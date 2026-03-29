import { NextResponse } from 'next/server';
import { SupabaseClient } from '@supabase/supabase-js';
import { createServerSupabase } from '@/lib/supabase/server';

/**
 * Verify the request is from an authenticated premium or admin user.
 * Returns the user, supabase client, and profile plan if authorized,
 * or a NextResponse error.
 *
 * Usage in route handlers:
 *   const auth = await requirePremium();
 *   if (auth.error) return auth.error;
 *   const { user, supabase } = auth;
 */
export async function requirePremium(): Promise<
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

    const { data: profile, error: profileError } = await supabase
      .from('user_profiles')
      .select('plan')
      .eq('id', user.id)
      .single();

    if (profileError) {
      return {
        user: null,
        supabase: null,
        error: NextResponse.json({ error: 'Failed to fetch user profile' }, { status: 500 }),
      };
    }

    if (!profile) {
      return {
        user: null,
        supabase: null,
        error: NextResponse.json({ error: 'Profile not found' }, { status: 404 }),
      };
    }

    if (profile.plan !== 'premium' && profile.plan !== 'admin') {
      return {
        user: null,
        supabase: null,
        error: NextResponse.json({ error: 'Premium required' }, { status: 403 }),
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
