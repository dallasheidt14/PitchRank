import { stripe, WEBHOOK_EVENTS, extractPeriodEnd, mapStatusToPlan, updateUserProfile } from '@/lib/stripe/server';
import { headers } from 'next/headers';
import { NextResponse } from 'next/server';
import { createClient, SupabaseClient } from '@supabase/supabase-js';
import Stripe from 'stripe';
import { notifyAdmin } from '@/lib/notifications/admin';

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
        console.log(`Unhandled event type: ${event.type}`);
    }

    return NextResponse.json({ received: true });
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const errorStack = error instanceof Error ? error.stack : undefined;
    console.error(`Webhook handler error for ${event.type}: ${errorMessage}`);
    if (errorStack) console.error(errorStack);
    // Return 200 to acknowledge receipt and prevent Stripe from retrying
    // for up to 72 hours. Permanent errors (missing user, bad data) won't
    // resolve on retry. Transient errors (DB timeout) are rare and can be
    // reprocessed manually if needed.
    return NextResponse.json({ received: true, error: 'Webhook handler failed', detail: errorMessage }, { status: 200 });
  }
}

/**
 * Handle successful checkout - activate subscription
 */
async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const customerId = session.customer as string;
  const subscriptionId = session.subscription as string;

  if (!customerId || !subscriptionId) {
    console.error('Missing customer or subscription ID in checkout session');
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
    }),
    stripe.customers.retrieve(customerId),
  ]);

  console.log(`Subscription activated for customer ${customerId}`);

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
}

/**
 * Handle subscription updates (plan changes, renewals)
 */
async function handleSubscriptionUpdated(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;
  const status = subscription.status;
  const plan = mapStatusToPlan(status);

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    stripe_subscription_id: subscription.id,
    subscription_status: status,
    plan,
    subscription_period_end: extractPeriodEnd(subscription),
  });

  console.log(`Subscription updated for customer ${customerId}: ${status}`);
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
  });

  console.log(`Subscription canceled for customer ${customerId}`);
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
    (typeof parentSub === 'string' ? parentSub : typeof parentSub === 'object' && parentSub !== null ? (parentSub as { id: string }).id : null)
    ?? (typeof legacySub === 'string' ? legacySub : null);

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
  });

  console.log(`Invoice paid for customer ${customerId}`);
}

/**
 * Handle failed invoice payment
 */
async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  const customerId = invoice.customer as string;

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    subscription_status: 'past_due',
  });

  console.log(`Payment failed for customer ${customerId}`);
}
