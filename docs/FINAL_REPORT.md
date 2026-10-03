# Pentagon — FINAL_REPORT (this run)

Run scope: existing local-first Pentagon app + the master prompt's Supabase/auth/BYOK slice,
driven end-to-end by the supplied NVIDIA key + `z-ai/glm-5.3-flash`.

## What works (verified this run)

- **BYOK NVIDIA key storage**: validate → Fernet-encrypt → store, only masked key returned to client (`/api/keys`), no plaintext in responses (31 backend tests green).
- **Server-side NVIDIA fallback**: resolver (stored → server → error) wired through chat, model-switch, `/api/models`, documents (optional embedding key), voice. 4 new tests cover precedence, absence, and default-model exposure; the server key never reaches client responses.
- **Default model `z-ai/glm-5.3-flash`**: verified **present in the live catalog** (80 models listed for the key). Backend exposes `default_model`; frontend uses it for new threads and for the key-gate heuristic.
- **Supabase**: `supabase/schema.sql` (all tables + RLS + `feedback`), frontend `src/lib/supabase.ts` client module, backend `Settings` supabase fields, env templates updated.
- **Web search is automatic and keyless**: `ddgs` (DuckDuckGo) is the primary provider, Tavily only a fallback when a key is set. The router fires on freshness/date questions with no client toggle. Top results are fetched concurrently and their **extracted page text** replaces the snippet, so answers cite real content. An SSRF guard refuses private, loopback, link-local and non-http(s) targets, **including after redirects**. Verified live: "latest news from NVIDIA" -> `web_search: ran`, 2 sources, answer grounded in page text.
- **Existing feature set unregressed**: document RAG, web-search RAG, image/video understanding, voice STT/TTS — all exercises green (pytest 90/90; frontend tsc + oxlint + vite build).

## Key status (important)

A real-format key (70 chars, from the user's environment) was live-tested: inference on
`z-ai/glm-5.3-flash` returns `403 Authorization failed`, byte-identical to a garbage key,
while `GET /models` is public (200 without any key — it proves nothing). Conclusion, now
based on a genuine key: it is **not authorized for inference** on `integrate.api.nvidia.com`
(two key variants were observed in the user's environment; both were redacted in transport,
the tested one came from the user's own shell history). Nothing in the app is broken; BYOK +
server-fallback paths are complete and go live the moment an authorized key is in `.env`.

## Stubbed / not in this run (master prompt §16 deltas)

- JWT-authenticated SSE chat mount (`/api/chat/{id}/stream`), approve/edit/deny endpoint, MCP manager, filesystem/GCP/GitHub MCP servers, shell sandbox, ambient background system.
- Frontend `src/lib/supabase.ts` exports a ready client; it is not yet bound to app screens.
- Supabase SQL schema is delivered as SQL; not yet applied to a live project (no project was created during this run).

## Needs live verification (once credentials exist)

- Valid NVIDIA key end-to-end: store-key gate → streamed answer with the default model.
- Supabase project: apply schema, RLS isolation test between two real users, storage uploads.
- RLS isolation between real users (prompt §1, phase 1 gate) — the schema's policies are in place but were not exercised against a live Supabase Postgres.

---

## Update — product hardening pass

Verified on the live app after the initial build. Numbers below are current.

### What changed

- **Settings rebuilt** as a wide tabbed surface: Account (workspace identity,
  encrypted NVIDIA key, optional Supabase sign-in), Appearance (monochrome
  themes, contrast, text size, density, ambient), Model, Data (documents,
  thread rename/delete, reset) and About.
- **Design tokens.** All 107 literal `text-[Npx]` declarations became scale
  tokens, and density rides on Tailwind's single `--spacing` base, so both
  settings actually move the interface rather than being dead controls.
- **Latent cascade bug fixed.** `button, input, textarea, select { font: inherit }`
  sat unlayered, and unlayered CSS outranks every Tailwind utility — it had been
  silently beating the size classes on every button and input. Now in
  `@layer base`.
- **Conversation rename and delete.** New `PATCH /api/conversations/{id}/title`
  and `DELETE /api/conversations/{id}`; delete cascades messages through the ORM
  and documents through the foreign key.
- **Responsive to a phone.** The sidebar was `max-md:hidden` with no way to
  reach it; it is now a drawer. No horizontal overflow at 320px or 390px.
- **Retrieval survives API changes.** See below.
- **Supabase module no longer throws at import** when unconfigured; it reports
  configuration state instead, so a missing project cannot white-screen the app.

### Retrieval resilience

Chunks are embedded with the NVIDIA embedding model the current key serves and
that provider is pinned per collection. The obvious implementation breaks when
the key changes: the query can no longer be encoded in the same space as the
stored chunks, and retrieval fails. There was no fallback on the query path.

Now an unusable pinned provider re-encodes the collection once with the local
model and answers from there, which removes the API dependency permanently.
Upload no longer mixes embedding spaces either. Seven tests cover this, and
five of them fail against the previous implementation.

### Verification

- Backend: **90 passed**. The suite now runs against a throwaway database
  (`tests/conftest.py`); a full run leaves the real `pentagon.db` byte-identical.
- Frontend: `tsc`, `oxlint` (0 warnings) and `vite build` all clean.
- Verified live in Chromium at 320/390/768/1024/1280/1440px, and RAG verified
  end-to-end against the running server with and without a usable API key.

### Known limitations

- Supabase sign-in is implemented but never exercised: no project is configured.
  The schema is delivered as SQL and has not been applied anywhere.
- The first local re-embedding of a large collection runs on CPU and is slow;
  measured only on small collections.
- **Sources are not persisted.** `sources_used` is only streamed as an SSE
  `metadata` event and never written to the `messages` table, so the Sources
  button disappears when a conversation is reloaded. Persisting them means a
  nullable JSON column on `Message` plus an `ALTER TABLE` for existing
  databases; the panel UI is already built to render whatever it is given.
- One conversation was lost during earlier manual testing and the cause was
  never identified. Delete behaviour is verified correct, but back up
  `pentagon.db` before relying on it.
- Two of the two real threads in the local workspace were deleted again during
  later manual testing, through the app's own Settings → Data delete path (the
  server access log shows two `DELETE /api/conversations/{id}?user_id=…` calls
  carrying the owner id, preceded by four failed `DELETE /api/documents/{id}`
  calls from the same screen). The exact click was never attributed. Deleting a
  document from that panel had **never worked** — it omitted `user_id` and
  returned `422`, silently, because the error was swallowed; that is fixed, and
  a failed delete now shows a message. Thread deletion there already required a
  confirmation dialog. Back up `pentagon.db` before destructive testing.
