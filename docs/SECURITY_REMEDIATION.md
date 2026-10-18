# Pentagon security remediation track

Updated: 2026-10-11

This tracks the supplied security, reliability, and pentest audit against the
current checkout. “Verified” means the local regression suite exercises the
behavior. Live database, provider, and container checks are called out
separately. The supplied 118/118 Supabase RLS result is accepted as prior
evidence; this pass did not connect to or change the live project.

## Remediation ledger

| Area | Result | Evidence / remaining boundary |
|---|---|---|
| Secrets in traces and logs | Verified | Free-text and structured credentials are redacted from tool traces and audit summaries; raw shell commands are excluded from server logs and sanitized before approval display. Regression coverage is in `tests/test_agent_traces.py`, `tests/test_command_runner.py`, and `tests/test_security_remediation.py`. |
| NVIDIA key storage and rotation | Verified locally | Encryption/masking and key replacement are exercised in `tests/test_key_rotation.py`. Local ignored `.env` permissions were checked as `0600`; source/history and checked shell-history scans found no credential-shaped service key or database URI. This is syntax scanning, not proof that an externally exposed credential is safe. |
| Previously shared Supabase key and database password | Deferred by user | No revocation or rotation was performed. Rotate the previously shared service key and database password in Supabase before any deployment that depends on them. No secret value is stored in this report. |
| Prompt injection and retrieved content | Verified | Search, retrieved documents, and vision results are framed as untrusted source material; tool calls and result text are validated/redacted. Offline injection suite and the full backend suite pass. |
| MCP tiers and environment | Verified in code/tests | `readOnlyHint` cannot lower configured risk; subprocess environment is allowlisted. Provider-issued OAuth scopes cannot be validated by this generic stdio bridge and remain deployment-specific. |
| User-created skills | Verified | Skills are owner-filtered on listing and matching, ownership is checked for mutations, and skill text is scoped as untrusted guidance. Covered by skills/router tests. |
| Agent autonomy and approvals | Verified | Explicit category settings override defaults derived from the saved Restricted/Balanced/Trusted level. `never_allow` blocks before execution; stale approval answers are rejected; denied action fingerprints are not retried; ask-first approvals are user-scoped. Eval and permission-flow suites pass. |
| API caller boundary | Verified for local installation | Every `/api/*` operation requires the installation capability and frontend requests pass it. Missing-token requests return 401. This is not user authentication: caller-supplied IDs and a build-time token do not support safe public or multi-user hosting. |
| Input and request bounds | Verified | A 130 MiB request ceiling preserves the 120 MiB video limit; text validators reject control characters; validation responses omit submitted values. Regression tests pass. |
| Provider rate limits | Verified for one process | Every provider request is metered, background work uses a lower-priority lane, and internal budget exhaustion is reported clearly in SSE. The in-memory limiter is process-local; multi-worker hosting needs shared rate state. |
| CORS | Verified in prior audit | The existing preflight check from an unconfigured origin returned no allow-origin header. Allowed origins remain explicit. |
| Shell and code execution | Fail-closed; live container unverified | Python execution is not registered without Docker. Shell execution requires Docker plus a dedicated workspace and uses no network, read-only root, dropped capabilities, non-root UID, and resource limits. Static argv and refusal tests pass. Docker is unavailable on this machine, so no live container was run. Bounded text artifact writing remains available independently of code execution. |
| Conversation and file deletion | Verified locally | Deletion cleans vectors, uploaded/generated storage, and checkpoint state before committing SQL deletion; failures retain relational metadata and return a sanitized error. Cleanup and retry tests pass. Remote Supabase Storage failure behavior was not exercised live. |
| Append-only audit log | Partially verified | Runtime SQLite/PostgreSQL triggers reject direct audit-row mutation; direct SQLite DML regression passes. No live PostgreSQL/Supabase trigger check was run in this pass. |
| Context and duplicate actions | Verified locally | Model history is bounded and compacted; approval batches cover only pending calls; duplicate/retried actions and concurrent stream side effects have regression coverage. |
| Startup and database recovery | Verified locally | Startup degrades when the database is unavailable, API routes return sanitized 503 responses, and initialization retries. No live Supabase outage was induced. |
| Skill routing scale | Verified in prior audit | The 1,000-skill synthetic run measured 13.6 ms median and 15.3 ms maximum; no router internals changed in this pass. |
| Generated documents | Verified locally | Formula-leading CSV/XLSX values are neutralized; generated-file ownership and preview/download paths are tested. `openpyxl` is declared in backend requirements. |

## Verification log

| Date | Check | Result |
|---|---|---|
| 2026-10-11 | Backend: `python -m pytest -q` | 921 passed, 4 skipped, 1 dependency deprecation warning. |
| 2026-10-11 | Frontend: `npm run check` | Passed. |
| 2026-10-11 | Frontend: `npm run build` | Passed. Vite reports the main JS chunk at 843.81 kB (252.26 kB gzip), above its 500 kB advisory threshold. |
| 2026-10-11 | Frontend runtime | Checks ran under Node 20.20.2 while `package.json` declares Node >=22.12.0. The checks passed, but release CI should use the declared version. |
| 2026-10-11 | Frontend: `npm run lint` | Passed. |
| 2026-10-11 | Browser smoke, Chrome desktop 1440×1000 and mobile 390×844 | Both rendered the local onboarding screen; capability-authenticated settings, autonomy, and agent badge endpoints returned 200. Models returned 404 as expected because this isolated run had no API key. A direct request without the capability returned 401. Screenshots: [desktop](security-remediation/browser-desktop-2026-10-11.png), [mobile](security-remediation/browser-mobile-2026-10-11.png). |
| 2026-10-11 | Isolated browser backend | Temporary SQLite database and local-only provider URL; project `.env`, live Supabase, and NVIDIA were not used. Test services were stopped after the check. |
| 2026-10-11 | Supabase RLS / schema reload | Prior supplied 118/118 RLS report accepted. No new database connection, table check, `NOTIFY pgrst`, or live trigger test was performed. |

## Remaining work before public or multi-user deployment

1. Rotate the shared Supabase service key and database password when the user
   is ready; this item is intentionally deferred now.
2. Validate the deployed database schema/triggers and repeat the RLS test with
   the deployed project configuration.
3. Use real user authentication and server-derived identity before exposing
   this API beyond a trusted local installation.
4. Use shared rate-limit storage if the backend runs in multiple processes.
5. Exercise the shell inside Docker on a machine with Docker, and review
   minimum OAuth scopes for every configured MCP provider.

The local code/test pass is green, but those deployment boundaries mean this
report does not claim the system is universally secure or ready for public
multi-user hosting.
