# Pentagon

A personal AI workspace. Bring your own NVIDIA API key, talk to any model on
NVIDIA NIM, and ground the answers in your own documents, the live web, images,
video and voice.

Everything runs on your machine: keys are encrypted at rest, documents are
chunked and embedded locally or against your own key, and nothing is sent to a
hosted service you did not choose.

> This repository replaces an earlier Convex-backed prototype, preserved on the
> `convex-prototype` tag. The backend is FastAPI + LangGraph; Convex is not used
> anywhere. Supabase remains optional.

---

## Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [How retrieval survives API changes](#how-retrieval-survives-api-changes)
- [HTTP API](#http-api)
- [Testing](#testing)
- [Desktop app](#desktop-app)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)
- [License](#license)

---

## What it does

| Capability | Notes |
|---|---|
| **Chat** | Server-sent events, streamed token by token, with stop control |
| **80+ models** | Anything in the live NVIDIA catalog, switched per thread |
| **Model switching** | Mid-conversation switch summarises prior turns so context survives |
| **Document RAG** | PDF, DOCX and plain text; answers cite the source chunks |
| **Web search** | Runs keyless via DuckDuckGo; Tavily is an optional fallback. Pages are fetched and read, not just snippets |
| **Images** | Vision-capable models, described and reasoned over |
| **Video** | Sampled frames sent to a vision model with the chosen sampling rate |
| **Voice** | Speech-to-text and text-to-speech, with local fallbacks |
| **Bring your own key** | Stored per user, Fernet-encrypted, validated before saving |
| **Appearance** | Monochrome themes, contrast, text size, density, ambient background |
| **Offline-friendly retrieval** | Embeddings fall back to a local model, so RAG survives key changes |

---

## Quick start

Requires **Python 3.10+** (developed on 3.14) and **Node 22.12+** — both the
frontend and the desktop package declare that engine floor. Builds do succeed
on Node 20, which is below the declared minimum.

```bash
# 1. Backend
cd pentagon-backend
python -m venv ../pentagon
source ../pentagon/bin/activate          # Windows: ..\pentagon\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste that into KEY_ENCRYPTION_SECRET in .env, then:
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Frontend (second terminal)
cd pentagon-frontend
npm install
cp .env.example .env                    # optional; the default points at :8000
npm run dev                             # http://127.0.0.1:5173
```

Open <http://127.0.0.1:5173>. If you left `NVIDIA_SERVER_API_KEY` empty, the app
asks for your own key on first run and stores it encrypted.

---

## Configuration

### Backend — `pentagon-backend/.env`

Every field is documented in [`.env.example`](pentagon-backend/.env.example).
The two that matter most:

| Variable | Why |
|---|---|
| `KEY_ENCRYPTION_SECRET` | Fernet key protecting stored API keys. **Changing it makes existing keys unreadable.** |
| `NVIDIA_SERVER_API_KEY` | Optional fallback so the app works before any user stores a key. Never sent to the client. |

Also worth knowing: `NVIDIA_TIMEOUT_SECONDS` defaults to `300`, because
reasoning models can take two to three minutes to produce a first token and a
30-second timeout kills every request.

### Frontend — `pentagon-frontend/.env`

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Backend origin. Defaults to the Vite dev proxy. |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | Optional. Only needed for cloud sign-in. |

The Supabase **service role key must never** be placed in the frontend. It
bypasses Row Level Security.

---

## Architecture

```
pentagon-frontend/          React 19 + Vite + TypeScript
  src/lib/preferences.ts    Theme, density and text-size store (applied pre-paint)
  src/lib/ambient.ts        Ambient background state machine
  src/components/           Sidebar, Settings, CommandPalette, AmbientLayer…

pentagon-backend/           FastAPI + LangGraph
  app/routes/chat.py        SSE chat, conversations, rename, delete
  app/routes/documents.py   Upload, list, delete
  app/routes/keys.py        Validate and store NVIDIA keys
  app/routes/voice.py       Speech-to-text and text-to-speech
  app/services/
    chat_graph.py           The LangGraph pipeline
    document_store.py       ChromaDB, chunk storage, retrieval, migration
    embeddings.py           Remote and local embedding providers
    web_search.py           Keyless search with an SSRF guard

supabase/schema.sql         Optional Postgres schema with RLS
docs/                       Setup, decisions, build log, final report
```

**Request flow.** The browser posts to `/api/chat` and reads an SSE stream.
`chat_graph` decides whether the question needs retrieval — a recent-price or
"who is the CEO" question triggers web search; "summarise this" does not —
then merges document chunks, web results, and conversation history into the
prompt and streams the answer back.

---

## How retrieval survives API changes

This is the part worth knowing about, because it is easy to get wrong.

Documents are embedded at upload time with whichever NVIDIA embedding model
your current key serves, and that choice is **pinned to the collection**. The
same model must encode the query, because embedding spaces from two different
models are not comparable — different meaning *and* different dimensions.

That means the obvious implementation breaks the moment the key changes: the
query can no longer be encoded in the space the chunks live in, and retrieval
fails outright. Pentagon handles this by **migrating rather than failing**:

- If the pinned provider stops working — key replaced, revoked, or the model
  withdrawn — the collection is re-encoded once with the local model
  (`all-MiniLM-L6-v2`, which needs no API) and answers from there. The
  collection is then permanently independent of the API.
- Uploading into an existing collection never mixes embedding spaces; it
  migrates the existing chunks first.
- Chunk ids, text and metadata survive migration, so citations keep working.

Cost: the first migration re-encodes the collection on CPU, which is slow for a
large corpus, and local embeddings are somewhat weaker than
`nemotron-3-embed-1b`. Everything after that is free.

Covered by [`tests/test_document_store_resilience.py`](pentagon-backend/tests/test_document_store_resilience.py).

---

## HTTP API

All routes are prefixed `/api`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/chat` | Streamed chat (SSE). Form or JSON. |
| `GET` | `/api/conversations` | List threads for a user |
| `POST` | `/api/conversations` | Create a thread |
| `GET` | `/api/conversations/{id}` | Full thread with messages |
| `PATCH` | `/api/conversations/{id}` | Switch model, summarising prior turns |
| `PATCH` | `/api/conversations/{id}/title` | Rename a thread |
| `DELETE` | `/api/conversations/{id}` | Delete a thread, its messages and documents |
| `GET` | `/api/models` | Model catalogue and the server default |
| `POST` | `/api/keys` | Validate and store an API key (encrypted) |
| `POST` | `/api/keys/validate` | Check a key without storing it |
| `POST` | `/api/documents/upload` | Upload a document |
| `GET` | `/api/documents` | List documents for a thread |
| `DELETE` | `/api/documents/{id}` | Delete a document and its chunks |
| `POST` | `/api/voice/transcribe` | Speech to text |
| `POST` | `/api/voice/synthesize` | Text to speech |

---

## Testing

```bash
# Backend — 52 tests
cd pentagon-backend
python -m pytest -q

# Frontend
cd pentagon-frontend
npm run check      # tsc
npm run lint       # oxlint
npm run build      # production build
```

The backend suite runs against a **throwaway SQLite database** created in a
temporary directory (`tests/conftest.py`), so running tests never touches your
real `pentagon.db`.

---

## Desktop app

`pentagon-backend/desktop/` packages the app with Electron:

```bash
cd pentagon-backend/desktop
npm install
npm run electron:dev      # window against the dev server
npm run package:linux     # or :mac / :win
```

Requires **Node 22.12+**, matching the frontend's declared engine. See
[`docs/DECISIONS.md`](docs/DECISIONS.md) for how this copy relates to the web
frontend — and why the two have not been merged yet.

---

## Troubleshooting

**"no answer" / request times out.** Reasoning models take 2–3 minutes for a
first token. `NVIDIA_TIMEOUT_SECONDS` defaults to `300`; raising it further may
help on very large models.

**NVIDIA returns 403.** The key is valid but not authorised for that endpoint.
Keys differ in what they can reach — check the key against the model in
Settings → Account.

**Retrieval returns nothing.** Confirm the document attached to *this* thread;
document context is per-thread, not global. If the embedding provider changed,
the collection re-embeds itself locally on the next query.

**Upload rejected with "Upload a PDF, DOCX, or plain text file."** Those three
extensions are the only ones accepted (`.pdf`, `.docx`, `.txt`). Markdown is
deliberately not — rename the file to `.txt`.

**Frontend cannot reach the backend.** The dev server proxies `/api` to
`127.0.0.1:8000`. Confirm the backend is running and check
`VITE_API_BASE_URL`.

**Stored keys unreadable after a restart.** `KEY_ENCRYPTION_SECRET` changed.
Restore the original value or re-enter the key.

**Port already in use.** `python -m uvicorn app.main:app --port 8001`, then set
`VITE_API_BASE_URL=http://127.0.0.1:8001`.

---

## Documentation

| Document | Contents |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | Environment setup in detail |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture decisions and their trade-offs |
| [docs/BUILD_LOG.md](docs/BUILD_LOG.md) | Chronological record of what changed and why |
| [docs/FINAL_REPORT.md](docs/FINAL_REPORT.md) | Verification status and known limitations |

---

## License

[MIT](LICENSE) © 2026 Reddirector.
