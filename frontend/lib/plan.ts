/**
 * Plan and subscription-status rules shared by client and server code. Kept free of any directive
 * so route handlers can import it: they compile in Next's RSC layer, where every export of a
 * `'use client'` module is a stub that throws when called.
 */

/** Statuses that keep premium: the subscriber is paying, trialing, or Stripe is still retrying. */
export const LIVE_SUBSCRIPTION_STATUSES = ['active', 'trialing', 'past_due'] as const;

/** What a standard checkout refuses: past_due may re-subscribe, which is how such an account fixes its billing. */
export const STANDARD_REFUSED_STATUSES = ['active', 'trialing'] as const;

export type LiveSubscriptionStatus = (typeof LIVE_SUBSCRIPTION_STATUSES)[number];

export function isStandardRefusedStatus(status: string | null | undefined): boolean {
  return (STANDARD_REFUSED_STATUSES as readonly (string | null | undefined)[]).includes(status);
}

/**
 * Whether a `user_profiles.plan` value carries premium access. Paying, trialing, past_due and
 * cancel-scheduled subscribers all store `premium`, as do comped accounts.
 */
export function hasPremiumPlan(plan: string | null | undefined): boolean {
  return plan === 'premium' || plan === 'admin';
}

export function hasAdminPlan(plan: string | null | undefined): boolean {
  return plan === 'admin';
}
