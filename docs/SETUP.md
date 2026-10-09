# Pentagon — Setup

Runs against your own Supabase project and NVIDIA key. Nothing in this repo contains secrets.

## 1. Backend (`pentagon-backend/.env`)

```ini
KEY_ENCRYPTION_SECRET=<fernet-key>            # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
DATABASE_URL=sqlite:///./pentagon.db          # local default; see §3a for Supabase Postgres
DATABASE_SCHEMA=pentagon                      # Postgres only: the schema the backend owns
NVIDIA_SERVER_API_KEY=<server-fallback-key>   # optional; a user's own key in Settings wins
DEFAULT_CHAT_MODEL=z-ai/glm-5.3-flash        # must exist in the live catalog
TAVILY_API_KEY=<optional>                     # web-search fallback when ddgs is rate-limited
SUPABASE_URL=<project url>
SUPABASE_ANON_KEY=<anon key>
SUPABASE_SERVICE_ROLE_KEY=<service role key>
SUPABASE_PROJECT_REF=<project ref>
```

Current status: **WORKING.** A key installed in `pentagon-backend/.env` was verified live on
`z-ai/glm-5.3-flash`: non-streamed HTTP 200 with the correct answer, and a full streamed
reply through the app's own `/api/chat` SSE endpoint. (No key material, not even a
fingerprint of one, is recorded here.)
**Latency is model-side: ~130–175 s before the first output token** (hidden reasoning phase,
identical with `enable_thinking: false`; small `max_tokens` gets fully consumed by thinking —
use the default ≥1024). `nvidia_timeout_seconds` was therefore raised 30 → 300 in
`app/config.py`; with the old 30 s timeout every app request died before any answer. For
snappier replies pick a smaller model in the picker (live catalog).

## 2. Frontend (`pentagon-frontend/.env`)

```ini
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_SUPABASE_URL=<project url>
VITE_SUPABASE_ANON_KEY=<anon or sb_publishable_ key>
```

The Supabase vars are consumed by `src/lib/supabase.ts`, which throws a clear error if they
are missing. The client is exported but not yet bound to app screens (see FINAL_REPORT).

This is where a **publishable** key belongs. It is a browser credential by design: it is
safe to ship in the bundle, it is limited to whatever the project's RLS policies allow, and
it cannot open a database connection. For the backend's own database access see §3a.

## 3. Supabase

A Supabase project is used here in two independent ways, and they need different
credentials. Mixing them up is the easy mistake, so: a **publishable** key
(`sb_publishable_...`) is a browser credential. It grants whatever the project's RLS
policies allow for anonymous callers, and it cannot open a database connection. It is
never the backend's database credential.

### 3a. The backend's database (optional — SQLite is the default)

To keep conversations in Supabase Postgres, put the project's connection string in
`pentagon-backend/.env`:

```ini
DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<db-password>@<host>:5432/postgres
DATABASE_SCHEMA=pentagon
```

Copy it from **Dashboard → Project Settings → Database → Connection string** and prefer the
**Session pooler** variant: the direct `db.<project-ref>.supabase.co` host is IPv6-only for
many projects, and the transaction pooler needs the driver's prepared statements disabled.
The password is the database password, not an API key.

On first run the backend creates its schema (`DATABASE_SCHEMA`, default `pentagon`) and puts
every table it owns there, including the chat checkpoints. It does **not** use `public`: the
tables in `supabase/schema.sql` have uuid keys and foreign keys into `auth.users` that this
local-first app cannot satisfy, and `public` is also the one schema the project's REST API
exposes — so keeping the backend's rows elsewhere means a publishable key cannot read them
at all. §3b is therefore optional; skip it if you only want the database.

To run the backend's own suite against Postgres (it uses a throwaway
`pentagon_test_<random>` schema and drops it afterwards):

```bash
cd pentagon-backend
PENTAGON_TEST_DATABASE_URL='postgresql+psycopg://...' .venv/bin/python -m pytest tests -q
```

### 3b. The client-facing schema (only if the frontend uses Supabase)

Run [`supabase/schema.sql`](../supabase/schema.sql) in the Supabase SQL editor once.
It creates: `user_secrets`, `conversations`, `messages`, `files`, `mcp_connections`,
`user_settings`, `feedback`, `action_audit` — all with RLS enabled, owner-only policies on
conversations/messages/files/feedback/action_audit, and **no client policies** on
`user_secrets`/`mcp_connections`/`user_settings` (service-role only). Add a private
`uploads` Storage bucket in the dashboard.

Get keys from **Supabase Dashboard → Project Settings → API**. The publishable/anon key goes
to `pentagon-frontend/.env` (§2); the service-role key is server-side only and must never
be shipped to a client or committed.

## 4. Run

```bash
# backend
cd pentagon-backend
../pentagon/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend
cd pentagon-frontend
npm run dev      # http://127.0.0.1:5173
```

## 5. Tests, evals, agent route

```bash
# backend unit/integration tests + lint
cd pentagon-backend
../pentagon/bin/python -m pytest tests -q        # 755 passed
../pentagon/bin/python -m pyflakes app/          # clean

# eval suite (mock LLM, no key, no network) — fails on any red case
../pentagon/bin/python -m app.evals.run_evals            # 75/75 (47 YAML tasks + 28 injection)
../pentagon/bin/python -m app.evals.run_evals --filter prompted   # one suite/substring
../pentagon/bin/python -m app.evals.run_evals --live     # only the 3 `live: true` tasks;
                                                         # spends NVIDIA quota, human-run only

# frontend
cd pentagon-frontend && npm run check && npm run lint && npm run build
```

### Agent mode

The composer's **Agent** chip toggles `pentagon.agentMode`, which sends turns to the agent
SSE endpoint instead of `/api/chat`:

- `POST /api/agent/chat` — streamed agent turn (same request shape as `/api/chat`, plus
  `regenerate`); emits `conversation`, `plan`, `status`, `tool_start`, `tool_result`,
  `ask_user`, `approval_required`, `artifact`, `done` (with the verification verdict) and
  `error` events, and pings every 1s while idle.
- `POST /api/agent/decisions` — answer an approval gate; `call_ids: []` means **decline**.
- `POST /api/agent/answers` — answer an `ask_user` question.
- `GET /api/agent/badges` — cached model-capability badges (Strong/Basic/Prompted-only);
  reads the `model_capabilities` table only, never the network.

Approval cards, the plan checklist, the tool timeline, artifacts and the verification badge
render in `pentagon-frontend/src/components/AgentActivity.tsx`.

## 6. RAG collections (R0)

New backend settings (all optional; defaults shown in `.env.example`):

```ini
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2  # default for new collections; a change means reindex
RATE_LIMIT_PER_MINUTE=40        # the shared request budget (NVIDIA free tier ≈ 40/min)
GRAPH_INDEX_RATE_FRACTION=0.5   # the most background indexing may spend of it; chat is always served first
RATE_LIMIT_WAIT_SECONDS=30      # wait for a permit before the API answers 429
JOB_WORKER_ENABLED=true         # background index-job worker (tests turn it off)
```

Collections are managed at `/api/collections` (POST create, GET list/detail,
PATCH rename, DELETE), with `/files` and `/conversations` sub-resources to
assign documents and to scope a conversation's retrieval. Every route takes
`user_id` and answers 404 for somebody else's row.

### Migrating existing uploads

Conversations uploaded before R0 keep their chunks in the old per-conversation
Chroma stores. Move them into collections with:

```bash
cd pentagon-backend
../pentagon/bin/python scripts/migrate_rag2.py --dry-run   # report only; changes nothing
../pentagon/bin/python scripts/migrate_rag2.py             # apply; verifies before deleting
```

The apply verifies both the table counts and the new vector store against the
legacy counts **before** deleting anything, and is safe to re-run after an
interruption. It has been exercised on the test fixtures and as a dry-run
against a real database; the destructive apply on your own `pentagon.db`
yourside is deliberate — back the file up first.

## 7. Skills

Skills are self-contained folders under `pentagon-backend/skills/`:

```
skills/
  public/            # shipped with Pentagon, always available
    document-writing/SKILL.md
    web-research/SKILL.md
    code-generation/SKILL.md
    data-analysis/SKILL.md
    citation-and-sourcing/SKILL.md
  user/              # created via Settings → Skills (gitignored)
    <slug>/SKILL.md
```

Each `SKILL.md` is YAML frontmatter plus a Markdown body:

```markdown
---
name: my-skill
description: One sentence (≤200 chars) — the ONLY part always visible to the model.
triggers: [keyword, another keyword, a phrase a user might say]
risk_category: read | write | destructive | external_send
requires_tools: [web_search, shell_exec]
---

Full instructions body…
```

Runtime behavior: the loader parses frontmatter only into an in-memory
index and re-checks file stamps on access, so a new or edited file is live
on your **next message** — no backend restart. The `skill_router` node
(after `intent_router`) scores the turn's text against `description` +
`triggers`, takes the best matches up to 3, and injects only those bodies
into the context **for that turn** — never into stored thread history.
Disabled skills are excluded from matching entirely.

Manage skills at **Settings → Skills**: toggle skills on/off, or use the
Add-skill form (writes `skills/user/<slug>/SKILL.md` with correct
frontmatter). Validation: description ≤200 chars, ≥1 trigger,
`risk_category` must be a permission tier (`read`, `write`, `destructive`,
`external_send`).

API: `GET /api/skills?user_id=`, `POST /api/skills`,
`PATCH /api/skills/{id}` (toggle), `DELETE /api/skills/{id}`
(user skills only — public skills answer 409).

Tuning: every turn logs `skills fired: [...]` on logger `app.skills.router`
(empty list = no match). Watch it to adjust triggers or the score threshold
(`SCORE_THRESHOLD`, `MAX_SKILLS_PER_TURN` in `app/skills/loader.py`).
