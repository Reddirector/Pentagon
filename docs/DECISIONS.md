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
