import 'server-only';
import type Stripe from 'stripe';

export const SECONDS_PER_DAY = 86_400;

/**
 * Cohort size below which a measured rate is reported as its fallback instead.
 *
 * Shared rather than per-module because the dashboard renders rates from both
 * `subscription-metrics` and `month-projection` on one screen: were the two to
 * disagree, the same cohort would show a measured percentage in one card and a
 * fallback badge in the next.
 */
export const MIN_COHORT_SAMPLE = 5;

/** Trial length granted at checkout (`frontend/app/api/stripe/checkout/route.ts`). */
export const TRIAL_DAYS = 7;

export function getCustomerEmail(sub: Stripe.Subscription): string {
  const customer = sub.customer;
  if (typeof customer === 'string') return customer;
  if ('deleted' in customer && customer.deleted) return '(deleted customer)';
  return customer.email ?? '(no email)';
}
