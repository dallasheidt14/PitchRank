import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import { optionalAuth } from '@/lib/api/optionalAuth';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { safeTeamPath } from '@/lib/auth/emailTokens';
import { CHECKOUT_BROWSER_COOKIE, isCheckoutBrowser } from '@/lib/stripe/checkoutBrowser';
import { stripe, isSessionPaymentSettled } from '@/lib/stripe/server';
import { createServerSupabase } from '@/lib/supabase/server';
import { getSupabaseAdmin } from '@/lib/supabase/service';

const MAX_ACCOUNT_AGE_MS = 30 * 60 * 1000;

function reply(body: Record<string, string>, status = 200) {
  return NextResponse.json(body, { status, headers: { 'Cache-Control': 'no-store' } });
}

const fallBackToEmail = () => reply({ status: 'email' });
const tryAgainShortly = () => reply({ status: 'pending' }, 202);

/**
 * POST /api/stripe/checkout-login
 *
 * Signs a guest buyer in on their return from Stripe, with no mailbox or password proof. Every
 * gate here keeps that to an account this checkout just created, in the browser that started the
 * checkout, and nobody has used yet. A refusal answers `email`, which sends the buyer to the
 * set-password link already in their inbox; `pending` asks the page to retry while the webhook is
 * still creating the account; a browser already signed in as the buyer gets `signed_in` and nothing
 * is minted.
 *
 * Refusals and sign-ins log through console.warn because production builds strip console.log.
 */
export async function POST(req: Request) {
  if (!req.headers.get('content-type')?.toLowerCase().startsWith('application/json')) {
    return reply({ error: 'Content-Type must be application/json' }, 415);
  }
  if (!checkRateLimit(`stripe-checkout-login:${getClientIp(req)}`, 10, 60_000)) {
    return reply({ status: 'email' }, 429);
  }

  try {
    const { sessionId } = await req.json();
    if (!sessionId || typeof sessionId !== 'string') return fallBackToEmail();

    const session = await stripe.checkout.sessions.retrieve(sessionId);
    if (session.status !== 'complete' || !isSessionPaymentSettled(session)) return fallBackToEmail();

    const next = safeTeamPath(session.metadata?.return_to) ?? '/rankings';
    const { user: caller } = await optionalAuth();

    if (caller && caller.id === session.metadata?.supabase_user_id) return reply({ status: 'signed_in', next });
    if (session.metadata?.anonymous_checkout !== 'true') return fallBackToEmail();
    if (!isCheckoutBrowser((await cookies()).get(CHECKOUT_BROWSER_COOKIE)?.value, session.metadata?.browser_key_hash)) {
      console.warn('[checkout-login] Refused: not the browser that started this checkout');
      return fallBackToEmail();
    }

    const customerId = typeof session.customer === 'string' ? session.customer : session.customer?.id;
    if (!customerId) return fallBackToEmail();

    const admin = getSupabaseAdmin();
    const { data: profile, error: profileError } = await admin
      .from('user_profiles')
      .select('id')
      .eq('stripe_customer_id', customerId)
      .maybeSingle();
    if (profileError) {
      console.error('[checkout-login] Profile lookup failed:', profileError.code);
      return fallBackToEmail();
    }
    if (!profile) return tryAgainShortly();

    const {
      data: { user: account },
      error: accountError,
    } = await admin.auth.admin.getUserById(profile.id);
    if (accountError || !account?.email) {
      console.error(`[checkout-login] Could not load account ${profile.id}`);
      return fallBackToEmail();
    }

    // A browser already signed in is never switched to another account.
    if (caller) return caller.id === account.id ? reply({ status: 'signed_in', next }) : fallBackToEmail();

    // Written this way round so an unreadable date fails the gate.
    const isNewAccount = Date.now() - new Date(account.created_at).getTime() < MAX_ACCOUNT_AGE_MS;
    if (account.last_sign_in_at || !isNewAccount) {
      console.warn(`[checkout-login] Refused account ${account.id}: already used or too old`);
      return fallBackToEmail();
    }

    const marker = account.app_metadata?.checkout_session_id;
    if (!marker) return tryAgainShortly();
    if (marker !== session.id) {
      console.warn(`[checkout-login] Refused account ${account.id}: marked by a different checkout`);
      return fallBackToEmail();
    }

    const { data: link, error: linkError } = await admin.auth.admin.generateLink({
      type: 'magiclink',
      email: account.email,
    });
    const tokenHash = link?.properties?.hashed_token;
    if (linkError || !tokenHash) {
      console.error(`[checkout-login] Could not mint a sign-in for account ${account.id}`);
      return fallBackToEmail();
    }

    const supabase = await createServerSupabase();
    const { error: verifyError } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type: 'magiclink' });
    if (verifyError) {
      console.error(`[checkout-login] Could not redeem the sign-in for account ${account.id}:`, verifyError.code);
      return fallBackToEmail();
    }

    console.warn(`[checkout-login] Signed in new account ${account.id}`);
    return reply({ status: 'signed_in', next });
  } catch (error) {
    // Only the error's name: a Stripe error message quotes the session id, which is a bearer secret here.
    console.error('[checkout-login] Failed:', error instanceof Error ? error.name : 'unknown error');
    return fallBackToEmail();
  }
}
