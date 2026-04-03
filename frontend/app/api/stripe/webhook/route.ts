import { stripe, WEBHOOK_EVENTS, extractPeriodEnd, mapStatusToPlan, updateUserProfile } from '@/lib/stripe/server';
import { headers } from 'next/headers';
import { NextResponse } from 'next/server';
import { createClient, SupabaseClient } from '@supabase/supabase-js';
import Stripe from 'stripe';
import { notifyAdmin } from '@/lib/notifications/admin';
import { tagSubscriber, untagSubscriber } from '@/lib/beehiiv';

// Lazy-load Supabase admin client to avoid build-time initialization errors
let supabaseAdmin: SupabaseClient | null = null;

function getSupabaseAdmin(): SupabaseClient {
  if (!supabaseAdmin) {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!supabaseUrl || !serviceRoleKey) {
      throw new Error(`Missing Supabase environment variables (url=${!!supabaseUrl}, key=${!!serviceRoleKey})`);
    }
    supabaseAdmin = createClient(supabaseUrl, serviceRoleKey);
  }
  return supabaseAdmin;
}

/**
 * Permanent errors that won't resolve on retry — return 200 so Stripe
 * stops retrying. Everything else returns 500 so Stripe retries.
 */
function isPermanentError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error);
  return msg.includes('No user profile found for Stripe customer');
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
      return NextResponse.json(
        { received: true, error: 'Permanent webhook error', details: errorMessage },
        { status: 200 }
      );
    }

    // Transient error (DB timeout, network issue) — return 500 so Stripe retries
    return NextResponse.json({ error: 'Webhook handler failed', details: errorMessage }, { status: 500 });
  }
}

/**
 * Handle successful checkout - activate subscription
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
  // Fetch customer details in parallel (independent of DB update)
  const [, customer] = await Promise.all([
    updateUserProfile(getSupabaseAdmin(), customerId, {
      stripe_subscription_id: subscriptionId,
      subscription_status: subscription.status,
      plan: mapStatusToPlan(subscription.status),
      subscription_period_end: extractPeriodEnd(subscription),
      cancel_at_period_end: false,
    }),
    stripe.customers.retrieve(customerId),
  ]);

  console.log(`[webhook] Subscription activated for customer ${customerId}`);

  // Notify admin of new signup
  const customerName = (customer as Stripe.Customer).name ?? 'Unknown';
  const customerEmail = (customer as Stripe.Customer).email ?? 'N/A';
  const statusLabel = subscription.status === 'trialing' ? '🆓 Free Trial' : '💳 Paid';
  const interval = subscription.items.data[0]?.price?.recurring?.interval;
  const planLabel = interval === 'month' ? 'Premium Monthly' : 'Premium Annual';

  await notifyAdmin(
    `<b>New Signup!</b>\n` +
      `${statusLabel}\n` +
      `<b>Name:</b> ${customerName}\n` +
      `<b>Email:</b> ${customerEmail}\n` +
      `<b>Plan:</b> ${planLabel}\n` +
      `<b>Status:</b> ${subscription.status}`
  );

  // Set subscriber tier to premium in Beehiiv (gates welcome sequence pitch emails)
  if (customerEmail && customerEmail !== 'N/A') {
    await tagSubscriber(customerEmail);
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

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    stripe_subscription_id: subscription.id,
    subscription_status: status,
    plan,
    subscription_period_end: extractPeriodEnd(subscription),
    cancel_at_period_end: canceling,
  });

  const label = canceling ? `${status} (canceling at period end)` : status;
  console.log(`[webhook] Subscription updated for customer ${customerId}: ${label}`);
}

/**
 * Handle subscription cancellation
 */
async function handleSubscriptionDeleted(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    stripe_subscription_id: null,
    subscription_status: 'canceled',
    plan: 'free',
    subscription_period_end: null,
    cancel_at_period_end: false,
  });

  console.log(`[webhook] Subscription canceled for customer ${customerId}`);

  // Remove premium tag in Beehiiv so they re-enter the pitch funnel
  try {
    const customer = await stripe.customers.retrieve(customerId);
    const email = (customer as Stripe.Customer).email;
    if (email) {
      await untagSubscriber(email);
    }
  } catch (err) {
    console.warn(`[webhook] Failed to untag Beehiiv subscriber: ${err}`);
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

  // Fetch subscription to get updated period end
  const subscriptionData = await stripe.subscriptions.retrieve(subscriptionId);
  await updateUserProfile(getSupabaseAdmin(), customerId, {
    subscription_status: subscriptionData.status,
    plan: mapStatusToPlan(subscriptionData.status),
    subscription_period_end: extractPeriodEnd(subscriptionData),
    cancel_at_period_end: subscriptionData.cancel_at_period_end ?? false,
  });

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
}
