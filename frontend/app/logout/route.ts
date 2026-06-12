import { NextResponse } from 'next/server';
import { createServerSupabase } from '@/lib/supabase/server';

/**
 * POST /logout
 *
 * Signs the user out and redirects to the home page. POST only — a GET
 * handler here would let any third-party page force-sign-out users via a
 * cross-site image or link (CSRF).
 */
export async function POST(request: Request) {
  const requestUrl = new URL(request.url);

  const supabase = await createServerSupabase();
  await supabase.auth.signOut();

  return NextResponse.redirect(new URL('/', requestUrl.origin));
}
