import { stripe, WEBHOOK_EVENTS } from "@/lib/stripe/server";
import { headers } from "next/headers";
import { NextResponse } from "next/server";
import { createClient, SupabaseClient } from "@supabase/supabase-js";
import Stripe from "stripe";

// Lazy-load Supabase admin client to avoid build-time initialization errors
let supabaseAdmin: SupabaseClient | null = null;

function getSupabaseAdmin(): SupabaseClient {
  if (!supabaseAdmin) {
    if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.SUPABASE_SERVICE_ROLE_KEY) {
      throw new Error("Missing Supabase environment variables");
    }
    supabaseAdmin = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL,
      process.env.SUPABASE_SERVICE_ROLE_KEY
    );
  }
  return supabaseAdmin;
}

export async function POST(req: Request) {
  const body = await req.text();
  const headersList = await headers();
  const sig = headersList.get("stripe-signature");

  if (!sig) {
    console.error("Missing stripe-signature header");
    return NextResponse.json(
      { error: "Missing stripe-signature header" },
      { status: 400 }
    );
  }

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(
      body,
      sig,
      process.env.STRIPE_WEBHOOK_SECRET!
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`Webhook signature verification failed: ${message}`);
    return NextResponse.json(
      { error: `Webhook signature verification failed: ${message}` },
      { status: 400 }
    );
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
    console.error("Webhook handler error:", error);
    return NextResponse.json(
      { error: "Webhook handler failed" },
      { status: 500 }
    );
  }
}

/**
 * Handle successful checkout - activate subscription
 */
async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const customerId = session.customer as string;
  const subscriptionId = session.subscription as string;

  if (!customerId || !subscriptionId) {
    console.error("Missing customer or subscription ID in checkout session");
    return;
  }

  // Fetch subscription details to get period end
  const subscription = await stripe.subscriptions.retrieve(subscriptionId);
  const periodEnd = (subscription as { current_period_end?: number }).current_period_end ||
    Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60; // Default to 30 days from now

  const { data, error } = await getSupabaseAdmin()
    .from("user_profiles")
    .update({
      stripe_subscription_id: subscriptionId,
      subscription_status: "active",
      plan: "premium",
      subscription_period_end: new Date(periodEnd * 1000).toISOString(),
      updated_at: new Date().toISOString(),
    })
    .eq("stripe_customer_id", customerId)
    .select();

  if (error) {
    console.error("Error updating profile after checkout:", error);
    throw error;
  }

  if (!data || data.length === 0) {
    console.error(`No user found with stripe_customer_id: ${customerId}`);
    throw new Error(`No user profile found for Stripe customer ${customerId}`);
  }

  console.log(`Subscription activated for customer ${customerId}`);
}

/**
 * Handle subscription updates (plan changes, renewals)
 */
async function handleSubscriptionUpdated(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;
  const status = subscription.status;

  // Map Stripe status to our plan
  // Keep premium access during past_due (Stripe will retry payment)
  const plan = status === "active" || status === "trialing" || status === "past_due"
    ? "premium"
    : "free";

  // Get period end from subscription
  const periodEnd = (subscription as unknown as { current_period_end?: number }).current_period_end ||
    Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;

  const { data, error } = await getSupabaseAdmin()
    .from("user_profiles")
    .update({
      stripe_subscription_id: subscription.id,
      subscription_status: status,
      plan: plan,
      subscription_period_end: new Date(periodEnd * 1000).toISOString(),
      updated_at: new Date().toISOString(),
    })
    .eq("stripe_customer_id", customerId)
    .select();

  if (error) {
    console.error("Error updating subscription:", error);
    throw error;
  }

  if (!data || data.length === 0) {
    console.error(`No user found with stripe_customer_id: ${customerId}`);
    throw new Error(`No user profile found for Stripe customer ${customerId}`);
  }

  console.log(`Subscription updated for customer ${customerId}: ${status}`);
}

/**
 * Handle subscription cancellation
 */
async function handleSubscriptionDeleted(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;

  const { data, error } = await getSupabaseAdmin()
    .from("user_profiles")
    .update({
      stripe_subscription_id: null,
      subscription_status: "canceled",
      plan: "free",
      subscription_period_end: null,
      updated_at: new Date().toISOString(),
    })
    .eq("stripe_customer_id", customerId)
    .select();

  if (error) {
    console.error("Error canceling subscription:", error);
    throw error;
  }

  if (!data || data.length === 0) {
    console.error(`No user found with stripe_customer_id: ${customerId}`);
    throw new Error(`No user profile found for Stripe customer ${customerId}`);
  }

  console.log(`Subscription canceled for customer ${customerId}`);
}

/**
 * Handle successful invoice payment (subscription renewal)
 */
async function handleInvoicePaid(invoice: Stripe.Invoice) {
  const customerId = invoice.customer as string;
  // Get subscription ID - it can be a string or an expanded object
  const subscriptionId = typeof invoice.parent?.subscription_details?.subscription === 'string'
    ? invoice.parent.subscription_details.subscription
    : invoice.parent?.subscription_details?.subscription?.id;

  if (!subscriptionId) {
    // One-time payment, not a subscription
    return;
  }

  // Fetch subscription to get updated period end
  const subscriptionData = await stripe.subscriptions.retrieve(subscriptionId);
  const periodEnd = (subscriptionData as { current_period_end?: number }).current_period_end ||
    Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;

  const { data, error } = await getSupabaseAdmin()
    .from("user_profiles")
    .update({
      subscription_status: "active",
      plan: "premium",
      subscription_period_end: new Date(periodEnd * 1000).toISOString(),
      updated_at: new Date().toISOString(),
    })
    .eq("stripe_customer_id", customerId)
    .select();

  if (error) {
    console.error("Error updating after invoice paid:", error);
    throw error;
  }

  if (!data || data.length === 0) {
    console.error(`No user found with stripe_customer_id: ${customerId}`);
    throw new Error(`No user profile found for Stripe customer ${customerId}`);
  }

  console.log(`Invoice paid for customer ${customerId}`);
}

/**
 * Handle failed invoice payment
 */
async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  const customerId = invoice.customer as string;

  const { data, error } = await getSupabaseAdmin()
    .from("user_profiles")
    .update({
      subscription_status: "past_due",
      updated_at: new Date().toISOString(),
    })
    .eq("stripe_customer_id", customerId)
    .select();

  if (error) {
    console.error("Error updating after payment failed:", error);
    throw error;
  }

  if (!data || data.length === 0) {
    console.error(`No user found with stripe_customer_id: ${customerId}`);
    throw new Error(`No user profile found for Stripe customer ${customerId}`);
  }

  console.log(`Payment failed for customer ${customerId}`);
}
