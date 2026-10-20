-- ==============================================================================
-- Pentagon — Supabase Enterprise Security Schema
-- Apply in the Supabase SQL editor or via `supabase db push`.
-- Backend uses the service-role key (server only); frontend uses the anon/auth key.
-- Defense-in-depth: RLS, FORCE RLS, BOLA protection, least privilege grants,
-- audit immutability, and storage isolation.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. TABLES & CONSTRAINTS
-- ------------------------------------------------------------------------------

create table user_secrets (
  user_id uuid primary key references auth.users(id) on delete cascade,
  nvidia_key_enc text,
  nvidia_key_last4 text check (nvidia_key_last4 is null or char_length(nvidia_key_last4) <= 8),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null default 'New chat' check (char_length(trim(title)) between 1 and 255),
  model text not null check (char_length(trim(model)) between 1 and 128),
  careful_mode boolean not null default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('user','assistant','system','tool')),
  content text not null check (octet_length(content) <= 1048576), -- 1 MB max text cap
  sources jsonb,
  attachments jsonb,
  created_at timestamptz default now()
);

create table files (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  storage_path text not null check (char_length(trim(storage_path)) between 1 and 1024 and storage_path !~ '\.\.'),
  filename text not null check (char_length(trim(filename)) between 1 and 512 and filename !~ '[/\\]'),
  kind text not null default 'document' check (kind in ('document', 'image', 'audio', 'video', 'code', 'export')),
  status text not null default 'processing' check (status in ('processing', 'ready', 'failed', 'deleted')),
  created_at timestamptz default now()
);

create table mcp_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  server text not null check (char_length(trim(server)) between 1 and 255),
  credentials_enc text,
  config jsonb default '{}',
  enabled boolean default true,
  created_at timestamptz default now(),
  unique (user_id, server)
);

create table user_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  shell_enabled boolean not null default false,
  always_allow jsonb not null default '[]',
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
  tool text not null check (char_length(trim(tool)) between 1 and 128),
  args jsonb,
  decision text not null check (decision in ('approved','denied','auto')),
  result_summary text,
  created_at timestamptz default now()
);

-- ------------------------------------------------------------------------------
-- 2. ROW LEVEL SECURITY ENFORCEMENT & FORCE RLS
-- ------------------------------------------------------------------------------
alter table user_secrets enable row level security;
alter table user_secrets force row level security;

alter table conversations enable row level security;
alter table conversations force row level security;

alter table messages enable row level security;
alter table messages force row level security;

alter table files enable row level security;
alter table files force row level security;

alter table mcp_connections enable row level security;
alter table mcp_connections force row level security;

alter table user_settings enable row level security;
alter table user_settings force row level security;

alter table feedback enable row level security;
alter table feedback force row level security;

alter table action_audit enable row level security;
alter table action_audit force row level security;

-- ------------------------------------------------------------------------------
-- 3. LEAST-PRIVILEGE GRANTS & ROLE REVOCATIONS
-- ------------------------------------------------------------------------------
-- Internal credentials: zero access to anon or authenticated
revoke all on table user_secrets, mcp_connections, user_settings from anon, authenticated, public;
grant all on table user_secrets, mcp_connections, user_settings to service_role;

-- Action audit: clients can select their own rows, but cannot insert/update/delete
revoke insert, update, delete, truncate on table action_audit from anon, authenticated, public;
grant select on table action_audit to authenticated;
grant all on table action_audit to service_role;

-- Standard user tables: authenticated only
revoke all on table conversations, messages, files, feedback from anon, public;
grant select, insert, update, delete on table conversations, messages, files, feedback to authenticated;
grant all on table conversations, messages, files, feedback to service_role;

-- ------------------------------------------------------------------------------
-- 4. BOLA / IDOR PROTECTED POLICIES
-- ------------------------------------------------------------------------------
-- Conversations
create policy "own rows" on conversations for all 
to authenticated
using (auth.uid() = user_id) 
with check (auth.uid() = user_id);

-- Messages: user must own message AND the parent conversation
create policy "own rows" on messages for all 
to authenticated
using (
  auth.uid() = user_id 
  and exists (
    select 1 from conversations 
    where conversations.id = messages.conversation_id 
      and conversations.user_id = auth.uid()
  )
)
with check (
  auth.uid() = user_id 
  and exists (
    select 1 from conversations 
    where conversations.id = messages.conversation_id 
      and conversations.user_id = auth.uid()
  )
);

-- Files: user must own file record AND the parent conversation
create policy "own rows" on files for all 
to authenticated
using (
  auth.uid() = user_id 
  and exists (
    select 1 from conversations 
    where conversations.id = files.conversation_id 
      and conversations.user_id = auth.uid()
  )
)
with check (
  auth.uid() = user_id 
  and exists (
    select 1 from conversations 
    where conversations.id = files.conversation_id 
      and conversations.user_id = auth.uid()
  )
);

-- Feedback: user must own feedback AND the parent message
create policy "own rows" on feedback for all 
to authenticated
using (
  auth.uid() = user_id 
  and exists (
    select 1 from messages 
    where messages.id = feedback.message_id 
      and messages.user_id = auth.uid()
  )
)
with check (
  auth.uid() = user_id 
  and exists (
    select 1 from messages 
    where messages.id = feedback.message_id 
      and messages.user_id = auth.uid()
  )
);

-- Action Audit: read-only for owner
create policy "own rows" on action_audit for select 
to authenticated
using (auth.uid() = user_id);

-- ------------------------------------------------------------------------------
-- 5. AUDIT IMMUTABILITY TRIGGER
-- ------------------------------------------------------------------------------
create or replace function public.prevent_audit_tampering()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  raise exception 'Security Violation: action_audit entries are immutable and cannot be updated or deleted.';
end;
$$;

create trigger trg_prevent_audit_tampering
before update or delete on action_audit
for each row
execute function public.prevent_audit_tampering();

-- ------------------------------------------------------------------------------
-- 6. RATE LIMITING & ANTI-FLOOD TRIGGER
-- ------------------------------------------------------------------------------
create or replace function public.check_message_rate_limit()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_recent_count int;
begin
  select count(*) into v_recent_count
  from messages
  where user_id = new.user_id
    and created_at >= (now() - interval '1 minute');

  if v_recent_count >= 60 then
    raise exception 'Rate Limit Exceeded: Maximum 60 messages per minute allowed.';
  end if;

  return new;
end;
$$;

create trigger trg_message_rate_limit
before insert on messages
for each row
execute function public.check_message_rate_limit();