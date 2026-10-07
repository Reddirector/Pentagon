-- Pentagon — RAG 2 schema (Advanced RAG upgrade §4)
-- Apply after supabase/schema.sql in the Supabase SQL editor or via
-- `supabase db push`. Every table is owner-only: RLS enabled with an
-- `auth.uid() = user_id` policy, exactly like the base schema's own rows.
--
-- The local-first SQLite build implements the same contract by scoping every
-- query on `user_id` (DECISIONS #8); this file is the schema spec.

create table collections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  description text,
  embedding_model text not null,                 -- id + version, see Section 6
  graph_enabled boolean not null default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table collection_files (
  collection_id uuid not null references collections(id) on delete cascade,
  file_id uuid not null references files(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  primary key (collection_id, file_id)
);

create table conversation_collections (
  conversation_id uuid not null references conversations(id) on delete cascade,
  collection_id uuid not null references collections(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  primary key (conversation_id, collection_id)
);

create table chunks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  collection_id uuid not null references collections(id) on delete cascade,
  file_id uuid not null references files(id) on delete cascade,
  ord int not null,
  page int,
  section text,
  text text not null,
  lang text,                    -- BCP-47 or "hi-Latn" for romanized Hindi
  script text,                  -- Latn, Deva, Arab, Hans, ...
  token_count int,
  created_at timestamptz default now()
);
create index on chunks (collection_id, file_id, ord);

create table kg_entities (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  collection_id uuid not null references collections(id) on delete cascade,
  canonical_name text not null,
  names jsonb not null default '{}',             -- {"en": "India", "hi": "भारत"}
  aliases jsonb not null default '[]',
  type text not null default 'Other',
  description text,
  mention_count int not null default 1,
  created_at timestamptz default now()
);
create index on kg_entities (collection_id, canonical_name);

create table kg_relations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  collection_id uuid not null references collections(id) on delete cascade,
  source_id uuid not null references kg_entities(id) on delete cascade,
  target_id uuid not null references kg_entities(id) on delete cascade,
  type text not null,
  description text,
  weight real not null default 1,
  confidence real,
  created_at timestamptz default now()
);
create index on kg_relations (collection_id, source_id);
create index on kg_relations (collection_id, target_id);

create table kg_provenance (                      -- which chunks support which entity/relation
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  collection_id uuid not null references collections(id) on delete cascade,
  entity_id uuid references kg_entities(id) on delete cascade,
  relation_id uuid references kg_relations(id) on delete cascade,
  chunk_id uuid not null references chunks(id) on delete cascade,
  check ((entity_id is not null) <> (relation_id is not null))
);

create table kg_communities (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  collection_id uuid not null references collections(id) on delete cascade,
  level int not null default 0,
  parent_id uuid references kg_communities(id) on delete set null,
  entity_ids uuid[] not null,
  title text,
  summary text,
  summary_lang text,
  stale boolean not null default true,
  created_at timestamptz default now()
);

create table index_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  collection_id uuid not null references collections(id) on delete cascade,
  kind text not null,                             -- ingest | embed | graph_extract | graph_resolve | communities | summarize | reindex
  status text not null default 'queued',          -- queued | running | paused | done | failed | cancelled
  progress real not null default 0,
  llm_calls_estimated int,
  llm_calls_used int not null default 0,
  llm_calls_cap int,
  error text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

alter table collections enable row level security;
alter table collection_files enable row level security;
alter table conversation_collections enable row level security;
alter table chunks enable row level security;
alter table kg_entities enable row level security;
alter table kg_relations enable row level security;
alter table kg_provenance enable row level security;
alter table kg_communities enable row level security;
alter table index_jobs enable row level security;

-- Owner-only, same pattern as the base schema's "own rows" policies.
create policy "own rows" on collections for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on collection_files for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on conversation_collections for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on chunks for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on kg_entities for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on kg_relations for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on kg_provenance for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on kg_communities for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on index_jobs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
