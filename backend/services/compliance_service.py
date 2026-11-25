"""
Compliance Inspection Service
-----------------------------
Coordinates the end-to-end document compliance analysis workflow:
Document -> Semantic Chunks -> Rules Retrieval -> LLM Analysis -> Validation & Offsets -> Persistence.

Keeps business orchestration decoupled from HTTP route handlers.
"""

import logging
from typing import List, Optional, Tuple
from backend.config import settings
from backend.db.store import DocumentStore, document_store
from backend.models.document import Document
from backend.models.finding import ValidatedFinding, FindingValidationResult
from backend.services.llm_orchestrator import (LLMOrchestrator, LLMRateLimitError, LLMServerError,
                                               LLMTimeoutError, LLMMalformedJSONError)
from backend.services.rules_engine import RulesEngine
from backend.services.inspection_progress import cache_hit, report
from backend.services.validator import Validator

logger = logging.getLogger(__name__)


class ComplianceService:
    """
    Coordinates the compliance inspection workflow across sections of a document.
    """

    def __init__(
        self,
        rules_engine: Optional[RulesEngine] = None,
        llm_orchestrator: Optional[LLMOrchestrator] = None,
        validator: Optional[Validator] = None,
        store: Optional[DocumentStore] = None
    ):
        self.rules_engine = rules_engine or RulesEngine()
        self.llm_orchestrator = llm_orchestrator or LLMOrchestrator()
        self.validator = validator or Validator(rules_engine=self.rules_engine)
        self.store = store or document_store

    async def analyze_document(
        self,
        document: Document
    ) -> Tuple[List[ValidatedFinding], List[FindingValidationResult]]:
        """
        Executes end-to-end inspection on an extracted document.
        
        Steps:
        1. Updates status to PROCESSING.
        2. Iterates through chunks, retrieving relevant rules for each chunk.
        3. Calls LLMOrchestrator to get structured candidate findings.
        4. Validates each candidate through the 3-stage Validator and calculates offsets.
        5. Persists verified findings and full audit trail into DocumentStore.
        6. Updates status to COMPLETED (or FAILED if an unhandled error occurs).
        
        Args:
            document: Processed Document model with chunks.
            
        Returns:
            Tuple of (verified_findings, audit_trail).
        """
        document_id = document.id


        all_verified_findings: List[ValidatedFinding] = []
        seen = set()
        all_audit_results: List[FindingValidationResult] = []

        in_chunk = False
        evaluated = 0
        try:
            for chunk in document.chunks:
                in_chunk = True
                cache_hit.set(False)
                report("ANALYZING")
                # Skip empty or non-substantive whitespace chunks to preserve API quota
                if not chunk.text or len(chunk.text.strip()) < 5:
                    logger.debug(f"Document {document_id} Chunk #{chunk.index}: skipping non-substantive chunk.")
                    report("ANALYZING", "skipped")
                    continue

                radius = settings.INSPECTION_CONTEXT_CHARS
                before = document.raw_text[max(0, chunk.char_start-radius):chunk.char_start]
                after = document.raw_text[chunk.char_end:chunk.char_end+radius]
                mode = settings.RULE_RETRIEVAL_MODE
                applicable_rules, strategy = self.rules_engine.select_for_inspection(chunk.text, mode)
                if not applicable_rules:
                    # In the rare event that no active rules exist in the database
                    logger.warning(f"No active compliance rules available for document {document_id} chunk #{chunk.index}.")
                    report("ANALYZING", "skipped")
                    continue

                logger.info(
                    f"Document {document_id} Chunk #{chunk.index}: retrieved {len(applicable_rules)} rules "
                    f"via {strategy.upper()} strategy."
                )

                # 2. Query LLM Orchestrator for structured candidate findings
                raw_findings = await self.llm_orchestrator.analyze_section(
                    document_id=document_id,
                    chunk=chunk,
                    rules=applicable_rules,
                    before=before, after=after, retrieval_config=(mode, radius),
                    checkpoints=self.store
                )

                report("VALIDATING")

                # 3. Validate every candidate finding and compute precise offsets
                verified, audit = self.validator.validate_findings(
                    candidates=raw_findings,
                    document_text=document.raw_text,
                    document_id=document_id,
                    chunk=chunk,
                    allowed_rule_ids={r.rule_id for r in applicable_rules},
                    retrieval_strategy=strategy
                )

                for finding in verified:
                    key = (finding.rule_id, finding.offset_start, finding.offset_end)
                    if key not in seen:
                        seen.add(key)
                        all_verified_findings.append(finding)
                all_audit_results.extend(audit)
                evaluated += 1
                report("ANALYZING", "cached" if cache_hit.get() else "analyzed")

            in_chunk = False
            if not evaluated:
                self.store.update_status(document_id, "FAILED", "No sections could be evaluated.")
                return [], []
            report("FINALIZING")
            # 4. Save to repository
            self.store.save_findings(
                document_id=document_id,
                findings=all_verified_findings,
                audit_trail=all_audit_results
            )
            logger.info(
                f"Inspection completed for document '{document_id}': "
                f"{len(all_verified_findings)} verified findings."
            )
            return all_verified_findings, all_audit_results

        except LLMRateLimitError as rle:
            if in_chunk:
                delay = None if rle.retry_delay is None else rle.retry_delay + self.llm_orchestrator.rate_limiter.safety_buffer
                report("WAITING_FOR_QUOTA", "failed", delay=delay)
            msg = "Provider rate limit reached. Retry after the quota resets."
            if rle.retry_delay is not None:
                wait_s = round(rle.retry_delay + self.llm_orchestrator.rate_limiter.safety_buffer)
                msg = f"Provider rate limit reached. Retry in about {wait_s} seconds."
            logger.warning(f"Rate limit halted inspection for document '{document_id}'")
            self.store.update_status(document_id, "FAILED", error_message=msg)
            raise
        except (LLMTimeoutError, LLMServerError, LLMMalformedJSONError) as exc:
            if in_chunk:
                report("ANALYZING", "failed")
            if isinstance(exc, LLMTimeoutError):
                message = "Provider request timed out."
            elif isinstance(exc, LLMMalformedJSONError):
                message = "Provider returned malformed findings."
            else:
                message = "Temporary provider or network failure."
            self.store.update_status(document_id, "FAILED", error_message=message + " Retry this inspection to resume.")
            raise
        except Exception as e:
            if in_chunk:
                report("ANALYZING", "failed")
            logger.error("Inspection %s failed (%s)", document_id, type(e).__name__)
            self.store.update_status(document_id, "FAILED", error_message="Inspection error. Check the provider configuration and retry.")
            raise


# Global service instance
compliance_service = ComplianceService()

