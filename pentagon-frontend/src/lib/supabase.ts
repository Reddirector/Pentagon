import { createClient } from '@supabase/supabase-js'
import type { SupabaseClient } from '@supabase/supabase-js'

const rawUrl = (import.meta.env.VITE_SUPABASE_URL as string | undefined)?.trim()
const rawAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined)?.trim()

/**
 * Validates that the Supabase endpoint is a legitimate HTTPS or trusted local URL
 * to defend against SSRF, open redirect, and malformed connection attacks.
 */
function isValidSupabaseUrl(url: string | undefined): boolean {
  if (!url) return false
  try {
    const parsed = new URL(url)
    return (
      parsed.protocol === 'https:' ||
      (parsed.protocol === 'http:' && (parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1'))
    )
  } catch {
    return false
  }
}

export const isSupabaseConfigured = Boolean(
  isValidSupabaseUrl(rawUrl) && rawAnonKey && rawAnonKey.length >= 20,
)

let client: SupabaseClient | null = null

/**
 * The hardened Supabase client.
 * Configured with:
 * - PKCE flow type (Proof Key for Code Exchange) to prevent OAuth code interception attacks.
 * - Secure session persistence with auto token refresh.
 * - Sanitized origin validation to thwart injection or credential forwarding tampering.
 */
export function getSupabase(): SupabaseClient | null {
  if (!isSupabaseConfigured || !rawUrl || !rawAnonKey) return null
  if (!client) {
    client = createClient(rawUrl, rawAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        flowType: 'pkce',
      },
    })
  }
  return client
}