# Pentagon — Setup

Runs against your own Supabase project and NVIDIA key. Nothing in this repo contains secrets.

## 1. Backend (`pentagon-backend/.env`)

```ini
KEY_ENCRYPTION_SECRET=<fernet-key>            # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
DATABASE_URL=sqlite:///./pentagon.db          # local default; see §3 for Supabase Postgres
NVIDIA_SERVER_API_KEY=<server-fallback-key>   # working key installed locally (last4 ...90kx)
DEFAULT_CHAT_MODEL=z-ai/glm-5.3-flash        # must exist in the live catalog
TAVILY_API_KEY=<optional>                     # web-search fallback when ddgs is rate-limited
SUPABASE_URL=<project url>
SUPABASE_ANON_KEY=<anon key>
SUPABASE_SERVICE_ROLE_KEY=<service role key>
SUPABASE_PROJECT_REF=<project ref>
```

Current status: **WORKING.** The key installed in `pentagon-backend/.env` (len 70, last4
`...90kx`) was verified live on `z-ai/glm-5.3-flash`: non-streamed HTTP 200 with the correct
answer, and a full streamed reply through the app's own `/api/chat` SSE endpoint.
**Latency is model-side: ~130–175 s before the first output token** (hidden reasoning phase,
identical with `enable_thinking: false`; small `max_tokens` gets fully consumed by thinking —
use the default ≥1024). `nvidia_timeout_seconds` was therefore raised 30 → 300 in
`app/config.py`; with the old 30 s timeout every app request died before any answer. For
snappier replies pick a smaller model in the picker (live catalog).

## 2. Frontend (`pentagon-frontend/.env`)

```ini
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_SUPABASE_URL=<project url>
VITE_SUPABASE_ANON_KEY=<anon key>
```

The Supabase vars are consumed by `src/lib/supabase.ts`, which throws a clear error if they
are missing. The client is exported but not yet bound to app screens (see FINAL_REPORT).

## 3. Supabase schema

Run [`supabase/schema.sql`](../supabase/schema.sql) in the Supabase SQL editor once.
It creates: `user_secrets`, `conversations`, `messages`, `files`, `mcp_connections`,
`user_settings`, `feedback`, `action_audit` — all with RLS enabled, owner-only policies on
conversations/messages/files/feedback/action_audit, and **no client policies** on
`user_secrets`/`mcp_connections`/`user_settings` (service-role only). Add a private
`uploads` Storage bucket in the dashboard.

Get keys from **Supabase Dashboard → Project Settings → API**.

## 4. Run

```bash
# backend
cd pentagon-backend
../pentagon/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend
cd pentagon-frontend
npm run dev      # http://127.0.0.1:5173
```

## 5. Tests

```bash
cd pentagon-backend && ../pentagon/bin/python -m pytest tests -q   # 31 passed
cd pentagon-frontend && npm run check && npm run lint && npm run build
```
