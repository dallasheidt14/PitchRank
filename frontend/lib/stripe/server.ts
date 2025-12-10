import Stripe from "stripe";

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
      throw new Error("Missing STRIPE_SECRET_KEY environment variable");
    }
    stripeClient = new Stripe(process.env.STRIPE_SECRET_KEY, {
      apiVersion: "2025-11-17.clover",
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
    if (typeof value === "function") {
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
    MONTHLY: process.env.STRIPE_PRICE_MONTHLY || process.env.NEXT_PUBLIC_STRIPE_PRICE_MONTHLY || "",
    YEARLY: process.env.STRIPE_PRICE_YEARLY || process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY || "",
  };
}

// Keep for backwards compatibility but mark as deprecated
export const STRIPE_PRICE_IDS = {
  get MONTHLY() {
    return getStripePriceIds().MONTHLY;
  },
  get YEARLY() {
    return getStripePriceIds().YEARLY;
  },
} as const;

/**
 * Stripe webhook event types we handle
 */
export const WEBHOOK_EVENTS = {
  CHECKOUT_COMPLETED: "checkout.session.completed",
  SUBSCRIPTION_UPDATED: "customer.subscription.updated",
  SUBSCRIPTION_DELETED: "customer.subscription.deleted",
  INVOICE_PAID: "invoice.paid",
  INVOICE_PAYMENT_FAILED: "invoice.payment_failed",
} as const;
