import { createClient, SupabaseClient } from '@supabase/supabase-js';

/**
 * Create a Supabase client with the service-role key for admin operations.
 * Use in API routes that need to bypass RLS (e.g., create-team, link-opponent).
 *
 * Throws if environment variables are missing (caught by route-level try/catch).
 */
export function createServiceSupabase(): SupabaseClient {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_KEY;

  if (!supabaseUrl || !serviceKey) {
    throw new Error(`Missing Supabase service environment variables (url=${!!supabaseUrl}, key=${!!serviceKey})`);
  }

  return createClient(supabaseUrl, serviceKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
      detectSessionInUrl: false,
    },
  });
}
