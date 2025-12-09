"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

// Singleton instance - ensures only ONE Supabase client exists in the browser
let supabaseInstance: SupabaseClient | null = null;

/**
 * Gets the singleton Supabase client for client-side operations
 *
 * IMPORTANT: This uses a singleton pattern to prevent the
 * "Multiple GoTrueClient instances detected" warning which
 * can cause auth state to not sync properly.
 */
export function createClientSupabase(): SupabaseClient {
  if (supabaseInstance) {
    return supabaseInstance;
  }

  // Let createBrowserClient handle cookies automatically
  supabaseInstance = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  return supabaseInstance;
}
