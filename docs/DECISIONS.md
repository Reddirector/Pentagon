# Pentagon — Decisions

| # | Decision | Reason |
|---|----------|--------|
| 1 | Keep the existing local-first SQLite BYOK app as the base; build the Supabase path beside it rather than a risky tables rewrite | The repo already implements chat/history/RAG/vision/voice/video with 27 passing tests; a wholesale migration mid-run would risk everything for parity |
| 2 | `NVIDIA_SERVER_API_KEY` / `DEFAULT_CHAT_MODEL` as new optional backend settings; resolver precedence stored-key → server-key → error | User explicitly asked to "use this model and api key"; BYOK stays the front door, server key makes the app run before any key is stored |
| 3 | Default model surfaced by `GET /api/models.default_model`; frontend prefers it over chunk index 0 | Master prompt §7.3 forbids hardcoding model names from memory; default is now live-catalog-derived |
| 4 | Frontend key-gate heuristic: boot to gate only on 404 when a configured default model exists and no thread exists | 404 on `/api/conversations/{id}` legitimately occurs for a fresh local user with a server key configured |
| 5 | Master prompt's `/api/chat/{id}/stream` and JWT auth not implemented this run | Existing contract is `POST /api/chat` with user_id; SSE chat-mount and per-route Supabase-JWT auth are the honest next slice on the Supabase path |
| 6 | No phase commits published | Worktree root (`Desktop/Pentagon`) has no `.git`; files are left uncommitted for git-aware review |
| 7 | Conversation creation auto-provisions the local user row when the server key fallback is configured | Live preview showed `create_conversation` still 404ing for fallback-key users; chat must start before any personal key is stored |

---

## Embeddings: migrate the collection, never mix spaces

**Context.** A Chroma collection can only ever hold one embedding space. The
app embeds documents with whatever NVIDIA embedding model the user's current key
serves, and pins that provider into the collection metadata. Retrieval must then
encode the query the same way.

**Options considered.**

1. *Re-embed on every query* — always uses the best available model. Rejected:
   far too slow, and still fails when no API is available.
2. *Always use the local model* — no API dependency at all. Rejected for the
   default path: `nemotron-3-embed-1b` retrieves better than MiniLM, and a
   machine with no network cannot download it on first use.
3. *Pin, and migrate on failure* — chosen.

**Decision.** Keep pinning per collection, but when the pinned provider becomes
unusable (key replaced or revoked, model withdrawn), re-encode that collection
once with the local model and answer from it thereafter. Embeddings are computed
*before* the store is touched, so a failed migration leaves the original intact.
Chunk ids, text and metadata are preserved so citations keep resolving.

The consequence worth stating plainly: once a collection migrates it stays local
even if the API returns. That is a deliberate trade — retrieval that never breaks
is worth more than the last increment of retrieval quality, and the migration is
reversible by re-uploading if a user prefers.

## One UI, packaged once

There was a second Electron package at `pentagon-backend/desktop/` with its own
`src/`, its own React dependencies and its own Vite build. It had already fallen
behind the web frontend: its `App.tsx` was 547 lines against the frontend's 929,
and its `index.css` was 10 lines against 291. Any fix made to the interface had
to be made twice, and nothing stopped the two from drifting apart again.

It was originally left in place because electron-builder packaging could not be
verified in this environment (Node 20 here; the package declares 22.12+), and an
unverified packaging change is worse than documented duplication. That reason
turned out to be wrong on both counts:

- The assumption was backwards. `pentagon-frontend/` already *was* a complete
  Electron application — same `electron/main.cjs`, same `electron/uiServer.cjs`,
  same electron-builder `appId` — and had already produced a working AppImage.
  There was never a need to repoint anything; the duplicate was simply a fork
  that had been left behind.
- Packaging does run here. `npm run package:linux` in `pentagon-frontend`
  completes on Node 20 and produces `release/Pentagon-0.1.0.AppImage`.

So the directory was deleted rather than synchronised. The two files that had
no counterpart in the frontend were checked first: `src/App.css` was imported
by nothing, and `public/favicon.svg` was a leftover the frontend had already
replaced with `pentagon-logo.png`. Nothing was lost but the duplication.

`npm run electron:dev` and the four `npm run package:*` scripts are unchanged,
and now build the same interface the browser serves.

## Every record route is scoped by owner

`GET`, `PATCH` and `DELETE` on `/api/conversations/{id}` originally looked the
row up by primary key alone, while `GET /api/conversations` and
`DELETE /api/documents/{id}` filtered on `user_id`. Anyone who knew a thread's
UUID could therefore read it, rename it, switch its model, or delete it with no
`user_id` at all. The inconsistency was accidental: `remove_document` shows the
intended shape, and the conversation routes simply missed the filter.

All four now take a required `user_id` and filter on it. They answer `404`
rather than `403` for someone else's thread, because a `403` confirms the id
exists.

This is **not** authentication. `user_id` is client-supplied, so it is a
scoping key rather than a credential: it stops a stale id in one client from
touching another user's rows, but a caller who can reach the API can pass any
`user_id` they like. Real isolation needs sessions or signed tokens, which is
why the app is documented as local-first. See the README.

## Tests run against a throwaway database

`tests/conftest.py` points `DATABASE_URL` at a temporary file before the engine
is constructed, because the engine is built from settings at import time. The
suite previously wrote into the real `pentagon.db`, so test rows — and rows
deleted by tests — landed in the user's actual data.
