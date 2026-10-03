-- Pentagon — Supabase schema (master prompt §4)
-- Apply in the Supabase SQL editor or via `supabase db push`.
-- Backend uses the service-role key (server only); frontend uses the anon key and relies on RLS.

create table user_secrets (
  user_id uuid primary key references auth.users(id) on delete cascade,
  nvidia_key_enc text,
  nvidia_key_last4 text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New chat',
  model text not null,
  careful_mode boolean not null default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user','assistant','system','tool')),
  content text not null,
  sources jsonb,
  attachments jsonb,
  created_at timestamptz default now()
);

create table files (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  storage_path text not null,
  filename text not null,
  kind text not null default 'document',        -- document | image | video | audio
  status text not null default 'processing',    -- processing | ready | failed
  created_at timestamptz default now()
);

create table mcp_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  server text not null,                         -- github | gcal | gmail | filesystem
  credentials_enc text,
  config jsonb default '{}',
  enabled boolean default true,
  created_at timestamptz default now(),
  unique (user_id, server)
);

create table user_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  shell_enabled boolean not null default false,
  always_allow jsonb not null default '[]',     -- read-only tool names the user always allows
  created_at timestamptz default now()
);

create table feedback (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null references messages(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  value text not null check (value in ('up','down')),
  created_at timestamptz default now(),
  unique (message_id, user_id)
);

create table action_audit (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  conversation_id uuid references conversations(id) on delete set null,
  tool text not null,
  args jsonb,
  decision text not null check (decision in ('approved','denied','auto')),
  result_summary text,
  created_at timestamptz default now()
);

alter table user_secrets enable row level security;
alter table conversations enable row level security;
alter table messages enable row level security;
alter table files enable row level security;
alter table mcp_connections enable row level security;
alter table user_settings enable row level security;
alter table feedback enable row level security;
alter table action_audit enable row level security;

create policy "own rows" on conversations for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on messages for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on files for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on feedback for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rows" on action_audit for select using (auth.uid() = user_id);
-- user_secrets, mcp_connections, user_settings: NO client policies. Backend (service role) only.
