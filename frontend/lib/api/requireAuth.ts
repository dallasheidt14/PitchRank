import { NextResponse } from 'next/server';
import { SupabaseClient } from '@supabase/supabase-js';
import { createServerSupabase } from '@/lib/supabase/server';

/**
 * Verify the request is from an authenticated user (any plan).
 * Returns the user and supabase client if authenticated,
 * or a NextResponse error.
 *
 * Usage in route handlers:
 *   const auth = await requireAuth();
 *   if (auth.error) return auth.error;
 *   const { user, supabase } = auth;
 */
export async function requireAuth(): Promise<
  | {
      user: { id: string; email?: string };
      supabase: SupabaseClient;
      error: null;
    }
  | { user: null; supabase: null; error: NextResponse }
> {
  try {
    const supabase = await createServerSupabase();

    const {
      data: { user },
      error: authError,
    } = await supabase.auth.getUser();

    if (authError || !user) {
      return {
        user: null,
        supabase: null,
        error: NextResponse.json({ error: 'Not authenticated' }, { status: 401 }),
      };
    }

    return { user, supabase, error: null };
  } catch {
    return {
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Authentication failed' }, { status: 500 }),
    };
  }
}
