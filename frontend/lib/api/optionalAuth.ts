import { SupabaseClient } from '@supabase/supabase-js';
import { createServerSupabase } from '@/lib/supabase/server';

/**
 * Try to get the authenticated user without failing.
 * Returns the user and supabase client if authenticated,
 * or null values if not — never returns an error response.
 *
 * Usage in route handlers that support both authenticated and anonymous access:
 *   const { user, supabase } = await optionalAuth();
 *   if (user) { ... } else { ... }
 */
export async function optionalAuth(): Promise<{
  user: { id: string; email?: string } | null;
  supabase: SupabaseClient | null;
}> {
  try {
    const supabase = await createServerSupabase();

    const {
      data: { user },
      error: authError,
    } = await supabase.auth.getUser();

    if (authError || !user) {
      return { user: null, supabase: null };
    }

    return { user, supabase };
  } catch {
    return { user: null, supabase: null };
  }
}
