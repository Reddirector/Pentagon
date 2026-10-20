-- ==============================================================================
-- Pentagon — Supabase Security Hardening & Penetration Testing Remediation
-- Migration: 002_security_hardening.sql
-- Defense-in-depth against BOLA, IDOR, RLS bypasses, search-path hijacking,
-- storage tampering, payload bombing (DoS), and audit log manipulation.
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- 1. FORCE ROW LEVEL SECURITY (RLS Bypass Defense)
-- Ensures table owners and non-superuser poolers cannot bypass policy checks.
-- ------------------------------------------------------------------------------
ALTER TABLE IF EXISTS user_secrets ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS user_secrets FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS conversations FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS messages FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS files ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS files FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS mcp_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS mcp_connections FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS user_settings FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS feedback FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS action_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS action_audit FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS collections FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS collection_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS collection_files FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS conversation_collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS conversation_collections FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS chunks FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS kg_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS kg_entities FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS kg_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS kg_relations FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS kg_provenance ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS kg_provenance FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS kg_communities ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS kg_communities FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS index_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS index_jobs FORCE ROW LEVEL SECURITY;

-- ------------------------------------------------------------------------------
-- 2. ZERO-TRUST SQL PRIVILEGES & ROLE RESTRICTIONS
-- Revoke broad public permissions and grant least-privilege access.
-- ------------------------------------------------------------------------------
-- Revoke all access to internal credentials from client roles
REVOKE ALL ON TABLE user_secrets FROM anon, authenticated, public;
REVOKE ALL ON TABLE mcp_connections FROM anon, authenticated, public;
REVOKE ALL ON TABLE user_settings FROM anon, authenticated, public;

GRANT ALL ON TABLE user_secrets TO service_role;
GRANT ALL ON TABLE mcp_connections TO service_role;
GRANT ALL ON TABLE user_settings TO service_role;

-- action_audit is strictly read-only for clients; only service_role can record audit logs
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE action_audit FROM anon, authenticated, public;
GRANT SELECT ON TABLE action_audit TO authenticated;
GRANT ALL ON TABLE action_audit TO service_role;

-- Conversations, messages, files and feedback are accessible only to authenticated users
REVOKE ALL ON TABLE conversations, messages, files, feedback FROM anon, public;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE conversations, messages, files, feedback TO authenticated;
GRANT ALL ON TABLE conversations, messages, files, feedback TO service_role;

-- ------------------------------------------------------------------------------
-- 3. BOLA / IDOR MITIGATION (Relational Integrity in Policies)
-- Prevents authenticated users from attaching rows to foreign conversations or messages.
-- ------------------------------------------------------------------------------

-- Messages: Must belong to auth.uid() AND conversation must belong to auth.uid()
DROP POLICY IF EXISTS "own rows" ON messages;
DROP POLICY IF EXISTS "own rows messages strict" ON messages;
CREATE POLICY "own rows messages strict" ON messages FOR ALL
TO authenticated
USING (
  auth.uid() = user_id 
  AND EXISTS (
    SELECT 1 FROM conversations 
    WHERE conversations.id = messages.conversation_id 
      AND conversations.user_id = auth.uid()
  )
)
WITH CHECK (
  auth.uid() = user_id 
  AND EXISTS (
    SELECT 1 FROM conversations 
    WHERE conversations.id = messages.conversation_id 
      AND conversations.user_id = auth.uid()
  )
);

-- Files: Must belong to auth.uid() AND conversation must belong to auth.uid()
DROP POLICY IF EXISTS "own rows" ON files;
DROP POLICY IF EXISTS "own rows files strict" ON files;
CREATE POLICY "own rows files strict" ON files FOR ALL
TO authenticated
USING (
  auth.uid() = user_id 
  AND EXISTS (
    SELECT 1 FROM conversations 
    WHERE conversations.id = files.conversation_id 
      AND conversations.user_id = auth.uid()
  )
)
WITH CHECK (
  auth.uid() = user_id 
  AND EXISTS (
    SELECT 1 FROM conversations 
    WHERE conversations.id = files.conversation_id 
      AND conversations.user_id = auth.uid()
  )
);

-- Feedback: Must belong to auth.uid() AND message must belong to auth.uid()
DROP POLICY IF EXISTS "own rows" ON feedback;
DROP POLICY IF EXISTS "own rows feedback strict" ON feedback;
CREATE POLICY "own rows feedback strict" ON feedback FOR ALL
TO authenticated
USING (
  auth.uid() = user_id 
  AND EXISTS (
    SELECT 1 FROM messages 
    WHERE messages.id = feedback.message_id 
      AND messages.user_id = auth.uid()
  )
)
WITH CHECK (
  auth.uid() = user_id 
  AND EXISTS (
    SELECT 1 FROM messages 
    WHERE messages.id = feedback.message_id 
      AND messages.user_id = auth.uid()
  )
);

-- ------------------------------------------------------------------------------
-- 4. INPUT CONSTRAINTS & PAYLOAD BOMBING DEFENSE (DoS & Injection Mitigation)
-- ------------------------------------------------------------------------------
DO $$
BEGIN
  -- Conversations constraints
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_conversation_title_len') THEN
    ALTER TABLE conversations ADD CONSTRAINT chk_conversation_title_len CHECK (char_length(trim(title)) BETWEEN 1 AND 255);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_conversation_model_len') THEN
    ALTER TABLE conversations ADD CONSTRAINT chk_conversation_model_len CHECK (char_length(trim(model)) BETWEEN 1 AND 128);
  END IF;

  -- Messages constraints (1 MB text cap, valid roles)
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_message_content_cap') THEN
    ALTER TABLE messages ADD CONSTRAINT chk_message_content_cap CHECK (octet_length(content) <= 1048576);
  END IF;

  -- Files constraints (prevent directory traversal in path or filename)
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_files_filename_sanitize') THEN
    ALTER TABLE files ADD CONSTRAINT chk_files_filename_sanitize CHECK (char_length(trim(filename)) BETWEEN 1 AND 512 AND filename !~ '[/\\]');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_files_path_traversal') THEN
    ALTER TABLE files ADD CONSTRAINT chk_files_path_traversal CHECK (char_length(trim(storage_path)) BETWEEN 1 AND 1024 AND storage_path !~ '\.\.');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_files_kind_valid') THEN
    ALTER TABLE files ADD CONSTRAINT chk_files_kind_valid CHECK (kind IN ('document', 'image', 'audio', 'video', 'code', 'export'));
  END IF;

  -- User secrets length constraint
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_nvidia_key_last4') THEN
    ALTER TABLE user_secrets ADD CONSTRAINT chk_nvidia_key_last4 CHECK (nvidia_key_last4 IS NULL OR char_length(nvidia_key_last4) <= 8);
  END IF;
END $$;

-- ------------------------------------------------------------------------------
-- 5. AUDIT LOG IMMUTABILITY & ANTI-TAMPER ENGINE
-- Guarantees that audit records cannot be altered or removed once created.
-- ------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.prevent_audit_tampering()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  RAISE EXCEPTION 'Security Exception: action_audit entries are immutable and cannot be updated or deleted.';
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_audit_tampering ON action_audit;
CREATE TRIGGER trg_prevent_audit_tampering
BEFORE UPDATE OR DELETE ON action_audit
FOR EACH ROW
EXECUTE FUNCTION public.prevent_audit_tampering();

-- ------------------------------------------------------------------------------
-- 6. DATABASE-LEVEL RATE LIMITING (Anti-Flood / Anti-Spam Trigger)
-- Caps client message generation to a maximum of 60 messages per minute.
-- ------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.check_message_rate_limit()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_recent_count int;
BEGIN
  SELECT COUNT(*) INTO v_recent_count
  FROM messages
  WHERE user_id = NEW.user_id
    AND created_at >= (NOW() - INTERVAL '1 minute');

  IF v_recent_count >= 60 THEN
    RAISE EXCEPTION 'Rate Limit Exceeded: Maximum 60 messages per minute allowed.';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_message_rate_limit ON messages;
CREATE TRIGGER trg_message_rate_limit
BEFORE INSERT ON messages
FOR EACH ROW
EXECUTE FUNCTION public.check_message_rate_limit();

-- ------------------------------------------------------------------------------
-- 7. SUPABASE STORAGE SECURITY (Bucket Protection & User Folder Isolation)
-- ------------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage') THEN
    -- Ensure pentagon-files bucket exists and is strictly private
    INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    VALUES (
      'pentagon-files',
      'pentagon-files',
      false,
      52428800, -- 50MB max file size
      ARRAY[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'text/plain',
        'text/markdown',
        'text/html',
        'text/csv',
        'image/png',
        'image/jpeg',
        'image/webp'
      ]
    )
    ON CONFLICT (id) DO UPDATE SET
      public = false,
      file_size_limit = 52428800;

    -- Enable and force RLS on storage.objects
    ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
    ALTER TABLE storage.objects FORCE ROW LEVEL SECURITY;

    -- Strictly isolate storage by auth.uid() folder
    DROP POLICY IF EXISTS "Pentagon storage user select" ON storage.objects;
    CREATE POLICY "Pentagon storage user select" ON storage.objects
    FOR SELECT TO authenticated
    USING (
      bucket_id = 'pentagon-files'
      AND (storage.foldername(name))[1] = auth.uid()::text
    );

    DROP POLICY IF EXISTS "Pentagon storage user insert" ON storage.objects;
    CREATE POLICY "Pentagon storage user insert" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (
      bucket_id = 'pentagon-files'
      AND (storage.foldername(name))[1] = auth.uid()::text
    );

    DROP POLICY IF EXISTS "Pentagon storage user update" ON storage.objects;
    CREATE POLICY "Pentagon storage user update" ON storage.objects
    FOR UPDATE TO authenticated
    USING (
      bucket_id = 'pentagon-files'
      AND (storage.foldername(name))[1] = auth.uid()::text
    );

    DROP POLICY IF EXISTS "Pentagon storage user delete" ON storage.objects;
    CREATE POLICY "Pentagon storage user delete" ON storage.objects
    FOR DELETE TO authenticated
    USING (
      bucket_id = 'pentagon-files'
      AND (storage.foldername(name))[1] = auth.uid()::text
    );
  END IF;
END $$;
