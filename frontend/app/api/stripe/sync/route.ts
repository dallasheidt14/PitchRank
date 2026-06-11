import { stripe, extractPeriodEnd, mapStatusToPlan } from '@/lib/stripe/server';
import { getSupabaseAdmin } from '@/lib/supabase/service';
import { optionalAuth } from '@/lib/api/optionalAuth';
import { NextResponse } from 'next/server';

/**
 * POST /api/stripe/sync
 *
 * Fallback sync: given a checkout session_id, fetch the subscription from
 * Stripe and update user_profiles. This covers the case where the webhook
 * fails (misconfigured secret, cold-start timeout, etc.).
 *
 * Supports both authenticated users (verifies ownership via metadata or
 * stripe_customer_id) and anonymous checkouts (verifies via session_id,
 * which is a secret known only to the checkout user).
 */
export async function POST(req: Request) {
  try {
    const { user, supabase } = await optionalAuth();

    const { sessionId } = await req.json();
    if (!sessionId || typeof sessionId !== 'string') {
      return NextResponse.json({ error: 'Missing session_id' }, { status: 400 });
    }

    // Retrieve checkout session from Stripe
    const session = await stripe.checkout.sessions.retrieve(sessionId, {
      expand: ['subscription'],
    });

    if (!session.customer || !session.subscription) {
      return NextResponse.json({ error: 'Session has no subscription' }, { status: 400 });
    }

    const customerId = session.customer as string;
    const subscription =
      typeof session.subscription === 'string'
        ? await stripe.subscriptions.retrieve(session.subscription)
        : session.subscription;

    const status = subscription.status;
    const plan = mapStatusToPlan(status);
    const updates = {
      stripe_customer_id: customerId,
      stripe_subscription_id: subscription.id,
      subscription_status: status,
      plan,
      subscription_period_end: extractPeriodEnd(subscription),
      cancel_at_period_end: subscription.cancel_at_period_end ?? false,
      updated_at: new Date().toISOString(),
    };

    // --- Authenticated sync: verify ownership, update by user.id ---
    if (user && supabase) {
      const sessionUserId = session.metadata?.supabase_user_id;
      if (sessionUserId) {
        if (sessionUserId !== user.id) {
          return NextResponse.json({ error: 'Session does not belong to you' }, { status: 403 });
        }
      } else {
        const { data: profile } = await supabase
          .from('user_profiles')
          .select('stripe_customer_id')
          .eq('id', user.id)
          .single();
        if (!profile?.stripe_customer_id) {
          return NextResponse.json(
            { error: 'No customer ID on profile — cannot verify session ownership' },
            { status: 403 }
          );
        }
        if (profile.stripe_customer_id !== customerId) {
          return NextResponse.json({ error: 'Session does not belong to you' }, { status: 403 });
        }
      }

      // Ownership verified above; API roles no longer have UPDATE on user_profiles,
      // so billing writes go through the admin client.
      const { error: updateError } = await getSupabaseAdmin().from('user_profiles').update(updates).eq('id', user.id);

      if (updateError) {
        console.error('Sync: error updating profile:', updateError);
        return NextResponse.json({ error: 'Failed to sync' }, { status: 500 });
      }

      console.log(`Sync: updated user ${user.id} -> plan=${plan}, status=${status}, customer=${customerId}`);
      return NextResponse.json({ synced: true, plan, status });
    }

    // --- Anonymous sync: verify via session_id, update by stripe_customer_id ---
    // The session_id is a secret URL parameter from Stripe that only the checkout user has.
    const { data: profile, error: profileError } = await getSupabaseAdmin()
      .from('user_profiles')
      .select('id')
      .eq('stripe_customer_id', customerId)
      .maybeSingle();

    if (profileError) {
      console.error('Sync: error looking up profile:', profileError);
      return NextResponse.json({ error: 'Failed to sync' }, { status: 500 });
    }

    if (!profile) {
      // Webhook may not have fired yet — this is expected for very fast redirects
      console.log('Sync: no profile found for anonymous checkout (webhook may be pending)');
      return NextResponse.json({ synced: false, error: 'Profile not yet created' }, { status: 202 });
    }

    const { error: updateError } = await getSupabaseAdmin().from('user_profiles').update(updates).eq('id', profile.id);

    if (updateError) {
      console.error('Sync: error updating profile:', updateError);
      return NextResponse.json({ error: 'Failed to sync' }, { status: 500 });
    }

    console.log(`Sync: updated anonymous user ${profile.id} -> plan=${plan}, status=${status}`);
    return NextResponse.json({ synced: true, plan, status });
  } catch (error) {
    console.error('Sync error:', error);
    return NextResponse.json({ error: 'Failed to sync subscription' }, { status: 500 });
  }
}
