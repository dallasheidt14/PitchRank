"use client";

import { createBrowserClient } from "@supabase/ssr";

/**
 * Creates a Supabase client for client-side operations
 *
 * Use this in:
 * - Client Components (use client)
 * - Event handlers
 * - Client-side effects
 */
export function createClientSupabase() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookieOptions: {
        // Ensure cookie reading works correctly
        path: "/",
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
      },
    }
  );
}
