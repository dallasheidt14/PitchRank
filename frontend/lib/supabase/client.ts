'use client';

import { createBrowserClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';

// Singleton instance - ensures only ONE Supabase client exists in the browser
let supabaseInstance: SupabaseClient | null = null;

/**
 * Gets the singleton Supabase client for client-side operations
 *
 * IMPORTANT: This uses a singleton pattern to prevent the
 * "Multiple GoTrueClient instances detected" warning which
 * can cause auth state to not sync properly.
 *
 * Environment variables are read at runtime (not build time) to ensure
 * they are always available after deployment.
 */
export function createClientSupabase(): SupabaseClient {
  if (supabaseInstance) {
    return supabaseInstance;
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseAnonKey) {
    console.error(
      'Missing Supabase environment variables for auth client. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY'
    );
    throw new Error('Supabase environment variables not configured');
  }

  supabaseInstance = createBrowserClient(supabaseUrl, supabaseAnonKey, {
    cookieOptions: {
      // @supabase/ssr's DEFAULT_COOKIE_OPTIONS omit `secure`, so the auth token
      // is otherwise offered on plaintext requests. Enabled only under HTTPS so
      // that http://localhost dev sessions still persist.
      secure: typeof window !== 'undefined' && window.location.protocol === 'https:',
    },
  });

  return supabaseInstance;
}
