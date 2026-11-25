"""
Finding Validator Service
-------------------------
Enforces rigorous multi-stage quality control on candidate compliance findings:
1. Schema Validation (Pydantic models, required fields, severity enum).
2. Rule ID Verification (Must exist as an ACTIVE rule in the RulesEngine).
3. Verbatim Passage Matching (Must appear word-for-word in the original document text).
4. Offset Calculation & Invariant Verification (Calculates exact character coordinates).

Crucial Safety Invariant:
Any candidate finding that fails ANY check is immediately discarded and logged in
an audit trail. Rejected findings NEVER appear in the verified findings list.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import ValidationError
from backend.models.document import DocumentChunk
from backend.models.finding import (
    RawFinding,
    ValidatedFinding,
    FindingValidationResult,
    ValidationStageEnum,
)
from backend.services.offset_calculator import (
    OffsetCalculator,
    OffsetCalculatorError,
)
from backend.services.rules_engine import RulesEngine

logger = logging.getLogger(__name__)


class Validator:
    """
    Validates candidate compliance findings and computes precise character offsets.
    """

    def __init__(
        self,
        rules_engine: Optional[RulesEngine] = None,
        offset_calculator: Optional[OffsetCalculator] = None
    ):
        """
        Args:
            rules_engine: RulesEngine instance for rule ID verification.
            offset_calculator: OffsetCalculator instance for offset resolution.
        """
        self.rules_engine = rules_engine or RulesEngine()
        self.offset_calculator = offset_calculator or OffsetCalculator()

    def validate_single_finding(
        self,
        candidate: Union[RawFinding, Dict[str, Any]],
        document_text: str,
        document_id: str = "doc-default",
        chunk: Optional[DocumentChunk] = None,
        retrieval_strategy: Optional[str] = None,
        allowed_rule_ids: Optional[set[str]] = None
    ) -> FindingValidationResult:
        """
        Executes the three-check validation pipeline plus offset calculation
        for a single candidate finding.
        
        Args:
            candidate: Raw finding model or dictionary.
            document_text: Original, un-modified document text.
            document_id: Identifier of the document.
            chunk: Optional DocumentChunk providing section context.
            
        Returns:
            FindingValidationResult documenting whether the finding passed or failed,
            including stage of failure and rejection reasons.
        """
        # ----------------------------------------------------------------------
        # Stage 1: Pydantic Schema Validation
        # ----------------------------------------------------------------------
        raw_finding: Optional[RawFinding] = None
        if isinstance(candidate, RawFinding):
            raw_finding = candidate
        elif isinstance(candidate, dict):
            try:
                raw_finding = RawFinding.model_validate(candidate)
            except ValidationError as err:
                errors = [f"{e['loc'][0]}: {e['msg']}" for e in err.errors() if 'loc' in e and len(e['loc']) > 0]
                reason_msg = f"Schema validation failed: {', '.join(errors)}"
                logger.warning("Finding rejected at SCHEMA_VALIDATION")
                return FindingValidationResult(
                    finding=candidate,
                    is_valid=False,
                    validation_status="REJECTED",
                    failed_stage=ValidationStageEnum.SCHEMA_VALIDATION.value,
                    failure_reasons=[reason_msg],
                    retrieval_strategy=retrieval_strategy,
                    validated_finding=None
                )
        else:
            return FindingValidationResult(
                finding={"unsupported_type": str(type(candidate))},
                is_valid=False,
                validation_status="REJECTED",
                failed_stage=ValidationStageEnum.SCHEMA_VALIDATION.value,
                failure_reasons=["Candidate finding must be a RawFinding instance or a dictionary."],
                retrieval_strategy=retrieval_strategy,
                validated_finding=None
            )

        # ----------------------------------------------------------------------
        # Stage 2: Rule ID Verification
        # ----------------------------------------------------------------------
        rule = self.rules_engine.get_rule(raw_finding.rule_id)
        if rule is None or (allowed_rule_ids is not None and raw_finding.rule_id not in allowed_rule_ids):
            reason_msg = (f"Rule ID '{raw_finding.rule_id}' does not exist in the active compliance rules database."
                          if rule is None else f"Rule ID '{raw_finding.rule_id}' was not supplied for this section.")
            logger.warning("Finding rejected at RULE_VALIDATION")
            return FindingValidationResult(
                finding=raw_finding,
                is_valid=False,
                validation_status="REJECTED",
                failed_stage=ValidationStageEnum.RULE_VALIDATION.value,
                failure_reasons=[reason_msg],
                retrieval_strategy=retrieval_strategy,
                validated_finding=None
            )

        if not rule.active:
            reason_msg = f"Rule ID '{raw_finding.rule_id}' is marked inactive and cannot be cited for violations."
            logger.warning("Finding rejected at RULE_VALIDATION")
            return FindingValidationResult(
                finding=raw_finding,
                is_valid=False,
                validation_status="REJECTED",
                failed_stage=ValidationStageEnum.RULE_VALIDATION.value,
                failure_reasons=[reason_msg],
                retrieval_strategy=retrieval_strategy,
                validated_finding=None
            )

        # ----------------------------------------------------------------------
        # Stage 3: Exact Verbatim Passage Matching
        # ----------------------------------------------------------------------
        if not raw_finding.passage or not raw_finding.passage.strip():
            reason_msg = "Passage is empty or whitespace-only."
            logger.warning("Finding rejected at PASSAGE_VERBATIM_CHECK")
            return FindingValidationResult(
                finding=raw_finding,
                is_valid=False,
                validation_status="REJECTED",
                failed_stage=ValidationStageEnum.PASSAGE_VERBATIM_CHECK.value,
                failure_reasons=[reason_msg],
                retrieval_strategy=retrieval_strategy,
                validated_finding=None
            )

        if raw_finding.passage not in document_text:
            reason_msg = (
                f"Passage does not appear verbatim in the original document text. "
                f"Candidate passage: '{raw_finding.passage[:80]}...'"
            )
            logger.warning("Finding rejected at PASSAGE_VERBATIM_CHECK")
            return FindingValidationResult(
                finding=raw_finding,
                is_valid=False,
                validation_status="REJECTED",
                failed_stage=ValidationStageEnum.PASSAGE_VERBATIM_CHECK.value,
                failure_reasons=[reason_msg],
                retrieval_strategy=retrieval_strategy,
                validated_finding=None
            )

        # ----------------------------------------------------------------------
        # Stage 4: Character Offset Calculation & Invariant Verification
        # ----------------------------------------------------------------------
        try:
            start_offset, end_offset = self.offset_calculator.calculate_offsets(
                document_text=document_text,
                passage=raw_finding.passage,
                chunk=chunk
            )
        except OffsetCalculatorError as offset_err:
            reason_msg = f"Failed to compute valid character offsets: {offset_err}"
            logger.warning("Finding rejected at OFFSET_CALCULATION")
            return FindingValidationResult(
                finding=raw_finding,
                is_valid=False,
                validation_status="REJECTED",
                failed_stage=ValidationStageEnum.OFFSET_CALCULATION.value,
                failure_reasons=[reason_msg],
                retrieval_strategy=retrieval_strategy,
                validated_finding=None
            )

        # Construct verified ValidatedFinding
        validated = ValidatedFinding(
            passage=raw_finding.passage,
            rule_id=raw_finding.rule_id,
            reason=raw_finding.reason,
            severity=raw_finding.severity,
            offset_start=start_offset,
            offset_end=end_offset,
            document_id=document_id,
            chunk_index=chunk.index if chunk is not None else None,
            retrieval_strategy=retrieval_strategy,
            is_valid=True
        )

        return FindingValidationResult(
            finding=raw_finding,
            is_valid=True,
            validation_status="PASSED",
            failed_stage=None,
            failure_reasons=[],
            retrieval_strategy=retrieval_strategy,
            validated_finding=validated
        )

    def validate_findings(
        self,
        candidates: List[Union[RawFinding, Dict[str, Any]]],
        document_text: str,
        document_id: str = "doc-default",
        chunk: Optional[DocumentChunk] = None,
        retrieval_strategy: Optional[str] = None,
        allowed_rule_ids: Optional[set[str]] = None
    ) -> Tuple[List[ValidatedFinding], List[FindingValidationResult]]:
        """
        Validates a list of candidate findings.
        
        Args:
            candidates: List of candidate RawFinding models or dictionaries.
            document_text: Full source document string.
            document_id: Associated document ID.
            chunk: Optional source chunk for offset disambiguation.
            retrieval_strategy: Optional string ('keyword' or 'fallback').
            
        Returns:
            Tuple of:
            - List of ValidatedFinding models (strictly valid findings only).
            - List of FindingValidationResult models (complete audit trail of all candidates).
        """
        verified_findings: List[ValidatedFinding] = []
        audit_trail: List[FindingValidationResult] = []

        for candidate in candidates:
            result = self.validate_single_finding(
                candidate=candidate,
                document_text=document_text,
                document_id=document_id,
                chunk=chunk,
                allowed_rule_ids=allowed_rule_ids,
                retrieval_strategy=retrieval_strategy
            )
            audit_trail.append(result)

            if result.is_valid and result.validated_finding is not None:
                verified_findings.append(result.validated_finding)

        return verified_findings, audit_trail

