import { cookies } from "next/headers";
import { createServerClient, type SupabaseClient } from "@supabase/ssr";

/**
 * Check if Supabase is configured on the server
 */
export function isServerSupabaseConfigured(): boolean {
  return !!(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}

/**
 * Creates a Supabase client for server-side operations
 * Use in: Server Components, Route Handlers, Server Actions
 *
 * Returns null if Supabase is not configured (missing env vars).
 */
export async function createServerSupabase(): Promise<SupabaseClient | null> {
  if (!isServerSupabaseConfigured()) {
    return null;
  }

  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => {
              cookieStore.set(name, value, options);
            });
          } catch {
            // Ignored for Server Components - middleware handles session refresh
          }
        },
      },
    }
  );
}
