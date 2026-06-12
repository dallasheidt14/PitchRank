import { stripe, getStripePriceIds } from '@/lib/stripe/server';
import { getSupabaseAdmin } from '@/lib/supabase/service';
import { optionalAuth } from '@/lib/api/optionalAuth';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { NextResponse } from 'next/server';
import type Stripe from 'stripe';

function baseSessionParams(priceId: string): Partial<Stripe.Checkout.SessionCreateParams> {
  return {
    mode: 'subscription',
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${process.env.NEXT_PUBLIC_SITE_URL}/upgrade/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.NEXT_PUBLIC_SITE_URL}/upgrade`,
    allow_promotion_codes: true,
    billing_address_collection: 'auto',
  };
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

    const { priceId } = await req.json();

    // Basic validation - ensure it looks like a Stripe price ID
    if (!priceId || typeof priceId !== 'string' || !priceId.startsWith('price_')) {
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

      // Check if user already has active or trialing subscription
      if (
        profile?.plan === 'premium' &&
        (profile?.subscription_status === 'active' || profile?.subscription_status === 'trialing')
      ) {
        return NextResponse.json({ error: 'You already have an active subscription' }, { status: 400 });
      }

      let customerId = profile?.stripe_customer_id;

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
        // API roles no longer have UPDATE on user_profiles; write via the admin
        // client (user identity comes from the validated session above).
        const { error: updateError } = await getSupabaseAdmin()
          .from('user_profiles')
          .update({ stripe_customer_id: customerId })
          .eq('id', user.id);

        if (updateError) {
          console.error('Error saving customer ID to profile:', updateError);
          return NextResponse.json({ error: 'Failed to link billing account. Please try again.' }, { status: 500 });
        }
      }

      // Check Stripe for existing subscriptions (active check + trial eligibility)
      const allSubs = await stripe.subscriptions.list({
        customer: customerId,
        status: 'all',
        limit: 10,
      });
      const activeSub = allSubs.data.find((s) => s.status === 'active' || s.status === 'trialing');
      if (activeSub) {
        return NextResponse.json({ error: 'You already have an active subscription' }, { status: 400 });
      }

      // Only grant trial to first-time subscribers
      const hasHadSubscription = allSubs.data.length > 0;

      // Create Stripe checkout session
      const session = await stripe.checkout.sessions.create({
        ...baseSessionParams(priceId),
        customer: customerId,
        metadata: { supabase_user_id: user.id },
        subscription_data: {
          ...(hasHadSubscription ? {} : { trial_period_days: 7 }),
          metadata: { supabase_user_id: user.id },
        },
        customer_update: {
          address: 'auto',
          name: 'auto',
        },
      });

      return NextResponse.json({ url: session.url });
    }

    // --- Anonymous checkout: no account yet ---
    // In subscription mode, Stripe automatically creates a customer when none is provided
    const session = await stripe.checkout.sessions.create({
      ...baseSessionParams(priceId),
      metadata: { anonymous_checkout: 'true' },
      subscription_data: {
        trial_period_days: 7,
        metadata: { anonymous_checkout: 'true' },
      },
    });

    return NextResponse.json({ url: session.url });
  } catch (error) {
    console.error('Checkout session error:', error);

    const errorMessage = error instanceof Error ? error.message : 'Unknown error';
    console.error('Checkout session detail:', errorMessage);
    return NextResponse.json({ error: 'Failed to create checkout session' }, { status: 500 });
  }
}
