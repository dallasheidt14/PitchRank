import { stripe, getStripePriceIds } from '@/lib/stripe/server';
import { optionalAuth } from '@/lib/api/optionalAuth';
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
    const { user, supabase } = await optionalAuth();

    const { priceId } = await req.json();

    // Basic validation - ensure it looks like a Stripe price ID
    if (!priceId || typeof priceId !== 'string' || !priceId.startsWith('price_')) {
      return NextResponse.json({ error: 'Invalid price ID' }, { status: 400 });
    }

    // Validate against known price IDs (uses env var fallback chain)
    const { MONTHLY, YEARLY } = getStripePriceIds();
    const VALID_PRICE_IDS = [MONTHLY, YEARLY].filter(Boolean);

    if (!VALID_PRICE_IDS.includes(priceId)) {
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

        // Save customer ID to profile - this MUST succeed for webhooks to work
        const { error: updateError } = await supabase
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
    const session = await stripe.checkout.sessions.create({
      ...baseSessionParams(priceId),
      customer_creation: 'always',
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
