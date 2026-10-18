# Supabase RLS Verification

Status: **PASS — 118/118 live checks** (2026-10-11). Project: `awphghawqhzbjvsfqkcc`.

## Live verification record

The initial service-role API request to `/rest/v1/conversations` returned
`PGRST205`, and its OpenAPI document omitted all 17 expected tables. A direct
Postgres catalog query through the project's Session pooler confirmed **0/17
expected tables in `public`**, with no matching RLS policies or table grants.
The cause was missing schema objects in this project at verification time; a
stale PostgREST cache alone did not explain the failure. The catalog cannot
establish why the earlier manual SQL Editor run did not create them.

Applied `supabase/schema.sql` followed by `supabase/migrations/rag2.sql` in one
database transaction. The catalog then showed 17/17 expected tables, RLS
enabled on all 17, one `own rows` policy on each user-owned table (select-only
for `action_audit`), and no client policies on `user_secrets`,
`mcp_connections`, or `user_settings`. The `anon`, `authenticated`, and
`service_role` database roles had table privileges, so the client denial probes
exercised RLS rather than relying on missing SQL grants. Sent
`NOTIFY pgrst, 'reload schema';`; the service-role API preflight then resolved
all expected table paths.

| Table | Live result |
|---|---|
| `conversations` | PASS — 7/7 owner isolation and ownership checks |
| `messages` | PASS — 7/7 owner isolation and ownership checks |
| `files` | PASS — 7/7 owner isolation and ownership checks |
| `feedback` | PASS — 7/7 owner isolation and ownership checks |
| `action_audit` | PASS — 7/7; owner reads allowed, writes refused as designed |
| `collections` | PASS — 7/7 owner isolation and ownership checks |
| `collection_files` | PASS — 7/7 owner isolation and ownership checks |
| `conversation_collections` | PASS — 7/7 owner isolation and ownership checks |
| `chunks` | PASS — 7/7 owner isolation and ownership checks |
| `kg_entities` | PASS — 7/7 owner isolation and ownership checks |
| `kg_relations` | PASS — 7/7 owner isolation and ownership checks |
| `kg_provenance` | PASS — 7/7 owner isolation and ownership checks |
| `kg_communities` | PASS — 7/7 owner isolation and ownership checks |
| `index_jobs` | PASS — 7/7 owner isolation and ownership checks |
| `user_secrets` | PASS — 6/6 client probes denied |
| `mcp_connections` | PASS — 6/6 client probes denied |
| `user_settings` | PASS — 6/6 client probes denied |

The two service-role write/readback probes passed. Fixtures were removed by the
runner; cleanup reported no errors. Total: **118/118 checks passed**.

No key values or passwords are recorded here. The service-role key supplied
for this run is considered exposed and still needs rotation in the dashboard;
this session has no authenticated dashboard access. The database password was
also supplied for the direct check and should be rotated after use.

## What the schema claims

`supabase/schema.sql` + `supabase/migrations/rag2.sql`:

- `conversations`, `messages`, `files`, `feedback`, `action_audit` (select-only)
  and all rag2 tables (`collections`, `collection_files`,
  `conversation_collections`, `chunks`, `kg_entities`, `kg_relations`,
  `kg_provenance`, `kg_communities`, `index_jobs`) →
  `alter table ... enable row level security` + one `own rows` policy per
  table: `using (auth.uid() = user_id) with check (...)`. Read *your* rows,
  write *your* rows, see nothing of anyone else's.
- `user_secrets`, `mcp_connections`, `user_settings` → **RLS enabled, no
  client policy at all**. Fail-closed: with no policy, the anon key answers
  zero rows for everybody. Only the service-role key (which bypasses RLS) can
  reach them, and that key lives on the backend only, per `.env.example`'s
  warning: "Never expose the service role key to the frontend."

## Diagnostic procedure for future runs

Run this read-only query in the project's Supabase SQL Editor. It checks the
database independently of PostgREST:

```sql
select table_schema, table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
    'user_secrets', 'conversations', 'messages', 'files', 'mcp_connections',
    'user_settings', 'feedback', 'action_audit', 'collections',
    'collection_files', 'conversation_collections', 'chunks', 'kg_entities',
    'kg_relations', 'kg_provenance', 'kg_communities', 'index_jobs'
  )
order by table_name;
```

If the tables exist in `public`, run this in a separate SQL Editor execution to
refresh PostgREST, wait a few seconds, and rerun the verifier:

```sql
notify pgrst, 'reload schema';
```

If the query returns no or only some tables, the SQL was not fully applied to
this project's `public` schema. Apply `supabase/schema.sql` first, then
`supabase/migrations/rag2.sql`, and repeat the query. If the tables exist in a
different schema, confirm that schema is exposed in the project's Data API
settings and is the default schema for the request.

## How to run the live check

1. Create a throwaway project (any free plan works).
2. SQL editor: paste `supabase/schema.sql`, then `supabase/migrations/rag2.sql`.
3. Auth → Users: add two test users (any emails/passwords).
4. From `pentagon-backend/`:

```bash
pip install supabase
SUPABASE_URL=https://<ref>.supabase.co \
SUPABASE_ANON_KEY=<anon> \
SUPABASE_SERVICE_ROLE_KEY=<service> \
SUPABASE_TEST_EMAIL_A=a@test.example \
SUPABASE_TEST_PASSWORD_A=<pw1> \
SUPABASE_TEST_EMAIL_B=b@test.example \
SUPABASE_TEST_PASSWORD_B=<pw2> \
python scripts/verify_supabase_rls.py
```

The verifier first confirms that PostgREST exposes every expected table to the
service role. A missing table is reported as `BLOCKED`, never counted as an RLS
pass. On a clean run it performs 118 checks: owner and foreign-user reads and
writes, plus an ownership-transfer refusal probe for every owner-scoped table;
read/write denial for anon, User A and User B on each backend-only table; and
service-role write/readback.

The script seeds representative fixtures using the service role, does not
create Auth users, and cleans up only rows it created. Existing `user_secrets`
and `user_settings` rows are reused read-only. The `action_audit` policy is
select-only, so an owner write is expected to be denied there; this is encoded
as the expected result rather than mislabeled as a successful owner write.

## What a pass looks like

```
PASS  anon read conversations
PASS  anon write conversations
PASS  user B read A's conversations
PASS  user B write A's conversations
PASS  user A reads own conversations
PASS  user A writes own conversations
PASS  user A cannot transfer A's conversations to user B
...
PASS  user A read backend-only user_secrets        # refuses: owner too
PASS  service role writes conversations
PASS  service role reads its conversation
118/118 checks passed
```

## What a fail looks like

`FAIL  user B read A's messages -- READ RETURNED ROWS: 1 row(s) ...` means
that table's policy is missing or is `using (true)`. Do not ship: fix the
policy and re-run. Every failure names the table and the exact probe that
leaked.

## Verifier corrections

The initial runner was not trustworthy: some write errors were treated as
passes for every actor, it expected column names that did not match the RAG 2
DDL (`name`/`summary` instead of `canonical_name`, `source_id`, `target_id`,
etc.), and its service-role probe reused a conversation primary key. The
current runner uses the live SQL column names, checks that permitted owner
writes return a row, verifies denied foreign updates and owner-to-foreign
ownership transfers leave ownership unchanged, distinguishes RLS refusals
from uniqueness errors, checks the expected select-only/backend-only policies,
and removes its fixtures.

## Found by the offline audit

Checked statically before writing the runner:

- Every table has `user_id uuid not null references auth.users(id)` — no
  table can hold a row without an owner; there is no nullable-owner table to
  hide a leak in.
- `action_audit` is deliberately **select-only** (`create policy ... for
  select`): writes come from the backend with the service role, clients can
  only look at their own audit trail. Refuses inserts by design and the
  runner treats that as a pass.
- `collection_files` and `conversation_collections` are composite-PK join
  tables but still carry `user_id` with the same policy — the join rows are
  owner-scoped independently of either parent table.
- `feedback` has `unique (message_id, user_id)`, so one user cannot stuff
  duplicate reactions; RLS keeps that per-user, not per-conversation.
- No policy on any table grants `for all using (true)` or omits RLS
  enablement; grep confirms `enable row level security` next to every
  `create table` in both files.

## Known gaps

- Storage bucket RLS policies (the `pentagon-files`/`files` buckets in
  Storage, not the `files` table) are configured in the dashboard, not in
  these two SQL files, and so are not covered by this script. If the bucket
  is private with no public policy, it defaults to deny for the anon key;
  verify in Storage → Policies that no `allow public` rule was added.
- Auth email confirmation: if the project requires email confirmation, the
  two test users must be marked confirmed in the dashboard before
  `sign_in_with_password` will work.
