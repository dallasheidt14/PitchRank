import { NextResponse } from 'next/server';
import { SupabaseClient } from '@supabase/supabase-js';
import { createServerSupabase } from './server';

/**
 * Verify the request is from an authenticated admin user.
 * Returns the user and supabase client if authorized, or a NextResponse error.
 *
 * Usage in route handlers:
 *   const auth = await requireAdmin();
 *   if (auth.error) return auth.error;
 *   const { user, supabase } = auth;
 */
export async function requireAdmin(): Promise<
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

    const { data: profile } = await supabase.from('user_profiles').select('plan').eq('id', user.id).single();

    if (!profile || profile.plan !== 'admin') {
      return {
        user: null,
        supabase: null,
        error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
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
