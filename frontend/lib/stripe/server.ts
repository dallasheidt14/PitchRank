import Stripe from 'stripe';
import type { SupabaseClient } from '@supabase/supabase-js';

// Lazy-load Stripe client to avoid build-time initialization errors
let stripeClient: Stripe | null = null;

/**
 * Get Stripe client for server-side operations
 * Lazily initialized to avoid build-time errors when env vars aren't set
 * Use in: Route Handlers, Server Actions, Webhooks
 */
function getStripeClient(): Stripe {
  if (!stripeClient) {
    if (!process.env.STRIPE_SECRET_KEY) {
      throw new Error('Missing STRIPE_SECRET_KEY environment variable');
    }
    stripeClient = new Stripe(process.env.STRIPE_SECRET_KEY, {
      apiVersion: '2026-03-25.dahlia',
      typescript: true,
    });
  }
  return stripeClient;
}

/**
 * Stripe client for server-side operations
 * This is a proxy that lazy-loads the actual client
 */
export const stripe = new Proxy({} as Stripe, {
  get(_, prop) {
    const client = getStripeClient();
    const value = client[prop as keyof Stripe];
    // Bind methods to the client instance
    if (typeof value === 'function') {
      return value.bind(client);
    }
    return value;
  },
});

/**
 * Get Stripe Price IDs for PitchRank Premium
 * Lazily loaded to read env vars at runtime, not build time
 */
export function getStripePriceIds() {
  return {
    MONTHLY: process.env.STRIPE_PRICE_MONTHLY || process.env.NEXT_PUBLIC_STRIPE_PRICE_MONTHLY || '',
    YEARLY: process.env.STRIPE_PRICE_YEARLY || process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY || '',
  };
}

/**
 * Stripe webhook event types we handle
 */
export const WEBHOOK_EVENTS = {
  CHECKOUT_COMPLETED: 'checkout.session.completed',
  SUBSCRIPTION_UPDATED: 'customer.subscription.updated',
  SUBSCRIPTION_DELETED: 'customer.subscription.deleted',
  INVOICE_PAID: 'invoice.paid',
  INVOICE_PAYMENT_FAILED: 'invoice.payment_failed',
} as const;

/**
 * Extract subscription period end as an ISO string, handling both item-level
 * (dahlia+) and top-level (clover) `current_period_end` field locations.
 */
export function extractPeriodEnd(subscription: Stripe.Subscription): string {
  const ts =
    subscription.items.data[0]?.current_period_end ??
    ((subscription as unknown as Record<string, unknown>).current_period_end as number | undefined) ??
    Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60;
  return new Date(ts * 1000).toISOString();
}

/**
 * Map a Stripe subscription status to our plan tier.
 * Keep premium access during past_due (Stripe will retry payment).
 */
export function mapStatusToPlan(status: Stripe.Subscription.Status): 'premium' | 'free' {
  return status === 'active' || status === 'trialing' || status === 'past_due' ? 'premium' : 'free';
}

/**
 * Update a user profile by stripe_customer_id, verify the row exists, and
 * return the updated row(s). Throws on DB error or missing user.
 *
 * Designed for the webhook admin client — sync/route.ts updates by user.id
 * with a user-scoped client and should not use this helper.
 */
export async function updateUserProfile(
  supabaseAdmin: SupabaseClient,
  customerId: string,
  updates: Record<string, unknown>
): Promise<unknown[]> {
  const { data, error } = await supabaseAdmin
    .from('user_profiles')
    .update({ ...updates, updated_at: new Date().toISOString() })
    .eq('stripe_customer_id', customerId)
    .select();

  if (error) {
    console.error('Error updating profile:', error);
    throw error;
  }

  if (!data || data.length === 0) {
    console.error(`No user found with stripe_customer_id: ${customerId}`);
    throw new Error(`No user profile found for Stripe customer ${customerId}`);
  }

  return data;
}
