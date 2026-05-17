import { stripe, WEBHOOK_EVENTS, extractPeriodEnd, mapStatusToPlan, updateUserProfile } from '@/lib/stripe/server';
import { getSupabaseAdmin } from '@/lib/supabase/service';
import { headers } from 'next/headers';
import { NextResponse } from 'next/server';
import Stripe from 'stripe';
import { notifyAdmin } from '@/lib/notifications/admin';
import { tagSubscriber, untagSubscriber, setLifecycle, type Lifecycle } from '@/lib/beehiiv';
import { sendPasswordSetupEmail } from '@/lib/email/password-setup';

/**
 * Permanent errors that won't resolve on retry — return 200 so Stripe
 * stops retrying. Everything else returns 500 so Stripe retries.
 */
function isPermanentError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    msg.includes('No user profile found for Stripe customer') ||
    msg.includes('already been registered') ||
    msg.includes('already exists')
  );
}

/**
 * Read current subscription_status + cancel_at_period_end from user_profiles
 * BEFORE the webhook update overwrites them. Used to detect transitions
 * (trialing → active, canceling → reactivated, etc.) for Beehiiv routing.
 */
async function getPriorState(customerId: string): Promise<{ status: string | null; canceling: boolean }> {
  const { data } = await getSupabaseAdmin()
    .from('user_profiles')
    .select('subscription_status, cancel_at_period_end')
    .eq('stripe_customer_id', customerId)
    .maybeSingle();
  return {
    status: data?.subscription_status ?? null,
    canceling: data?.cancel_at_period_end ?? false,
  };
}

/**
 * Resolve a Stripe customer's email. Returns null if the customer was
 * deleted or the API call fails.
 */
async function getCustomerEmail(customerId: string): Promise<string | null> {
  try {
    const customer = await stripe.customers.retrieve(customerId);
    return (customer as Stripe.Customer).email ?? null;
  } catch (err) {
    console.warn(`[webhook] Failed to retrieve customer ${customerId}: ${err}`);
    return null;
  }
}

/**
 * Set the Beehiiv lifecycle field for a customer by email. Non-fatal —
 * Beehiiv errors are logged but don't fail the webhook (Stripe shouldn't
 * retry a successful state update just because an email tag failed).
 */
async function syncLifecycle(customerId: string, lifecycle: Lifecycle): Promise<void> {
  try {
    const email = await getCustomerEmail(customerId);
    if (email) await setLifecycle(email, lifecycle);
  } catch (err) {
    console.error(`[webhook] syncLifecycle(${lifecycle}) failed (non-fatal):`, err);
  }
}

export async function POST(req: Request) {
  const body = await req.text();
  const headersList = await headers();
  const sig = headersList.get('stripe-signature');

  if (!sig) {
    console.error('Missing stripe-signature header');
    return NextResponse.json({ error: 'Missing stripe-signature header' }, { status: 400 });
  }

  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET?.trim();
  if (!webhookSecret) {
    console.error('Missing STRIPE_WEBHOOK_SECRET environment variable');
    return NextResponse.json({ error: 'Webhook not configured' }, { status: 500 });
  }

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(body, sig, webhookSecret);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.error(`Webhook signature verification failed: ${message}`);
    return NextResponse.json({ error: 'Webhook signature verification failed' }, { status: 400 });
  }

  console.log(`[webhook] Received ${event.type} (${event.id})`);

  try {
    switch (event.type) {
      case WEBHOOK_EVENTS.CHECKOUT_COMPLETED: {
        const session = event.data.object as Stripe.Checkout.Session;
        await handleCheckoutCompleted(session);
        break;
      }

      case WEBHOOK_EVENTS.SUBSCRIPTION_UPDATED: {
        const subscription = event.data.object as Stripe.Subscription;
        await handleSubscriptionUpdated(subscription);
        break;
      }

      case WEBHOOK_EVENTS.SUBSCRIPTION_DELETED: {
        const subscription = event.data.object as Stripe.Subscription;
        await handleSubscriptionDeleted(subscription);
        break;
      }

      case WEBHOOK_EVENTS.INVOICE_PAID: {
        const invoice = event.data.object as Stripe.Invoice;
        await handleInvoicePaid(invoice);
        break;
      }

      case WEBHOOK_EVENTS.INVOICE_PAYMENT_FAILED: {
        const invoice = event.data.object as Stripe.Invoice;
        await handleInvoicePaymentFailed(invoice);
        break;
      }

      case WEBHOOK_EVENTS.TRIAL_WILL_END: {
        const subscription = event.data.object as Stripe.Subscription;
        await handleTrialWillEnd(subscription);
        break;
      }

      case WEBHOOK_EVENTS.CHARGE_REFUNDED: {
        const charge = event.data.object as Stripe.Charge;
        await handleChargeRefunded(charge);
        break;
      }

      default:
        console.log(`[webhook] Unhandled event type: ${event.type}`);
    }

    return NextResponse.json({ received: true });
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const errorStack = error instanceof Error ? error.stack : undefined;
    console.error(`[webhook] Handler error for ${event.type}: ${errorMessage}`);
    if (errorStack) console.error(errorStack);

    if (isPermanentError(error)) {
      // No matching user — retrying won't help. Acknowledge so Stripe stops.
      console.warn(`[webhook] Permanent error, returning 200 to stop retries`);
      return NextResponse.json({ received: true, error: 'Permanent webhook error' }, { status: 200 });
    }

    // Transient error (DB timeout, network issue) — return 500 so Stripe retries
    return NextResponse.json({ error: 'Webhook handler failed' }, { status: 500 });
  }
}

/**
 * Handle successful checkout - activate subscription.
 * Supports both authenticated checkouts (user already has a profile with
 * stripe_customer_id) and anonymous checkouts (no Supabase account yet).
 */
async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const customerId = session.customer as string;
  const subscriptionId = session.subscription as string;

  if (!customerId || !subscriptionId) {
    console.error('[webhook] Missing customer or subscription ID in checkout session');
    return;
  }

  // Fetch subscription details to get period end and status (may be "trialing" for free trials)
  const subscription = await stripe.subscriptions.retrieve(subscriptionId);

  const baseUpdates = {
    stripe_subscription_id: subscriptionId,
    subscription_status: subscription.status,
    plan: mapStatusToPlan(subscription.status),
    subscription_period_end: extractPeriodEnd(subscription),
    cancel_at_period_end: false,
  };

  // Check if a user profile already exists for this Stripe customer (authenticated checkout)
  const { data: existingProfile } = await getSupabaseAdmin()
    .from('user_profiles')
    .select('id')
    .eq('stripe_customer_id', customerId)
    .maybeSingle();

  let customer: Stripe.Customer | Stripe.DeletedCustomer;

  if (existingProfile) {
    // --- Authenticated checkout: profile exists, update it ---
    [, customer] = await Promise.all([
      updateUserProfile(getSupabaseAdmin(), customerId, baseUpdates),
      stripe.customers.retrieve(customerId),
    ]);
  } else {
    // --- Anonymous checkout: create or link Supabase account ---
    customer = await stripe.customers.retrieve(customerId);
    const email = (customer as Stripe.Customer).email;

    if (!email) {
      console.error('[webhook] Anonymous checkout but Stripe customer has no email');
      return;
    }

    const anonymousUpdates = { stripe_customer_id: customerId, ...baseUpdates };

    // Check if a user already exists with this email (signed up but checked out anonymously)
    const { data: profileByEmail } = await getSupabaseAdmin()
      .from('user_profiles')
      .select('id, stripe_customer_id')
      .eq('email', email)
      .maybeSingle();

    if (profileByEmail) {
      // Existing user — link Stripe subscription to their account
      await getSupabaseAdmin()
        .from('user_profiles')
        .update({ ...anonymousUpdates, updated_at: new Date().toISOString() })
        .eq('id', profileByEmail.id);

      await stripe.customers.update(customerId, {
        metadata: { supabase_user_id: profileByEmail.id },
      });

      console.log(`[webhook] Linked anonymous checkout to existing user ${profileByEmail.id}`);
    } else {
      // New user — create Supabase account
      const { data: newUser, error: createError } = await getSupabaseAdmin().auth.admin.createUser({
        email,
        email_confirm: true,
        user_metadata: { source: 'stripe_checkout' },
      });

      if (createError || !newUser?.user) {
        console.error('[webhook] Failed to create user for anonymous checkout:', createError);
        throw new Error(`Failed to create user for anonymous checkout: ${createError?.message}`);
      }

      // Update the profile created by handle_new_user trigger
      await getSupabaseAdmin()
        .from('user_profiles')
        .update({ ...anonymousUpdates, updated_at: new Date().toISOString() })
        .eq('id', newUser.user.id);

      // Link Stripe customer to the new Supabase user for future webhook lookups
      await stripe.customers.update(customerId, {
        metadata: { supabase_user_id: newUser.user.id },
      });

      console.log(`[webhook] Created new user ${newUser.user.id} for anonymous checkout`);

      // Send password-setup email (non-fatal if it fails)
      try {
        const { data: linkData } = await getSupabaseAdmin().auth.admin.generateLink({
          type: 'recovery',
          email,
          options: {
            redirectTo: `${process.env.NEXT_PUBLIC_SITE_URL}/auth/callback?next=/rankings`,
          },
        });

        const setupUrl = linkData?.properties?.action_link;
        if (setupUrl) {
          await sendPasswordSetupEmail(email, setupUrl);
        } else {
          console.warn('[webhook] Could not generate password setup link');
        }
      } catch (emailError) {
        console.error('[webhook] Password setup email failed (non-fatal):', emailError);
      }
    }
  }

  console.log(`[webhook] Subscription activated for customer ${customerId}`);

  // Notify admin of new signup — escape HTML to prevent injection via Stripe customer name
  const escapeHtml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const displayName = escapeHtml((customer as Stripe.Customer).name ?? 'Unknown');
  const displayEmail = escapeHtml((customer as Stripe.Customer).email ?? 'N/A');
  const statusLabel = subscription.status === 'trialing' ? '🆓 Free Trial' : '💳 Paid';
  const interval = subscription.items.data[0]?.price?.recurring?.interval;
  const planLabel = interval === 'month' ? 'Premium Monthly' : 'Premium Annual';

  await notifyAdmin(
    `<b>New Signup!</b>\n` +
      `${statusLabel}\n` +
      `<b>Name:</b> ${displayName}\n` +
      `<b>Email:</b> ${displayEmail}\n` +
      `<b>Plan:</b> ${planLabel}\n` +
      `<b>Status:</b> ${subscription.status}`
  );

  // Sync Beehiiv: set tier to premium (gates paywall content) and route into
  // Trial Onboarding (status=trialing) or Paid Drip (direct-to-paid checkout).
  const rawEmail = (customer as Stripe.Customer).email;
  if (rawEmail) {
    try {
      await tagSubscriber(rawEmail);
      await setLifecycle(rawEmail, subscription.status === 'trialing' ? 'trialing' : 'paid');
    } catch (tagError) {
      console.error('[webhook] Beehiiv sync failed (non-fatal):', tagError);
    }
  }
}

/**
 * Handle subscription updates (plan changes, renewals, cancellation intent)
 *
 * When a user cancels via Customer Portal, Stripe sets cancel_at_period_end=true
 * but keeps status as "active" until the period ends. We track this flag so the
 * dashboard can show the user as "canceling" rather than misleadingly "active".
 */
async function handleSubscriptionUpdated(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;
  const status = subscription.status;
  const plan = mapStatusToPlan(status);
  const canceling = subscription.cancel_at_period_end ?? false;

  const prior = await getPriorState(customerId);

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    stripe_subscription_id: subscription.id,
    subscription_status: status,
    plan,
    subscription_period_end: extractPeriodEnd(subscription),
    cancel_at_period_end: canceling,
  });

  // Route Beehiiv on cancel-at-period-end / reactivation transitions
  if (canceling && !prior.canceling) {
    await syncLifecycle(customerId, 'canceling');
  } else if (!canceling && prior.canceling && status === 'active') {
    await syncLifecycle(customerId, 'paid');
  }

  const label = canceling ? `${status} (canceling at period end)` : status;
  console.log(`[webhook] Subscription updated for customer ${customerId}: ${label}`);
}

/**
 * Handle subscription cancellation
 */
async function handleSubscriptionDeleted(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;
  const prior = await getPriorState(customerId);

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    stripe_subscription_id: null,
    subscription_status: 'canceled',
    plan: 'free',
    subscription_period_end: null,
    cancel_at_period_end: false,
  });

  console.log(`[webhook] Subscription canceled for customer ${customerId} (prior status: ${prior.status})`);

  // Remove premium tag in Beehiiv + route into Trial Cancel or Paid Win-Back
  // based on whether they were trialing or actively paying when canceled.
  try {
    const email = await getCustomerEmail(customerId);
    if (email) {
      await untagSubscriber(email);
      await setLifecycle(email, prior.status === 'trialing' ? 'trial_canceled' : 'paid_canceled');
    }
  } catch (err) {
    console.warn(`[webhook] Failed to sync Beehiiv on cancel: ${err}`);
  }
}

/**
 * Handle successful invoice payment (subscription renewal)
 */
async function handleInvoicePaid(invoice: Stripe.Invoice) {
  const customerId = invoice.customer as string;
  // Get subscription ID - handle both new (dahlia+) and old (clover) API versions
  // New: invoice.parent.subscription_details.subscription
  // Old: invoice.subscription (top-level, removed in dahlia)
  const parentSub = invoice.parent?.subscription_details?.subscription;
  const legacySub = (invoice as unknown as Record<string, unknown>).subscription;
  const subscriptionId =
    (typeof parentSub === 'string'
      ? parentSub
      : typeof parentSub === 'object' && parentSub !== null
        ? (parentSub as { id: string }).id
        : null) ?? (typeof legacySub === 'string' ? legacySub : null);

  if (!subscriptionId) {
    // One-time payment, not a subscription
    return;
  }

  const prior = await getPriorState(customerId);

  // Fetch subscription to get updated period end
  const subscriptionData = await stripe.subscriptions.retrieve(subscriptionId);
  await updateUserProfile(getSupabaseAdmin(), customerId, {
    subscription_status: subscriptionData.status,
    plan: mapStatusToPlan(subscriptionData.status),
    subscription_period_end: extractPeriodEnd(subscriptionData),
    cancel_at_period_end: subscriptionData.cancel_at_period_end ?? false,
  });

  // Flip lifecycle to `paid` only on trial→paid or past_due→paid transitions.
  // Renewals (active → active) are no-ops so subscribers stay in Paid Drip
  // instead of re-entering it every billing cycle.
  if (subscriptionData.status === 'active' && (prior.status === 'trialing' || prior.status === 'past_due')) {
    await syncLifecycle(customerId, 'paid');
  }

  console.log(`[webhook] Invoice paid for customer ${customerId}`);
}

/**
 * Handle failed invoice payment
 */
async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  const customerId = invoice.customer as string;

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    subscription_status: 'past_due',
  });

  console.log(`[webhook] Payment failed for customer ${customerId}`);
  await syncLifecycle(customerId, 'past_due');
}

/**
 * Backup signal fired ~3 days before a trial ends. The Beehiiv Trial
 * Onboarding automation handles day-5/6/7 reminder emails on its own
 * clock; this is observability + a future hook for engagement-based
 * routing if Beehiiv timing drifts.
 */
async function handleTrialWillEnd(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;
  console.log(`[webhook] Trial will end for customer ${customerId} (subscription ${subscription.id})`);
}

/**
 * Refund means money back to the customer — route into the Paid Win-Back
 * sequence regardless of whether the underlying subscription was also canceled.
 */
async function handleChargeRefunded(charge: Stripe.Charge) {
  const customerId = charge.customer as string;
  if (!customerId) {
    console.log('[webhook] Charge refunded without a customer (guest checkout); skipping');
    return;
  }
  console.log(`[webhook] Charge refunded for customer ${customerId} (charge ${charge.id})`);
  await syncLifecycle(customerId, 'paid_canceled');
}
