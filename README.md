# Pentagon

A ChatGPT-style assistant where you bring your own NVIDIA API key, with grounded answers,
document/web retrieval, image and video understanding, and voice.

> **Supabase, not Convex.** This repository replaces an earlier Convex-backed prototype.
> The backend is FastAPI + LangGraph; the database/auth/storage layer is Supabase
> (see [`supabase/schema.sql`](supabase/schema.sql)). Convex is not used anywhere.

## Layout

| Path | What it is |
|------|-----------|
| `pentagon-backend/` | FastAPI + LangGraph API (chat SSE, RAG, vision, voice, BYOK keys) |
| `pentagon-frontend/` | React + Vite + TypeScript client, packaged with Electron |
| `supabase/schema.sql` | Postgres schema + RLS policies for Supabase |
| `docs/` | [SETUP](docs/SETUP.md), [DECISIONS](docs/DECISIONS.md), [BUILD_LOG](docs/BUILD_LOG.md), [FINAL_REPORT](docs/FINAL_REPORT.md) |

## Run it

```bash
# backend — needs a venv with the deps in requirements.txt
cd pentagon-backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend
cd pentagon-frontend
npm install
npm run dev        # http://127.0.0.1:5173
```

Configuration lives in `pentagon-backend/.env` and `pentagon-frontend/.env`
(copy from the `.env.example` files; both are committed, real `.env` files are not).
Full instructions, including Supabase project setup, are in [docs/SETUP.md](docs/SETUP.md).

## Keys and secrets

Your NVIDIA key is either stored per-user (encrypted at rest with Fernet) or supplied as a
server-side fallback via `NVIDIA_SERVER_API_KEY`. **No key is ever committed** — the repo's
`.gitignore` excludes `.env` files, and the working tree was scanned before publishing.
Supabase's `SUPABASE_SERVICE_ROLE_KEY` is server-only.

## Tests

```bash
cd pentagon-backend && python -m pytest tests -q     # 31 tests
cd pentagon-frontend && npm run check && npm run lint && npm run build
```

## Status and known limits

Verified working: BYOK key storage and validation, chat with streamed answers, model switching
with summarised hand-off, document RAG, web-search RAG, image and video understanding, voice
STT/TTS, conversation history.

Known limits are documented honestly in [docs/FINAL_REPORT.md](docs/FINAL_REPORT.md).
The most important one: reasoning models on NVIDIA NIM (for example `z-ai/glm-5.3-flash`)
can take **2–3 minutes** to produce their first token, so the client shows an elapsed-time
indicator and a Stop button while waiting. Pick a smaller model in the picker for fast replies.