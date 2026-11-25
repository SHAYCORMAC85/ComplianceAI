# Working on ComplianceAI

Read PROJECT_CONTEXT.md before continuing the project. Verify relevant behavior against current code and tests. Preserve existing working features and ask the owner before major changes to architecture, storage, authentication or the inspection job lifecycle.

- Keep model output advisory. Only a human compliance officer may approve or reject a document. Keep inspection status, evidence validation and human decisions distinct.
- Preserve the canonical extracted text and half-open Python character offsets. Require exact equality between the evidence passage and its source slice. Check repeated passages, Unicode and whitespace when modifying extraction, validation or highlighting.
- Keep provider adapters behind LLMOrchestrator and inspection coordination in ComplianceService. Review changes to retrieval, prompts or cache identity for stale results and lost provenance.
- Use synthetic fixtures and mock providers for automated tests. Never print credentials, dump environment settings, copy private uploads into fixtures, or include document text or officer records in handovers. Avoid unnecessary paid API requests.
- Use Python 3.11. Run `python -B -m pytest -q -p no:cacheprovider backend/tests`. The suite selects temporary data storage and mock inference before loading services. Keep these overrides ahead of application imports.
- The supported demo is a single FastAPI process and Streamlit bound to loopback. Use `python demo.py` for launch. Preserve SQLite recovery, immutable officer decisions, authentication and the HTTP 202 submission contract. Exercise the FastAPI lifespan in integration tests. Upload and retry enqueue work, and clients follow status_url through a terminal state. Keep claims and final publication atomic, wait outside database transactions, and expose skipped and cached counts explicitly.
- Keep secrets and runtime data local. Preserve user records during testing and debugging. Read effective settings through a narrow allowlist and report credential presence only.
- Run relevant offline tests after changes, then the complete suite for cross-layer changes. Report the actual result, limitations and any unverified live behavior. Update PROJECT_CONTEXT.md when a milestone changes the verified architecture or closes a listed issue.

- Use backend/db/schema.py for application SQLite connections and versioned migrations. Keep migration DDL, data copy, integrity checks and version changes in one transaction. Reject unsupported future versions. Exercise both clean creation and legacy migration in isolated data.
- Use the offline backup utility for recovery rehearsals. Use synthetic records and a fresh destination. Never overwrite active data, remove unlinked evidence or bypass review-history protections for cleanup or test isolation.

- For retrieval and prompt changes, run the synthetic section benchmark and report rule coverage separately from mock candidate quality. Preserve the supplied-rule allowlist, target-only quotation checks, context bounds and checkpoint invalidation. Treat the local rules as illustrative and preserve their legal wording.

## Phase 11 security contract

- All document and review-data requests require an enrolled officer session. Keep tokens in the individual Streamlit session. Keep CLI administration behind OS access controls. Test anonymous, expired, revoked and authenticated requests when modifying API access.
- Preserve explicit per-submission external-provider authorization, including retries and restart recovery. Never send private source material during development. Keep abuse limits independent from the provider quota limiter.
- Treat all parser input, provider output and filenames as untrusted. Preserve canonical evidence and target-only validation. Use bounded synthetic fixtures for resource-limit tests. Keep credentials, passages and upstream error bodies out of logs and public errors.
- Retain original uploads and historical decisions. Seek approval before changing the backup format, trust model, deployment boundary or public API contract.

## Final release verification

Run the evaluation module in its default offline mode for regressions. Live evaluation requires fresh explicit approval of provider, model, synthetic corpus, quota and total attempts. A stopped or incomplete run has no full-corpus accuracy score. Package only project source, synthetic fixtures, public templates and handover documents. Exercise the packaged source in isolated storage.
