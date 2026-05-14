import { createClient, SupabaseClient } from '@supabase/supabase-js';

/**
 * Create a Supabase client with the service-role key for admin operations.
 * Use in API routes that need to bypass RLS (e.g., create-team, link-opponent).
 *
 * Throws if environment variables are missing (caught by route-level try/catch).
 */
export function createServiceSupabase(): SupabaseClient {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error(`Missing Supabase service environment variables (url=${!!supabaseUrl}, key=${!!serviceRoleKey})`);
  }

  return createClient(supabaseUrl, serviceRoleKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
      detectSessionInUrl: false,
    },
  });
}

/**
 * Lazy-loaded singleton Supabase admin client for webhook/background operations.
 * Uses SUPABASE_SERVICE_ROLE_KEY (the key configured for Stripe webhooks and
 * server-side admin operations like user creation).
 *
 * Prefer createServiceSupabase() for short-lived route handlers.
 * Use this for long-lived modules (webhooks, sync) where a singleton avoids
 * repeated client construction.
 */
let _adminSingleton: SupabaseClient | null = null;

export function getSupabaseAdmin(): SupabaseClient {
  if (!_adminSingleton) {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!supabaseUrl || !serviceRoleKey) {
      throw new Error(`Missing Supabase environment variables (url=${!!supabaseUrl}, key=${!!serviceRoleKey})`);
    }
    _adminSingleton = createClient(supabaseUrl, serviceRoleKey);
  }
  return _adminSingleton;
}
