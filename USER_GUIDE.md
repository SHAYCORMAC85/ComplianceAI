# Officer and internship demonstration guide

## Prepare an isolated local demo

From a fresh release folder, use PowerShell and Python 3.11. Choose a new data directory for the demonstration. The example uses a unique directory so earlier inspection records stay separate.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:COMPLIANCE_DATA_DIR = Join-Path $env:TEMP ("ComplianceAI-demo-" + [guid]::NewGuid())
$env:LLM_PROVIDER = "mock"
.\.venv\Scripts\python.exe demo.py
```

Keep the directory path available for the restart demonstration. Enrollment prompts for an ID and a hidden password of at least 12 characters. Open http://127.0.0.1:8501 and sign in. The sidebar shows the effective provider. To demonstrate Gemini with separate authorization, configure the backend environment or private .env with LLM_PROVIDER=gemini, the approved LLM_MODEL_ID and GEMINI_API_KEY, then restart the backend. Remove any conflicting shell overrides. The example configuration uses offline mock by default.

## Five-minute presentation

1. Create a synthetic TXT from an explicit-return target in evaluation/cases.json. Include a neutral paragraph as a contrast. Use only the target and context as document content. Reserve expected labels for scoring.
2. Upload the file, record the document ID and follow progress. Cloud submissions require provider-specific authorization. Explain that skipped sections received no assessment.
3. Open Findings. Read the cited illustrative rule, rationale, source highlight and offsets. A matching quote establishes what the document said. Review the surrounding text independently before judging the risk.
4. Open Human Review, verify the document ID, record a reason and confirm the decision. Show the timestamp and attributed decision in Review History. Signing is final for this inspection.
5. Restart the demo using the same data path and sign in again. Look up the document ID. Explain the false negatives and false positives measured in TEST_REPORT.md and why human review remains necessary.

## Troubleshooting

- **401** — sign in again after expiry, logout or a backend restart.
- **403 on upload or retry** — confirm authorization for the provider currently shown, or switch to mock and restart.
- **409** — check for a pending inspection, signed decision or a reused submission key with different content.
- **413 or 422** — check upload size, file type, parser constraints and presence of extractable text. Image-only pages need manual review.
- **429** — review the status page for provider waits. For application throttling, allow the rolling request window to clear. Retry only an eligible failed job.
- **Port in use or database locked** — identify the existing demo instance. Run one backend per data directory. Use the offline maintenance commands in README.md after stopping services.
