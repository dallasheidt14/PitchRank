import { createBrowserClient } from '@supabase/ssr';
import { SupabaseClient } from '@supabase/supabase-js';

let supabaseBrowserInstance: SupabaseClient | null = null;

/**
 * Creates a Supabase client for use in browser/client components.
 * This is needed for Realtime subscriptions and client-side data fetching.
 */
export function createSupabaseBrowserClient(): SupabaseClient {
  if (supabaseBrowserInstance) {
    return supabaseBrowserInstance;
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error(
      'Missing Supabase environment variables. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY'
    );
  }

  supabaseBrowserInstance = createBrowserClient(supabaseUrl, supabaseAnonKey);
  return supabaseBrowserInstance;
}

/**
 * Hook to get Supabase browser client.
 * Safe to call multiple times - returns same instance.
 */
export function useSupabaseBrowser(): SupabaseClient {
  return createSupabaseBrowserClient();
}
