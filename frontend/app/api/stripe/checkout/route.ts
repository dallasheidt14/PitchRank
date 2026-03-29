import { stripe } from '@/lib/stripe/server';
import { createServerSupabase } from '@/lib/supabase/server';
import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  try {
    const supabase = await createServerSupabase();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const { priceId } = await req.json();

    // Basic validation - ensure it looks like a Stripe price ID
    if (!priceId || typeof priceId !== 'string' || !priceId.startsWith('price_')) {
      return NextResponse.json({ error: 'Invalid price ID' }, { status: 400 });
    }

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
    if (profile?.subscription_status === 'active' || profile?.subscription_status === 'trialing') {
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

    // Belt-and-suspenders: check Stripe directly for existing subscriptions
    const existingSubs = await stripe.subscriptions.list({
      customer: customerId,
      limit: 10,
    });
    const activeSub = existingSubs.data.find((s) => s.status === 'active' || s.status === 'trialing');
    if (activeSub) {
      return NextResponse.json({ error: 'You already have an active subscription' }, { status: 400 });
    }

    // Create Stripe checkout session with 7-day free trial
    const session = await stripe.checkout.sessions.create({
      mode: 'subscription',
      customer: customerId,
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${process.env.NEXT_PUBLIC_SITE_URL}/upgrade/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${process.env.NEXT_PUBLIC_SITE_URL}/upgrade`,
      subscription_data: {
        trial_period_days: 7,
        metadata: {
          supabase_user_id: user.id,
        },
      },
      allow_promotion_codes: true,
      billing_address_collection: 'auto',
      customer_update: {
        address: 'auto',
        name: 'auto',
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
