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
      "Missing Supabase environment variables for auth client. Please set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY"
    );
    throw new Error("Supabase environment variables not configured");
  }

  // Let createBrowserClient handle cookies automatically
  supabaseInstance = createBrowserClient(supabaseUrl, supabaseAnonKey);

  return supabaseInstance;
}
