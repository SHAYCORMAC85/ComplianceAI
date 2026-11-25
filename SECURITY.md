# Security boundary and review

## Supported use

Use loopback, one backend process, a trusted workstation and a shared officer workspace. Protect the UI, API and local files as one deployment. Remote hosting requires a separate review of HTTPS, identity, tenant isolation, network boundaries, parser isolation and operating procedures.

| Surface | Control verified by the offline suite | Residual risk |
| --- | --- | --- |
| Access and sign-off | Enrolled officer sessions, expiration and logout, completed-inspection guard, immutable attributed decision and transactional history | Every officer can read all inspections. OS administrators can access or alter local files. |
| Upload and parser | Pre-parse authentication, request budgets, bounded upload, filename and format checks, PDF and DOCX extraction limits | Native parsers run in process. A shared request budget or disk can be exhausted. Scanned pages need manual assessment. |
| Provider and prompt | Explicit external authorization, supplied-rule checks, exact target slices, synthetic adversarial tests | Authorized cloud processing may disclose the full extracted document over multiple calls. Prompt safeguards cannot guarantee correct or complete findings. |
| Secrets and logs | Server-side credentials, sanitized provider errors and structured security events | Operators must control ACLs, debugging, log retention and rotation. Historical credential exposure has not been independently assessed. |
| Storage and recovery | Evidence digests, SQLite checks, verified offline backup and isolated restore | Backup confidentiality requires separate encryption and key custody. Hashes require a trusted manifest. Recovery point is the last backup. |
| Dependencies | Phase 11 checked compatibility and queried 21 installed package versions | Partial point-in-time advisory review. Minimum versions allow future installations to differ. |

Use the deployment and recovery checklist in README.md. The rules are illustrative training summaries. Only an authorized human officer can record a final disposition.
