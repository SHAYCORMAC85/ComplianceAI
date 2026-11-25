# ComplianceAI project context

Audited 25 November 2026. This Springer Capital internship project assists financial compliance officers by flagging passages for review. A verified finding means the evidence passed application checks. Its regulatory significance requires human judgment.

## Phase 12 local release candidate

Phase 11 was approved for the trusted local deployment. Release verification passed 242 offline tests, including a fresh extraction of the 86-entry source archive. The mock scored 25% recall on 20 targets. The live evaluation was stopped during a quota wait at the owner's request. ARCHITECTURE.md and README.md describe the current architecture and API contract. Earlier phase sections below are dated implementation snapshots. TEST_REPORT.md records release verification and limits, including the explicitly stopped live Gemini evaluation. USER_GUIDE.md contains the internship demonstration and startup workflow. The offline release candidate retains a single backend process, provider-specific authorization, canonical evidence and final human decisions.

## Historical development milestones

### Phase 10 — rule coverage, context and evaluation

Phase 9 was approved. The read-only assessment found eight active illustrative rules in 4,883 bytes of JSON. Their scope spans suitability, public communications, securities fraud, consumer practices, account identification, reporting controls, customer data safeguards and execution quality. Existing retrieval counts keyword substrings, returns at most four matches and otherwise takes the first four active rules. It can therefore omit a relevant rule even when it found an unrelated keyword. Chunking preserves offsets but separate paragraph calls previously omitted adjacent disclosures. Persistent checkpoints already include model, prompts, chunk identity and offsets. Prior validation verified global rule activity and target-local text but did not enforce membership in the actual request.

| Approach | Assessment for this catalog |
| --- | --- |
| Keyword ranking | Offline, deterministic, inexpensive; small prompts and better shortlist precision. Vocabulary gaps and catalog-order fallback caused misses. |
| All active rules (selected default) | One call per eligible target and no retrieval-stage exclusion. Eight descriptions increase input tokens and supply more irrelevant rules. As the catalog grows, revisit prompt size and model distraction. |
| Local embeddings | Could rank paraphrases for a larger catalog with smaller prompts; entails encoder download, CPU/memory cost, versioned indexing and uncertain domain recall. No extra Gemini call is necessary, but embeddings cannot improve coverage beyond all eight. |
| Hybrid keyword/embedding ranking | May balance lexical and semantic recall at scale. Requires labels, tuning, a low-confidence coverage policy and index invalidation. No measured need for the added model or infrastructure in the current deployment. |

Full-catalog mode is the default. The optional keyword mode uses full-catalog fallback on a miss. Rules are keyed by ID; active additions and edits are observed on catalog reload. No embeddings, vector store or external retrieval service were introduced. Retrieval strategy is recorded with findings and audits. The provider receives structured JSON with illustrative rules, target and bounded source context, including up to 800 characters on either side by default. The system prompt addresses untrusted document instructions, negation, conditional claims, quoted examples, historical performance, inconsistent figures and uncertain applicability. Exact passage and supplied-rule checks run independently of the model. New retrieval settings and context are included in checkpoint identity. Original rules and canonical documents were not edited.

**Synthetic benchmark.** The same 20 target sections have 17 labeled relevant rule–section pairs and 12 expected potential findings. A rule may be relevant to assessing a disclosure even if no finding is expected. Labels are illustrative and sometimes non-exclusive. Retrieval counts are micro-aggregated pairs. Mock predictions are scored separately by exact (rule ID, passage) match before validation. Each comparison uses the mock implementation and prompt from its respective phase.

| Measure | Phase 9 measured baseline | Phase 10 full coverage |
| --- | ---: | ---: |
| Retrieval TP / FP / FN | 13 / 46 / 4 | 17 / 143 / 0 |
| Retrieval precision / recall / F1 | .2203 / .7647 / .3421 | .1062 / 1.0000 / .1921 |
| Mock candidate TP / FP / FN | 3 / 3 / 9 | 3 / 2 / 9 |
| Mock precision / recall / F1 | .5000 / .2500 / .3333 | .6000 / .2500 / .3529 |
| Mean supplied rules | 2.95 | 8.00 |
| Estimated input tokens over targets | 15,022 | 21,663 |
| Expected uncached target requests, before retries | 20 | 20 |
| Median retrieval wall time (microseconds) | 115.30 | 3.10 |
| Benchmark CPU time (milliseconds) | 109.4 | 15.6 |
| Peak traced Python allocations (bytes) | 77,751 | 86,221 |

Latency used 50 selections per case with allocation tracing enabled. CPU time covers the benchmark loop; allocations exclude interpreter startup, loaded objects and provider infrastructure. Token estimates use combined prompt characters divided by four and rounded up per target; these are not provider tokenizer or billing measurements. Request counts refer to scored targets only. Real uploads also inspect eligible context paragraphs as targets. The pre-change run is recorded in evaluation/phase9_baseline.json. Use python -B -m evaluation.benchmark for the current run.

All **221 offline tests passed in 22.59 seconds**. Regression cases exercise full coverage, zero-hit fallback, reload/deduplication, clean and negated claims, rejection of an active but unsupplied rule, rejection of context-only quotations, cache invalidation, target-local offsets and an embedded approval instruction. Scripted providers demonstrate application boundaries; they cannot establish Gemini's instruction-following robustness or inference accuracy. The deterministic mock still missed nine labeled findings. The benchmark is small, English-only and lacks independently adjudicated legal labels. Distant contradictions outside the context window can still be missed. No live Gemini or embedding calls were made. Phase 10 awaits review.

### Phase 9 — storage integrity and disaster recovery

Phase 8 was approved. The pre-migration inventory included unindexed originals and legacy decisions. The Phase 8 source also supports jobs, checkpoints and signed history when the backend has initialized those tables. The audit did not identify the unindexed uploads as disposable or change any user data.

| Data | Authoritative location and lifetime |
| --- | --- |
| Document ID, filename, type, canonical text, chunks, exact offsets and evidence digest | SQLite inspections.record JSON. Original bytes live separately under uploads with UUID-prefixed filenames. Older records can lack a digest. |
| Job stage, counters, failure, timestamps, quota timing and idempotency | Inspection status/error in the record; inspection_jobs holds stage, counters, retry time, unique optional submission key and source digest. Startup recomputes progress for interrupted work using persisted checkpoints. |
| Successful LLM responses | chunk_checkpoints stores typed candidate results keyed on inference inputs. Completion removes checkpoints transactionally. The optional in-process LRU cache is bounded to 256 entries. |
| Findings and validation audit | Final findings and candidate-level audit in the inspection snapshot. Completion is atomic with job finalization and checkpoint cleanup. |
| Human sign-off | Attributed decision in the signed snapshot and immutable review_history row in one transaction. Older standalone UUID decision JSON remains separately readable. |
| Officer identity | Separate officers.sqlite3 stores enrolled names, salts and scrypt digests. Session tokens, rate-limiter window, worker wake notifications and memory-cache telemetry are process-local. Restart requires sign-in and resets local pacing state. |

Schema 1 uses PRAGMA user_version and separate SQLite application IDs. Migration runs in a write transaction; incompatible versions and inconsistent relationships fail closed. All application connections enable foreign keys and a bounded lock wait. Jobs, checkpoints and history reference inspections with restricted parent deletion. Existing primary keys, submission-key uniqueness and signed-history protections remain. Recursive trigger enforcement also blocks replacement of immutable history rows. The checkpoint document index supports final cleanup. Officer fields are constrained. Historical officer IDs remain attribution snapshots independent of today's officer roster. Damaged legacy decision files block sign-off.

Backup and restore commands and retention guidance are in README.md. Backup uses SQLite snapshots and the worker owner lock. It verifies schema, relational integrity, canonical evidence, finding offsets, decisions, external evidence and file hashes. Restore only publishes to a fresh directory. No evidence or historical decisions were automatically deleted. Stopping the application and enrollment during backup is required for a consistent cross-file snapshot.

Verification passed **192 offline tests in 24.30 seconds**, including all 176 previous tests. Separate new interpreter processes reopened the source and the restored synthetic databases. They returned matching inspection snapshots, job state, evidence bytes and signed attribution. Tests covered failed-inspection persistence, legacy decisions, checkpoint recovery, migration rollback with an orphan row, FK/uniqueness enforcement, lock contention, SQLite capacity failure, corruption, incompatible backups and unpublished failed restores. No live Gemini requests were made.

Limitations include local-disk durability, operator-managed retention, no automatic backup scheduling or off-site replication, and no cryptographic signature or encryption in the backup format. A completed backup is a point-in-time recovery point. Existing unauthenticated historical bytes cannot be retroactively proved genuine. Phase 9 awaits owner review.

### Phase 8 — persistent background inspection and live progress

Phase 7 was approved for local development. Its 169-test baseline passed before implementation. Phase 8 passed **176 offline tests in 15.19 seconds**. A real loopback HTTP integration test with a delayed synthetic provider returned 202 in 0.062 seconds, observed 1 of 2 sections evaluated at 50%, received 409 for early findings and officer sign-off, then retrieved results and recorded a decision after completion. Streamlit AppTest verified inspection reopening, a quota wait, 50% progress and terminal controls. No live provider calls were made.

Before Phase 8, synchronous uploads waited for inspection and optional FastAPI background tasks could be lost on restart. Upload and retry now enqueue durably and return 202 with a status URL. Source files are written before acceptance; the inspection and job are registered together in SQLite. Optional submission keys bind file type and bytes to one document ID. Reusing a key with different content returns 409. See README.md and the generated FastAPI /docs for the API contract.

A lifespan-owned pool (default one worker) claims queued jobs atomically and sleeps on an event when idle. A process-level file lock protects startup recovery. Interrupted jobs are requeued and matching checkpoints are reused. Gemini calls and waits run outside SQLite transactions. Completed findings, validation history, terminal job stage and checkpoint cleanup commit together. Stages include preparing, analyzing, validating, waiting for quota and finalizing. Counts distinguish analyzed, cached, skipped and failed sections. All-skipped inspections fail. Signed inspections remain immutable.

The local deployment requires one API process per data directory. Upload acknowledgment includes extraction time. Shutdown drains for a bounded interval before canceling unfinished inspections; an uncheckpointed provider call may repeat after restart. Old completed inspections lack historical per-chunk counters. The system has no multi-host scheduling, provider-side exactly-once guarantee or automated retention policy. Phase 8 is awaiting review.

### Phase 7 — retry and inspection recovery

Phase 6 was approved for local development. Its 155-test baseline passed before changes. Phase 7 verification passed **169 offline tests in 8.09 seconds**. A separate Streamlit AppTest with a mocked API selected a historical failed inspection, displayed the failure reason, submitted one retry for the original ID and removed the retry action after completion. No live Gemini requests were made.

The original audit found UTF-8 extracted text being dispatched to a PDF or DOCX parser according to the filename. At the start of Phase 7 the endpoint already reused the stored Document. Its remaining risks were separate eligibility and state writes, retries of unsigned completed inspections, and loss of chunk results on backend restart.

Retry now claims only a failed, unsigned inspection under a SQLite write transaction. It checks stored chunk order, coverage and exact slices. New records also carry a SHA-256 digest of canonical text and chunk boundaries. With intact evidence the upload file is unnecessary. If that evidence is damaged, recovery parses actual original bytes and requires the reconstructed evidence to match the saved digest. Missing, unreadable or mismatching evidence returns a recovery error. Historical records without a digest can retry from consistent saved chunks, but cannot verify a reconstructed original.

Successful chunk outputs, including empty results, are checkpointed in SQLite. Their keys include document ID, chunk index and offsets, model, prompt version, provider and rendered prompts including the supplied rules. On retry the validator checks candidates against the source again. Identical rule and offset pairs appear once in findings while candidate-level validation history remains available. Completion commits findings and removes temporary checkpoints in the same transaction.

The upload page can reopen failed inspections by ID and polls the existing status endpoint. Rate-limit delays and provider pacing remain in effect. The existing single-process background dispatch is retained. A process crash after the provider responds but before checkpoint commit may repeat that request. Failed or abandoned records retain checkpoints until completion. Loss of both verifiable evidence sources requires a new upload. Phase 7 awaits review.

### Phase 6 — human review security and decision integrity

The original audit counted 140 tests. The working tree passed 148 before Phase 6 and **155 after implementation**. The complete offline suite ran with isolated temporary storage and mocked inference. A separate Streamlit AppTest signed in, submitted a synthetic decision and displayed its attributed history over local HTTP.

The existing local officer enrollment, scrypt password verification and one-hour bearer sessions remain the authentication design. The API derives the recorded officer from the session. Older clients may supply an officer ID as a consistency check. Streamlit sends the session token and decision. Only completed, unsigned inspections accept sign-off.

SQLite takes a write lock before checking inspection state. The decision snapshot and history row commit together. A competing submission receives HTTP 409, and a write failure returns HTTP 500 with no partial decision. Signed inspection snapshots resist later updates. The audit table has one final decision per inspection, with document ID, officer, UTC timestamp, outcome and notes. Its update and delete triggers protect existing history rows. On backend startup, existing SQLite decisions populate missing history rows using their original attribution and timestamps. Legacy JSON records remain readable by UUID.

The history page uses `GET /api/review/{doc_id}/history`. History covers accepted decisions. Failed attempts and sign-in activity have no separate security event log. Local read access is unchanged, filesystem administrators retain control of the database, and the application has no amendment workflow.

The owner selected one backend process on loopback, local officer sign-in and SQLite. Run `python demo.py` from the project root. First launch prompts privately for officer enrollment. The launcher and direct API startup both honor the backend provider configuration. The offline test suite selects mock inference. The sections below this release summary record the **pre-implementation audit**.

- Upload and retry support an optional background response. Streamlit polls persisted status and processed-section count. Synchronous API callers retain the previous response contract. Retry reuses the extracted Document in all three formats. An active or signed inspection rejects another retry.
- The SQLite inspection database in data/decisions stores documents, chunks, findings, validation audits, progress and decisions. On startup an unfinished inspection becomes retryable. Process-local inference cache entries expire after one hour and depend on the provider and prompt contents. A restart can repeat model calls for unfinished inspections.
- Officer enrollment stores a salted scrypt password digest in data/officers.sqlite3. Login issues a one-hour bearer session scoped to the running process. Sign-off requires matching authenticated attribution and a completed, undecided inspection. A database write failure leaves the decision unrecorded. Existing JSON decisions are preserved and can be looked up using their original UUID. Old uploads lack historical inspection evidence and are not automatically re-inspected.
- Evidence with a source chunk must match that chunk. DOCX extraction includes body paragraphs and table cells in order. Long chunks are bounded and their slices checked. Embedded PDF text is supported. Image-only content needs separate review. Eight illustrative rules and bounded retrieval limit coverage.
- Release verification passed all 147 offline tests. The launcher also started and stopped both services successfully in isolated storage. The offline suite isolates uploads, decisions and provider settings automatically. An additional Streamlit AppTest smoke run used a real loopback FastAPI server, exercised all five pages and the home page, and signed a synthetic decision. No live provider traffic was used.
- Deployment scope is a trusted local workstation. Document reads and uploads are available to local callers. Public hosting, organizational SSO, OCR, regulatory catalog maintenance, retention policy and measured recall on representative documents remain outside this demo release.

## Historical audit — initial baseline

The handover describes five phases. The current tree supports the following inventory. The root README describes Phase 1 and no separate architecture document or local Git history was present to establish change dates.

| Reported phase | Implementation present |
| --- | --- |
| 1. Foundation | Pydantic document, chunk, rule, finding and review contracts. Paragraph and sentence splitting with source offsets. |
| 2. Inspection | Eight active example financial rules in backend/db/mock_rules.json. Keyword retrieval, prompt construction, mock, OpenAI and Gemini adapters, JSON parsing and a process-local cache. |
| 3. Evidence | Candidate schema checks, active rule lookup, exact quotation matching, offset calculation and per-candidate validation audit. |
| 4. API | FastAPI health, upload, retry, list, status, text, findings and review routes. TXT, PyMuPDF PDF and python-docx extraction. |
| 5. Officer interface | Streamlit dashboard, upload, findings with highlights, human review and review history. Theme and explicit text colors exist. Visual contrast was not measured during this audit. |

The current prompt and rules cover indirect representations, and retrieval records keyword or fallback strategy for findings. The Gemini adapter uses google-genai. Configurable timeouts, permanent error classification and transient retry handling are present. Historical expansion of the keywords and the earlier 128-test result come from the handover.

## Runtime and data flow

1. Streamlit pages use frontend/api/client.py to call FastAPI over HTTP. The client defaults to localhost port 8000 and a 180-second timeout. Shared components render metrics, evidence and review controls. Highlighting uses escaped slices of the extracted text.
2. backend/main.py mounts the document and review routers. Upload checks the extension, reads the file, checks the 15 MiB limit and writes original bytes under data/uploads. DocumentProcessor extracts canonical raw_text and indexed chunks. Offsets refer to Python character positions in this extracted string.
3. ComplianceService registers processing status and visits chunks sequentially. It skips trimmed text shorter than five characters. RulesEngine ranks active rules by keyword hits, with up to four rules per chunk. A miss selects a bounded subset of active rules in catalog order. Rules outside that subset can be missed.
4. LLMOrchestrator checks its in-memory cache by document ID, prompt version, model ID and chunk index. On a miss it submits the chunk and selected rules, parses JSON into RawFinding objects and caches successful results, including empty lists. A new upload receives a new ID. Rule changes are absent from the cache key.
5. Validator checks each candidate and its cited rule. OffsetCalculator looks in the chunk first and falls back to the whole document. A quote from another section can therefore receive the originating chunk index. A slice match establishes textual evidence only. ComplianceService saves validated findings and candidate audit results together after the last chunk.
6. DocumentStore holds documents, statuses, findings and audit results in memory. Uploaded originals and one decision JSON per document survive on disk. Review routes require a known in-memory document even for disk-backed decisions. The history page cannot recover the document inventory after restart. There is no public candidate-audit endpoint.

## Gemini and the reported 429

Effective backend settings, read through Settings with an allowlist, select Gemini, model `gemini-3.5-flash`, prompt `v1.0`, 90 seconds per attempt, two total attempts, four requests per rolling minute and a two-second cooldown buffer. A Gemini credential is configured. The handover's incident concerned `gemini-3.6-flash`, a reported five-RPM limit and an approximately 44-second delay. Model access, current account quota and live recovery were not exercised.

backend/services/rate_limiter.py supplies a process-wide rolling window and minimum one-second spacing. The orchestrator gates real provider attempts, parses RPC retryDelay, numeric Retry-After and message text, shares a suggested cooldown and uses backoff when a delay is unavailable. Authentication, permission, invalid request and missing model errors terminate early. Cache hits and skipped chunks reduce requests. Each remaining uncached chunk still requires a separate provider call.

The upload page shows a spinner, a quota-specific failure message and a retry button. Both upload and retry await the full inspection before returning. The client can time out before receiving a document ID. It receives no live chunk count or cooldown updates. The partial-findings button can show an empty list after failure because findings are committed at the end.

## Verification

The Python 3.11 offline run passed **140 tests in 4.88 seconds**. Backend, frontend, pytest configuration and sample fixture were copied into a temporary directory. The process selected the mock provider, cleared provider credentials, and ran `python -B -m pytest -q -p no:cacheprovider backend/tests`. This isolates API tests that write uploads and decision files. Tests cover models, extraction, offsets, validation, retrieval, indirect phrasing, orchestration, rate limiting, API workflows, frontend client behavior and highlighting. The run did not exercise browser rendering or real provider traffic. requirements.txt specifies minimum versions rather than a reproducible lock.

## Historical audit — proposed milestones

| Priority | Finding and next milestone | Verification target |
| --- | --- | --- |
| P0 | routes_review.py trusts a submitted officer ID and permits decisions before inspection completes. Repeated submissions overwrite the current decision. store.py reports success after a disk write error. Agree on identity and amendment policy, enforce the reviewer role and completion state, and make persistence failures visible. | Unauthorized and premature decisions fail. An authenticated officer can decide a completed inspection. A failed save cannot return success. Amendments retain attribution. |
| P0 | routes_documents.py retries by encoding extracted text as UTF-8 and dispatching on the original filename before the error handler. PDF and DOCX retries consequently enter binary parsers with text. Reuse the stored Document and guard duplicate or conflicting retries. | Fail a middle chunk once in each file format, retry the same ID, verify offsets and count provider calls for cached and failed chunks. |
| P1 | Limiter state is local to one process. A cooldown extended while acquire sleeps for spacing or capacity is not rechecked before dispatch. Quota messages hard-code Gemini, five RPM and a buffer. | Use a controllable clock to test cooldown extensions during waits. Surface structured retry timing for the actual provider. Establish worker assumptions before designing shared quotas. |
| P1 | Long inspections can outlast the UI timeout. Agree on a job boundary and durable inspection records before changing the API. Define partial-result visibility and bind decisions to a completed inspection version. | Return an ID early, report processed and total chunks, resume after interruption, and recover evidence and decisions across restart. |
| P1 | Evidence can be attributed to the wrong chunk. DOCX paragraph extraction omits tables and PDF text extraction has no OCR path. Configured chunk limits do not reach the route's default processor, whose 2,500-character sentence threshold can be exceeded. | Add repeated-quote, long-sentence, table and scanned-page fixtures. Surface extraction coverage and verify every displayed slice against canonical text. |
| P2 | Fixed fallback order and paragraph-level requests trade coverage against quota. The cache lacks rule versioning and has no default expiry. | Measure recall and calls on labeled synthetic documents, then evaluate rule selection, bounded batching and invalidation with the same evidence checks. |
| P2 | API tests leave files under project data when run in place. Uploads are fully read before size checks. Development CORS is permissive, raw provider errors can reach clients, and disk artifacts lack a defined retention lifecycle. | Isolate fixtures by default, bound reads, redact errors and agree on access and retention before handling shared confidential data. |

## Phase 11 security review and implementation (2026-11-25)

The approved deployment is a trusted local workstation with one backend process and a shared workspace for enrolled officers. The public surface includes health and API schema documentation. Document and review data require authentication. The OS operator enrolls users and manages backups. Direct API clients must sign in before uploading, reading, retrying or reviewing. The README describes the headers and operational deployment checklist.

| Initial finding | Assessed impact | Implemented control or outstanding action |
| --- | --- | --- |
| High: anonymous document, evidence and history access, upload and retry | A client able to reach the API could read financial text or trigger provider work. Loopback reduced exposure to local clients. | Authenticate before parsing uploads or resolving records. Session tokens bind human decisions to the officer. |
| High for confidential material: cloud processing lacked explicit per-document authorization | Text from multiple chunks can disclose the entire extracted document. | Provider-specific confirmation on upload and retry and a persisted check at job recovery. Use mock for unapproved data. |
| Medium: unbounded login attempts and limited parser resource controls | Password guessing, excessive CPU, memory, temporary storage or queue load | Rolling per-process limits, bounded request reading, filename checks, format validation and extraction budgets. |
| Medium: upstream/parser errors and configuration detail | Responses or diagnostic output could disclose internal information. | Generic client errors, minimized health response and structured security events. Local debug logging and filesystem access still require operator controls. |
| High if copied outside trusted storage: plaintext backups and officer digests | A reader could inspect financial data and attempt offline password guessing. | Existing checksum/restore procedures retained. Restrict ACLs, encrypt volumes and keep recovery keys separately. |
| Medium: prompt manipulation and incorrect model judgments | An incorrect but verbatim finding could influence a reviewer. | Structured prompt, supplied-rule validation, exact target-only offsets and human sign-off. Offline adversarial tests cannot measure live-model resistance. |

Passwords use scrypt with individual random salts. One-hour opaque bearer sessions are process-local, and logout revokes them. Global rolling limits per minute are 12 login attempts, 60 authenticated POSTs, 1,200 other authenticated requests and 1,800 API requests overall (excluding preflights). The provider quota limiter is independent. Three uploads can enter processing concurrently. Multipart bodies are limited to 16 MiB including framing, uploaded files to 15 MiB, and other API bodies to 32 KiB. Extraction caps include one million characters, 4,096 chunks, 300 PDF pages, and 1,024 DOCX members totaling at most 64 MiB uncompressed. Original bytes, canonical text and target offsets are retained for accepted documents.

The security logger emits JSON with UTC time, operation, outcome and optional pseudonymous officer reference. Enrollment, authentication, logout, access denial, rejected decisions and backup/verify/restore operations produce events. Decision history remains a separate SQLite transaction record. Security events require an operator-managed restricted sink, rotation, retention and tamper protection. OS account or direct database access can bypass application controls.

Dependency review: pip check found no broken installed requirements. An OSV query for 21 installed direct and selected transitive package versions returned no matching advisories. The optional OpenAI package was absent. This was a point-in-time partial inventory. Source control history was unavailable in this project folder; historical secret exposure cannot be assessed. Local secrets and default runtime storage are covered by ignore patterns.

Remaining limitations include shared officer visibility, workstation-wide quotas that one client can consume, local process resets clearing sessions and limits, native document parsers running in-process, and no hard disk or backlog quota. External processing requires the organization's own provider and retention review. UI/API TLS, workstation ACLs, encrypted volumes, network isolation, backup key recovery and centralized logging require deployment-level verification. Preserve unmatched originals and legacy decisions.

Phase 11 changed files (paths relative to project root):

- Backend: main.py, officers.py, security.py, security_events.py, storage_backup.py under backend; api/routes_documents.py, api/routes_review.py, db/store.py, models/api_schemas.py, services/document_processor.py, services/inspection_worker.py and services/llm_orchestrator.py under backend.
- Streamlit: frontend/api/client.py, frontend/components/{sidebar,review,findings}.py and frontend/pages/{2_Upload_Document,4_Human_Review}.py.
- Offline tests: backend/tests/conftest.py and test_api.py, test_frontend_client.py, test_inspection_jobs.py, test_rate_limiter.py, test_retrieval_coverage.py, test_security.py and test_storage_recovery.py in that directory.
- Operations: .gitignore, README.md, PROJECT_CONTEXT.md and AGENTS.md.

Verification: 240 offline tests passed in 21.88 seconds, up from the 221-test baseline. The suite includes authenticated loopback HTTP submission, progress and review, Streamlit inspection polling, interruption recovery, backup integrity, and synthetic authorization, upload, provider-consent and adversarial evidence regressions. No live Gemini calls were made. Phase 11 awaits local review.
