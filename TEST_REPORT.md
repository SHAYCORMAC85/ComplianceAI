# Final verification and handover

## Release decision

Local internship demonstration candidate, verified on Windows and Python 3.11. Phase 11 supplied 240 offline tests. Phase 12 added two tests covering the scoring contract and the history-page error state. The working-tree suite passed **242 tests in 26.17 seconds** with mock inference and temporary data. See the packaged-source check below. No public deployment was performed.

## Detection measurements

The bundled corpus comprises 20 labeled English target sections, including direct and indirect guarantees, risk, past performance, suitability, neutral communications, disclosures, context-dependent discrepancies, ambiguity, negation and untrusted instructions. Each target receives the same eligible rule catalog and bounded context in both provider modes. Section-positive means at least one validated finding. Finding-level matching requires the exact pair of rule ID and quoted passage within the same case. Duplicate pairs count once. Alternative but defensible wording can lose credit. Failed or unattempted targets are excluded and must be reported separately. There is no defined universe of negative individual findings.

| Mock result | TP | FP | TN | FN | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Section classification | 3 | 2 | 6 | 9 | 60% | 25% | 35.29% |
| Validated rule and exact quotation | 3 | 2 | N/A | 9 | 60% | 25% | 35.29% |

All 20 mock attempts returned a response. Mean adapter latency was about 0.044 ms, excluding prompt building, validation and disk work. Five of five candidates quoted the target exactly. No candidate referenced an invalid rule, so the observed invalid-rule rejection rate is undefined. Separate controlled tests reject unsupplied rules and context-only evidence. Full retrieval supplied all 17 labeled relevant rule-section pairs, along with 143 extra pairs. Coverage therefore reached 100% while detection recall was 25%.

### Authorized Gemini evaluation

The effective model was gemini-3.5-flash. The owner approved 20 initial requests, one possible retry per case, a 40-attempt ceiling, four requests per rolling minute and 1,024 output tokens per attempt. SDK retries were disabled for the runner. Input was estimated at 21,663 tokens per pass, using prompt characters divided by four. At the published standard input/output prices of $1.50/$9 per million tokens, estimated cost with full output allowances was about $0.22 for one pass or $0.44 if every attempt repeated. Account charges and actual token usage were not measured. [Google Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)

The live run encountered malformed finding JSON and a provider quota error. The limiter reported a 60,175-second delay and added its two-second buffer. The owner requested a stop. The process was terminated and its exit verified. It never switched models. Aggregate counters lived in process memory and had not been emitted at termination. Exact live request consumption, completed cases, latency, precision, recall, F1 and validation rates are unavailable. A numerical Gemini-versus-mock accuracy comparison would require a separately authorized completed run. The runner now emits aggregate progress after scored live cases and an attempt count before dispatch.

## End-to-end and performance

Run python -B -m evaluation.rehearsal with psutil installed to repeat this local workload. A fresh officer, mock provider and temporary data directory were used. Uvicorn and Streamlit both passed loopback readiness checks. The rehearsal signed in via HTTP, uploaded three synthetic 30-paragraph TXT documents, verified each 202 response and terminal progress, compared every returned passage for the inspected document to its exact source slice, exercised the highlight renderer, signed a decision and checked history. Reauthentication after backend restart and after a verified backup restored to a separate directory returned identical history. The automated suite separately drives Streamlit widgets and observes intermediate queue progress and quota waits. The real-process rehearsal used HTTP for officer actions and did not measure browser paint, mobile layout or full browser-session memory.

| Measurement on this laptop | Observed value |
| --- | --- |
| Idle process RSS after readiness | FastAPI 82.27 MiB, Streamlit 57.53 MiB before a browser session |
| TXT extraction, mean of 20 runs | 0.115 ms for the 30-paragraph fixture |
| HTTP upload acknowledgment, three sequential submissions | 1,158 / 1,368 / 1,085 ms |
| Submission start to observed completion, same order | 3.617 / 2.461 / 1.097 s |
| Backend process CPU over workload | 41.83% of one core |
| Scratch SQLite, 100 individual durable inserts / 100 indexed reads | Mean commit 5.253 ms, mean lookup 0.153 ms |

Observation includes upload and polling overhead. Earlier completions can go unseen while the client submits later documents. These are local samples, with one backend worker and no cloud inference. The controlled interruption test recovered a two-section job with one cached section and one newly analyzed section. The quota/failure-isolation test completed a later queued document after an earlier inspection failed. A new document ID intentionally prevents cross-document checkpoint reuse. Live Gemini throughput under sustained load remains unmeasured.

## Audit disposition and next work

- Corrected the history page's legacy JSON storage message and the behavior that converted a failed inventory read into an empty history. Corrected UI language about officer identity, regulatory authority and clean inspections.
- Corrected the example environment to default to offline evaluation. Actual runtime configuration takes precedence. Deployment still relies on a Python environment compatible with the declared minimum versions. A dependency lock and fresh-machine install test would improve reproducibility.
- Retained legacy JSON decision reads, the optional provider adapter, the compatibility officer-ID check and the earlier candidate benchmark because historical data, callers and measurement comparisons rely on them. No storage migration was required.
- Remaining limitations include partial-text PDF inspection, overlapping evidence highlights, no OCR, a small illustrative rule set, restricted context, no independently adjudicated legal labels and no full real-model accuracy result. Prioritize expert labeling and repeatable per-case quota-aware evaluation before expanding the catalog.
- The remaining operational risks are shared officer visibility, in-process native parsing, single-process operation, partial historical dependency checks and operator-managed disk capacity, encryption and backup keys. See SECURITY.md.
- Phase 12 modified the example environment, provider adapter, document route description, frontend home/findings/review/history copy, README, AGENTS and PROJECT_CONTEXT. Added evaluation/final_evaluation.py, evaluation/rehearsal.py, backend/tests/test_release.py, ARCHITECTURE.md, USER_GUIDE.md, TEST_REPORT.md, SECURITY.md and CHANGELOG.md. The release ZIP includes source, synthetic evaluation data, test suite, example configuration and handover documents.


## Packaged-source verification

An allowlist produced 86 archive entries. The independent CRC check passed. A fresh temporary extraction passed all 242 offline tests in 23.94 seconds using the installed Python 3.11 environment. The final archive adds this result to the handover documents. All executable and fixture bytes match the tested package. Dependency installation on a clean machine remains unverified.
