"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

// Singleton instance - ensures only ONE Supabase client exists in the browser
let supabaseInstance: SupabaseClient | null = null;

/**
 * Check if Supabase is configured
 */
export function isSupabaseConfigured(): boolean {
  return !!(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}

/**
 * Gets the singleton Supabase client for client-side operations
 *
 * IMPORTANT: This uses a singleton pattern to prevent the
 * "Multiple GoTrueClient instances detected" warning which
 * can cause auth state to not sync properly.
 *
 * Returns null if Supabase is not configured (missing env vars).
 */
export function createClientSupabase(): SupabaseClient | null {
  // Return null if Supabase is not configured
  if (!isSupabaseConfigured()) {
    return null;
  }

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
