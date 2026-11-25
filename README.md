# AI Compliance Inspection Agent

An automated compliance document analyzer that assists financial compliance officers by parsing documents, checking clauses against regulatory rules with an LLM, validating findings rigorously, and presenting them in a review interface with human-in-the-loop oversight.

---

## Run the local demo

From this folder with Python 3.11 and the dependencies in requirements.txt installed, run the following command in PowerShell.

```powershell
python demo.py
```

On first launch, choose an officer ID and enter a private password of at least 12 characters when prompted. The launcher starts FastAPI on loopback port 8000 and Streamlit on loopback port 8501. Open http://127.0.0.1:8501 and use Ctrl+C in the launcher terminal to stop both processes. Enroll additional officers using `python -m backend.officers`.

1. Sign in using the shared sidebar. Open **Upload Document** and upload a synthetic TXT, text PDF or DOCX. Watch the section progress.
2. Open **Inspection Findings** and inspect the cited rule and highlighted source passage.
3. Open **Human Review**, review the evidence, select a decision and confirm. Sign-off is final for that inspection.
4. Open **Review History** to see the recorded decision. Restarting the demo preserves the inspection and its sign-off.

The launcher uses the backend provider configured in .env. An explicit LLM_PROVIDER environment variable takes precedence. For an offline demonstration, set LLM_PROVIDER to mock before launch. Keep real documents and credentials local. Use synthetic data for demonstrations.

## Development

Install dependencies with `python -m pip install -r requirements.txt`. Run the isolated offline suite with `python -B -m pytest -q -p no:cacheprovider backend/tests`. To start services separately, select `$env:LLM_PROVIDER = "mock"` in the backend shell, run `python -m uvicorn backend.main:app --host 127.0.0.1`, then run `python -m streamlit run frontend/app.py --server.address 127.0.0.1` in another shell.

PROJECT_CONTEXT.md records architecture, storage and verification. AGENTS.md contains contributor instructions.

## Inspection API and local worker

Run a single Uvicorn backend process against the local data directory. FastAPI lifespan must be enabled. INSPECTION_WORKERS controls the number of concurrent inspections inside that process (default 1, range 1–8). All workers share the provider limiter. WORKER_SHUTDOWN_SECONDS controls the drain interval (default 5, range 0–60). Closing the server stops new claims. Startup resumes interrupted work using saved evidence and matching chunk checkpoints.

| Request | Response |
| --- | --- |
| POST /api/documents/upload | Multipart field `file`. Returns HTTP 202 after extraction, source storage and queue registration. The body includes document_id, filename, file_type, status, status_url and message. |
| Idempotency-Key request header | Optional opaque key (1–200 characters). The same key, file type and bytes return the original ID and current state. Changed content or type returns 409. Keep the key when retrying a lost upload acknowledgment. |
| GET /api/documents/{id}/status | Returns QUEUED, PROCESSING, COMPLETED or FAILED, the processing stage, chunk counts, progress_percent, retry_at when known, updated_at and a sanitized error_message. |
| GET /api/documents/{id}/findings | Returns findings after completion. An unfinished or failed inspection returns 409. |
| POST /api/documents/{id}/retry | Returns 202 for an eligible failed, unsigned inspection using the same ID. Active, completed and signed inspections return 409. Unrecoverable evidence returns 422. |
| POST /api/review/{id}/decision | Requires a valid officer session and a completed, unsigned inspection. |

Poll status_url about every two seconds while the inspection is queued or processing. Terminal states end polling. Analyzed and cached counts include sections after validation. Skipped sections received no assessment. Failed identifies the section that stopped an attempt. Progress measures handled sections, including skips, and stays below 100 until the final database transaction commits. For historical records, progress_tracked=false indicates detailed counters were unavailable. Quota waits report the next eligible retry time when known. A final decision still requires a human officer.

Uploads and retries always enqueue work. Older callers that consumed findings immediately after POST must follow status_url. The earlier background query flag is unnecessary. Failed attempts can retain checkpoints and original files. SQLite durability and recovery assume a healthy local filesystem. A provider request that succeeds immediately before a crash can repeat if its checkpoint has not committed.
## Local backup and disaster recovery

Stop the demo before maintenance and pause officer enrollment. Run the following commands from the project root. The examples assume the parent directory for each destination already exists. Choose a new destination each time. Replace `data` with the active COMPLIANCE_DATA_DIR if you use a custom location.

```powershell
python -m backend.storage_backup backup data ..\ComplianceAI-backup-01
python -m backend.storage_backup verify ..\ComplianceAI-backup-01
python -m backend.storage_backup restore ..\ComplianceAI-backup-01 ..\ComplianceAI-restored-01
```

Backup takes the same exclusive owner lock as the inspection worker, snapshots the SQLite databases with the SQLite backup API, and copies recognized UUID-named original TXT, PDF and DOCX evidence and historical decision JSON. It includes unindexed originals with the project naming convention. It excludes configuration files, API keys in the environment, bearer sessions, logs, lock files and unrelated files. The officer database contains salted password digests. **Backups can contain confidential financial documents, findings and officer identities.** Use access-controlled, encrypted storage and a trusted copy of the manifest. The manifest contains filenames, schema versions, sizes and SHA-256 hashes. Hashes detect changes relative to a trusted manifest; they do not authenticate its author.

Restore verifies the source, copies into a temporary sibling directory, checks the staged databases and every file again, and publishes the new directory only after verification. It refuses an existing destination. There is no in-place overwrite command. For an authorized cutover, stop the old backend, keep its data directory, and explicitly select the verified replacement:

```powershell
$env:COMPLIANCE_DATA_DIR = (Resolve-Path ..\ComplianceAI-restored-01).Path
python demo.py
```

Use a fresh sign-in. Check the expected document IDs, source highlights, job states and review history. To roll back, stop the demo and select the previous data directory. Documents registered after the chosen backup are outside its recovery point.

On first use, each application database moves from unversioned schema 0 to schema 1 in one SQLite transaction. A newer database version, unsupported layout or inconsistent historical relationship requires operator investigation. Preserve the original and investigate a copy. A missing referenced upload prevents a complete backup even when the live inspection can still use canonical text. Verification deliberately does not manufacture missing evidence, counters or historical identities.

### Retention and capacity

Keep signed inspections, audit records and their source evidence together. Inventory unindexed uploads and legacy JSON by UUID; a missing inspection row alone is insufficient evidence for deletion. Review abandoned failed jobs and their checkpoints with the data owner. Completed jobs already release their checkpoints on commit. Budget disk space for originals, canonical text, findings, checkpoints and staged backups. Monitor the data and backup volumes and rehearse a restore after schema changes. Set retention periods and approve any deletion or offline database compaction separately. No scheduled cleanup is installed.

## Rule coverage and contextual inspection

The included eight rules are **illustrative training summaries**. They are not a maintained legal database. The default RULE_RETRIEVAL_MODE=full sends all active rule descriptions once per eligible target section. RULE_RETRIEVAL_MODE=keyword opts into at most four keyword hits, with all active rules supplied on a miss. A weak or incidental keyword hit can still exclude a relevant rule in that optional mode. Changes to the JSON catalog are picked up on backend restart or explicit rules reload.

INSPECTION_CONTEXT_CHARS defaults to 800 source characters on each side of the target (0 disables context, maximum 4,000 per side). Neighboring text can qualify a claim or explain a contradiction. The model may quote only the target. Validation requires an active rule from that request and an exact target-local source slice. A change in context, rendered rules, prompt, model or retrieval configuration invalidates prior inference for the affected section. Existing completed and signed inspections keep their original results.

The synthetic evaluation lives in evaluation/cases.json. Run the following command to benchmark the current selection settings and deterministic mock. The runner instantiates the mock provider explicitly.

```powershell
python -B -m evaluation.benchmark
```

See PROJECT_CONTEXT.md for the Phase 9 comparison, trade-offs and measurement limits. A complete candidate set can still yield a missed finding. Officers should examine relevant disclosures and distant sections themselves.


## Officer access and external processing

Sign in with HTTP Basic credentials at POST /api/review/session. Send the returned token as an Authorization header with the Bearer scheme for every document and review request. DELETE /api/review/session revokes the token. Sessions expire after one hour or a backend restart. All enrolled officers share access to the same inspection workspace and can make the first final decision on a completed inspection. Enrollment, backup and restore are local operating-system operations.

For a cloud upload or retry, explicitly set X-Authorized-Provider to the configured provider name (gemini or openai). The sidebar identifies the provider and the upload page requests confirmation. A missing or mismatched authorization returns 403. The worker checks the saved authorization before processing after restart. External requests include the full target section, bounded preceding and following text (default 800 characters per side), selected rule IDs, names, descriptions, categories and severity defaults, output fields and system instructions. Over multiple requests the provider can receive the entire extracted text. Account passwords, bearer tokens and original binary files are outside the inspection prompt. Use mock for offline work. Check organizational permission and provider retention terms before authorizing confidential text.

### Secure deployment checklist

- Run both services on loopback with a single backend process and one trusted local workspace. Keep debug/reload and HTTP wire or SDK debug logging off when handling sensitive data.
- Before any non-loopback use, require authenticated HTTPS for the UI and API, restrict network access, and review proxy limits, isolation and logging. HTTP Basic and bearer credentials require confidential transport. Public hosting requires a separate review.
- Limit OS read/write access on configuration, originals, SQLite files and journals, checkpoints, temporary directories, and backups. Anyone who can edit the officer database or runtime files is inside the trust boundary.
- Use encrypted volumes for live data and backups, including offline copies. Keep the recovery key separately under restricted custody and rehearse an offline restore with the key and a trusted manifest. Volume encryption preserves the existing backup format. It only protects a locked volume.
- Capture security events from stderr in restricted, rotated logs. Define retention and deletion with the data owner, restrict read access to designated operators, and protect archived logs against changes. The application does not install logging infrastructure. Keep review history with inspection evidence under its own retention policy.
- Provision backend secrets outside source control. Keep backups outside the project and protect the active data directory when overriding COMPLIANCE_DATA_DIR. Refresh dependency and OS security checks before distributing a build.


## Local internship release candidate

Start with USER_GUIDE.md for a fresh Windows installation, mock setup and presentation walkthrough. ARCHITECTURE.md describes the runtime and evidence flow. TEST_REPORT.md records the final verification, measurements and interrupted live evaluation. SECURITY.md covers operating boundaries. CHANGELOG.md summarizes the twelve phases.

Run the synthetic evaluation offline with `python -B -m evaluation.final_evaluation`. Live evaluation requires separate approval of the exact model, synthetic cases, quotas and budget for each run. The previous live session was stopped. For the optional process benchmark install psutil in the demo virtual environment and run `python -B -m evaluation.rehearsal`. It starts temporary loopback services and uses its own disposable data directories. Run from the project root.
