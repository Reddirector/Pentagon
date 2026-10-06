# Pentagon — Build Log

- phase 0/6 built on existing repo quality gates: backend pytest (27→31), frontend tsc/oxlint/build, live-catalog verification against NVIDIA
- Supabase integrated: schema.sql with full RLS matrix + feedback table; client module exists in frontend; backend settings carry service-role ref fields; server-side NC key fallback wired through chat/models/documents/voice routes with tests
- key status: models endpoint 200/80 models with the supplied key, but `/models` is public without a key and inference returns the same 403 as a garbage key → key invalid for inference (BYOK storage unaffected); reported in SETUP.md
- assumptions: docs live at repo-root `docs/` (master prompt layout) rather than inside either subpackage; schema is delivered as SQL per prompt (schema is correct as written)
- user supplied a second NVIDIA key: verified live (HTTP 200, correct answer; full SSE reply through /api/chat). Root cause of the earlier "no answer": model-side TTFB of ~130-175 s vs the backend's 30 s NVIDIA timeout — raised to 300 s (tests green, 31/31); first key remains unauthorized for inference
- hardening pass: settings rebuilt as a tabbed surface (account / appearance / model / data / about) with a preference store applied before first paint
- fixed a latent cascade bug: an unlayered `button { font: inherit }` rule was outranking every Tailwind font-size utility, so button text silently ignored its size class; moved to `@layer base`
- replaced 107 literal `text-[Npx]` values with scale tokens and made density ride on Tailwind's `--spacing` base, so text-size and density settings genuinely work
- conversation rename + delete: `PATCH /api/conversations/{id}/title` and `DELETE /api/conversations/{id}`, cascading messages and documents; surfaced in the sidebar (hover actions, inline edit) and the Data tab
- responsive pass: sidebar became a drawer below md (it was `max-md:hidden` and unreachable), verified with no horizontal overflow at 320px and 390px
- RAG fix: retrieval had no fallback when the pinned NVIDIA embedding model became unusable, so changing the key broke document search entirely; now migrates the collection to local embeddings once and stays independent of the API. 7 new tests, 5 of which fail against the previous implementation
- test isolation: `tests/conftest.py` points the suite at a temporary database; a full run now leaves the real `pentagon.db` byte-identical
- corrected `.env.example`, which named `IMAGE_UPLOADS_DIRECTORY` while the config field is `image_upload_directory` — the variable was silently ignored
- added MIT LICENSE and rewrote the README; refreshed the docs to current test counts and limitations
- tools T0 scaffolding: `pentagon-backend/app/agent/` (schemas: ToolSpec/ToolContext/result envelope/Budget/AgentEvent; registry with registration validation + OpenAI-schema export; TraceRecorder with secret-redaction), `app/tools/`, `app/evals/` (deterministic mock LLM whose astream fragments content and tool_call_chunks per-index like the real OpenAI-compatible stream, plus a YAML task loader/runner skeleton), and a `tool_traces` table (SQLAlchemy, SQLite base per DECISIONS #1)
- tools T0 gate: 34 new tests (registry validation/dup/unknown-name listing, envelope shapes + truncation flag, budget caps, redaction, trace persistence, mock stream reassembly) — 470 passed exit 0, pyflakes clean; committed
- tools baseline: pending permission-feature + audit-fix work committed first as its own commit (488ad21) so phase commits stay clean
