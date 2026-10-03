# Pentagon — Build Log

- phase 0/6 built on existing repo quality gates: backend pytest (27→31), frontend tsc/oxlint/build, live-catalog verification against NVIDIA
- Supabase integrated: schema.sql with full RLS matrix + feedback table; client module exists in frontend; backend settings carry service-role ref fields; server-side NC key fallback wired through chat/models/documents/voice routes with tests
- key status: models endpoint 200/80 models with the supplied key, but `/models` is public without a key and inference returns the same 403 as a garbage key → key invalid for inference (BYOK storage unaffected); reported in SETUP.md
- assumptions: docs live at repo-root `docs/` (master prompt layout) rather than inside either subpackage; schema is delivered as SQL per prompt (schema is correct as written)
- user supplied a second NVIDIA key: verified live (HTTP 200, correct answer; full SSE reply through /api/chat). Root cause of the earlier "no answer": model-side TTFB of ~130-175 s vs the backend's 30 s NVIDIA timeout — raised to 300 s (tests green, 31/31); first key remains unauthorized for inference
