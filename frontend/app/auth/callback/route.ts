import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { createServerClient } from '@supabase/ssr';
import { safeNextPath } from '@/lib/auth/emailTokens';

// Next.js aliases HEAD to the GET handler unless HEAD is exported, so a link
// scanner's HEAD would run the PKCE exchange below and spend that single-use
// code before the recipient clicks.
export async function HEAD(_request: Request) {
  return new NextResponse(null, { status: 200 });
}

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);

  const token_hash = searchParams.get('token_hash');
  const type = searchParams.get('type');
  const code = searchParams.get('code');
  // Default to /rankings instead of /watchlist to avoid redirecting free users to premium route
  const next = safeNextPath(searchParams.get('next'));
  const error = searchParams.get('error');
  const errorDescription = searchParams.get('error_description');

  // Handle auth errors from Supabase
  if (error) {
    console.error('[Auth Callback] Error:', error, errorDescription);
    return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent(errorDescription ?? error)}`);
  }

  // Redeeming here would spend the single-use token on GET, which is what a mail
  // scanner's fetch does before the recipient clicks. Links already sitting in
  // inboxes still arrive here, so this redirect is what protects them.
  if (token_hash && type) {
    const confirmUrl = new URL('/auth/confirm', origin);
    confirmUrl.searchParams.set('token_hash', token_hash);
    confirmUrl.searchParams.set('type', type);
    confirmUrl.searchParams.set('next', next);
    return NextResponse.redirect(confirmUrl);
  }

  const cookieStore = await cookies();

  // Create Supabase client - let it handle cookies automatically
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set(name, value, options);
          });
        },
      },
    }
  );

  // Handle OAuth/PKCE (code exchange flow)
  if (code) {
    const isRecovery = type === 'recovery' || cookieStore.get('password_reset_pending')?.value === 'true';

    const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);

    if (exchangeError) {
      console.error('[Auth Callback] Code exchange error:', exchangeError.message);

      // When PKCE code exchange fails (e.g., user opened the email confirmation
      // link in a different browser/tab where the code_verifier cookie is missing),
      // the email is still confirmed by Supabase — only the session creation failed.
      // Redirect to login with a success message so the user can sign in manually.
      const isCodeVerifierError =
        exchangeError.message.toLowerCase().includes('code verifier') ||
        exchangeError.message.toLowerCase().includes('code_verifier') ||
        exchangeError.message.toLowerCase().includes('pkce');

      if (isCodeVerifierError) {
        // Terminal failure: the code is consumed and the email confirmed, so this
        // recovery link can't be retried. Clear the flag now (it survives up to 24
        // hours otherwise) so it can't later hijack an unrelated code exchange in
        // this browser into the reset flow. Genuinely retryable errors fall through
        // below and keep the flag so a retried recovery link still routes to reset.
        if (isRecovery) {
          cookieStore.set('password_reset_pending', '', { path: '/', maxAge: 0 });
        }
        return NextResponse.redirect(
          `${origin}/login?message=${encodeURIComponent('Email confirmed! Please sign in with your password.')}`
        );
      }

      return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent(exchangeError.message)}`);
    }

    // Clear the recovery flag only now that the exchange has succeeded — clearing
    // it earlier would strip the recovery context from a retried link if the
    // exchange failed (C36), routing the retry to /rankings instead of reset.
    if (isRecovery) {
      cookieStore.set('password_reset_pending', '', { path: '/', maxAge: 0 });
      return NextResponse.redirect(`${origin}/reset-password`);
    }

    return NextResponse.redirect(`${origin}${next}`);
  }

  // No valid auth params
  return NextResponse.redirect(`${origin}/login`);
}
