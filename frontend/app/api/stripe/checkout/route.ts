import { stripe, getStripePriceIds } from '@/lib/stripe/server';
import { getSupabaseAdmin } from '@/lib/supabase/service';
import { optionalAuth } from '@/lib/api/optionalAuth';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { gaClientIdFromCookie } from '@/lib/analyticsServer';
import { safeTeamPath } from '@/lib/auth/emailTokens';
import { newCheckoutBrowserKey } from '@/lib/stripe/checkoutBrowser';
import { sanitizeAttribution } from '@/lib/attribution';
import {
  LIVE_SUBSCRIPTION_STATUSES,
  STANDARD_REFUSED_STATUSES,
  hasPremiumPlan,
  isStandardRefusedStatus,
  type LiveSubscriptionStatus,
} from '@/lib/plan';
import { findPromotionById, type Promotion } from '@/lib/promotions';
import { getLivePromotion, getPromotionCouponId, getPromotionStatus } from '@/lib/promotions.server';
import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type Stripe from 'stripe';

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const ALREADY_SUBSCRIBED = 'You already have an active subscription';

function baseSessionParams(
  priceId: string,
  returnTo: string | null,
  couponId?: string
): Partial<Stripe.Checkout.SessionCreateParams> {
  return {
    mode: 'subscription',
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${process.env.NEXT_PUBLIC_SITE_URL}/upgrade/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.NEXT_PUBLIC_SITE_URL}/upgrade${returnTo ? `?next=${encodeURIComponent(returnTo)}` : ''}`,
    // Stripe refuses promotion codes beside a discount, which also stops a code stacking on a sale.
    ...(couponId ? { discounts: [{ coupon: couponId }] } : { allow_promotion_codes: true }),
    billing_address_collection: 'auto',
  };
}

function isPriceId(value: unknown): value is string {
  return typeof value === 'string' && value.startsWith('price_');
}

/** The yearly price the upgrade page posts. A sale charges exactly that price and no other. */
function saleYearlyPriceId(): string | undefined {
  return process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY || process.env.STRIPE_PRICE_YEARLY;
}

/**
 * A sale checkout closes when the sale ends, but no sooner than 31 minutes and no later than 23 hours
 * after it opens: Stripe accepts 30 minutes to 24 hours from creation on its own clock, so both ends
 * keep a margin.
 */
function saleSessionExpiresAt(promotion: Promotion, nowMs: number): number {
  const endsAt = Date.parse(promotion.endsAt);
  return Math.floor(Math.min(Math.max(endsAt, nowMs + 31 * MINUTE_MS), nowMs + 23 * HOUR_MS) / 1000);
}

/** The order a subscription moves through the live statuses: a trial turns active, an active one falls past_due. */
const STATUS_ORDER: readonly LiveSubscriptionStatus[] = ['trialing', 'active', 'past_due'];

/**
 * One filtered list per status given, read one after another in the order a subscription moves
 * through them, so one that changes status during the check is still in a later list. A
 * `status: 'all'` page can hide a live subscription behind cancelled ones.
 */
async function holdsSubscriptionIn(customerId: string, statuses: readonly LiveSubscriptionStatus[]): Promise<boolean> {
  for (const status of STATUS_ORDER.filter((s) => statuses.includes(s))) {
    const list = await stripe.subscriptions.list({ customer: customerId, status, limit: 1 });
    if (list.data.length > 0) return true;
  }
  return false;
}

/**
 * Around a sale a customer keeps one open checkout, so a standard checkout and a sale checkout left
 * open in two tabs cannot both be paid. Every id is collected before any is expired, because
 * expiring changes the filtered set under the cursor.
 */
async function expireOpenSessions(customerId: string): Promise<void> {
  const ids: string[] = [];
  let startingAfter: string | undefined;
  for (;;) {
    const page = await stripe.checkout.sessions.list({
      customer: customerId,
      status: 'open',
      ...(startingAfter ? { starting_after: startingAfter } : {}),
    });
    ids.push(...page.data.map((session) => session.id));
    startingAfter = page.data.at(-1)?.id;
    if (!page.has_more || !startingAfter) break;
  }
  for (const id of ids) {
    try {
      await stripe.checkout.sessions.expire(id);
    } catch (error) {
      // Only an open session expires. One completed meanwhile shows up in the caller's re-check.
      const session = await stripe.checkout.sessions.retrieve(id);
      if (session.status === 'open') throw error;
    }
  }
}

/** While a sale is live or switched off, and for a day after its scheduled end, when late sale checkouts can still be open. */
function inPromotionPeriod(nowMs: number): boolean {
  const status = getPromotionStatus(nowMs);
  if (status.state === 'live') return true;
  return status.state === 'ended' && nowMs < Date.parse(status.promotion.endsAt) + 24 * HOUR_MS;
}

export async function POST(req: Request) {
  try {
    // Unauthenticated endpoint that creates Stripe customers/sessions —
    // throttle to blunt cost/DoS amplification
    const ip = getClientIp(req);
    if (!checkRateLimit(`stripe-checkout:${ip}`, 5, 60_000)) {
      return NextResponse.json({ error: 'Too many requests. Please try again later.' }, { status: 429 });
    }

    const { user, supabase } = await optionalAuth();

    const { priceId, next, promotion: promotionId, attribution: rawAttribution } = await req.json();
    const attribution = sanitizeAttribution(rawAttribution);
    const now = Date.now();

    // An unknown or ended sale, or a wrong price, is refused here, before any Stripe call.
    let sale: { promotion: Promotion; couponId: string } | null = null;
    if (promotionId != null) {
      const entry = typeof promotionId === 'string' ? findPromotionById(promotionId) : null;
      if (!entry) {
        return NextResponse.json({ error: "This offer isn't available." }, { status: 400 });
      }
      const promotion = getLivePromotion(entry.id, now);
      if (!promotion) {
        return NextResponse.json({ error: entry.copy.endedNotice }, { status: 400 });
      }
      // The format check also catches a misconfigured price variable before any open checkout is expired.
      if (!isPriceId(priceId) || priceId !== saleYearlyPriceId()) {
        return NextResponse.json({ error: 'Invalid price ID' }, { status: 400 });
      }
      sale = { promotion, couponId: getPromotionCouponId(promotion) };
    } else {
      // Basic validation - ensure it looks like a Stripe price ID
      if (!isPriceId(priceId)) {
        return NextResponse.json({ error: 'Invalid price ID' }, { status: 400 });
      }

      // Validate against known price IDs (check both server-side and client-side env vars
      // in case they differ between STRIPE_PRICE_* and NEXT_PUBLIC_STRIPE_PRICE_*)
      const { MONTHLY, YEARLY } = getStripePriceIds();
      const VALID_PRICE_IDS = new Set(
        [
          MONTHLY,
          YEARLY,
          process.env.NEXT_PUBLIC_STRIPE_PRICE_MONTHLY,
          process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY,
        ].filter(Boolean)
      );

      if (!VALID_PRICE_IDS.has(priceId)) {
        return NextResponse.json({ error: 'Invalid price ID' }, { status: 400 });
      }
    }

    const gaClientId = gaClientIdFromCookie((await cookies()).get('_ga')?.value);
    const returnTo = safeTeamPath(next);
    const sessionMetadata: Record<string, string> = {
      ...(gaClientId ? { ga_client_id: gaClientId } : {}),
      ...(returnTo ? { return_to: returnTo } : {}),
    };
    const saleMetadata = (segment: 'new' | 'returning' | 'signed_out'): Record<string, string> =>
      sale ? { promotion: sale.promotion.id, segment, ...attribution } : {};
    // Measured at creation, not at the start of the request: Stripe counts its 30-minute minimum from the
    // session's own creation, and the lookups and expiries before it take time.
    const saleExpiry = () => (sale ? { expires_at: saleSessionExpiresAt(sale.promotion, Date.now()) } : {});

    // --- Authenticated checkout: existing user ---
    if (user && supabase) {
      // Get user profile
      const { data: profile, error: profileError } = await supabase
        .from('user_profiles')
        .select('*')
        .eq('id', user.id)
        .single();

      if (profileError) {
        console.error('Error fetching profile:', profileError);
        return NextResponse.json({ error: 'Failed to fetch user profile' }, { status: 500 });
      }

      // A sale is for anyone not on a premium plan: payers, trials, past_due, cancel-scheduled and comped
      // accounts all hold one. A standard checkout refuses active or trialing subscriptions only.
      const alreadySubscribed = sale
        ? hasPremiumPlan(profile?.plan)
        : profile?.plan === 'premium' && isStandardRefusedStatus(profile?.subscription_status);
      if (alreadySubscribed) {
        return NextResponse.json({ error: ALREADY_SUBSCRIBED }, { status: 400 });
      }

      let customerId = profile?.stripe_customer_id;
      const createdCustomer = !customerId;

      const refused = sale ? LIVE_SUBSCRIPTION_STATUSES : STANDARD_REFUSED_STATUSES;
      // A customer created below is new to Stripe: no subscriptions to refuse on, and no trial used.
      let hasHadSubscription = false;
      if (customerId) {
        if (await holdsSubscriptionIn(customerId, refused)) {
          return NextResponse.json({ error: ALREADY_SUBSCRIBED }, { status: 400 });
        }
        // Read after the refusals, so a subscription started while they ran counts as history; its own
        // status is refused on too, since it began after the filtered lists were read.
        const history = await stripe.subscriptions.list({ customer: customerId, status: 'all', limit: 1 });
        if (history.data.some((s) => (refused as readonly string[]).includes(s.status))) {
          return NextResponse.json({ error: ALREADY_SUBSCRIBED }, { status: 400 });
        }
        // Only first-time subscribers get a trial.
        hasHadSubscription = history.data.length > 0;
      }
      const segment = hasHadSubscription ? 'returning' : 'new';

      // Create Stripe customer if one doesn't exist
      if (!customerId) {
        const customer = await stripe.customers.create({
          ...(user.email ? { email: user.email } : {}),
          metadata: {
            supabase_user_id: user.id,
          },
        });

        customerId = customer.id;

        // Save customer ID to profile - this MUST succeed for webhooks to work.
        // API roles have no UPDATE on user_profiles; write via the admin
        // client (user identity comes from the validated session above). Only a profile still without a
        // customer is written: a signed-out purchase that linked this account meanwhile, or a checkout
        // started in another tab, keeps the customer it wrote.
        const { data: linked, error: updateError } = await getSupabaseAdmin()
          .from('user_profiles')
          .update({ stripe_customer_id: customerId })
          .eq('id', user.id)
          .is('stripe_customer_id', null)
          .select('id');

        if (updateError) {
          console.error('Error saving customer ID to profile:', updateError);
          return NextResponse.json({ error: 'Failed to link billing account. Please try again.' }, { status: 500 });
        }
        if (!linked?.length) {
          return NextResponse.json(
            { error: 'Your account changed while checkout was starting. Please try again.' },
            { status: 409 }
          );
        }
      }

      // A customer created just now has no open checkouts and no subscriptions to find.
      if (!createdCustomer && (sale || inPromotionPeriod(now))) {
        await expireOpenSessions(customerId);
        // A checkout paid while the others were being listed or expired shows up here, so it is not
        // followed by a second one.
        if (await holdsSubscriptionIn(customerId, refused)) {
          return NextResponse.json({ error: ALREADY_SUBSCRIBED }, { status: 400 });
        }
      }

      // Create Stripe checkout session
      const session = await stripe.checkout.sessions.create({
        ...baseSessionParams(priceId, returnTo, sale?.couponId),
        customer: customerId,
        metadata: { supabase_user_id: user.id, ...sessionMetadata, ...saleMetadata(segment) },
        subscription_data: {
          ...(sale || hasHadSubscription ? {} : { trial_period_days: 7 }),
          metadata: { supabase_user_id: user.id, ...saleMetadata(segment) },
        },
        customer_update: {
          address: 'auto',
          name: 'auto',
        },
        ...saleExpiry(),
      });

      return NextResponse.json({ url: session.url });
    }

    // --- Anonymous checkout: no account yet ---
    // In subscription mode, Stripe automatically creates a customer when none is provided
    const browserKey = newCheckoutBrowserKey();
    const session = await stripe.checkout.sessions.create({
      ...baseSessionParams(priceId, returnTo, sale?.couponId),
      metadata: {
        anonymous_checkout: 'true',
        browser_key_hash: browserKey.keyHash,
        ...sessionMetadata,
        ...saleMetadata('signed_out'),
      },
      subscription_data: {
        ...(sale ? {} : { trial_period_days: 7 }),
        metadata: { anonymous_checkout: 'true', ...saleMetadata('signed_out') },
      },
      ...saleExpiry(),
    });

    const response = NextResponse.json({ url: session.url });
    response.cookies.set(browserKey.cookie);
    return response;
  } catch (error) {
    console.error('Checkout session error:', error);

    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    console.error('Checkout session detail:', errorMessage);
    return NextResponse.json({ error: 'Failed to create checkout session' }, { status: 500 });
  }
}
