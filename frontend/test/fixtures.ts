import type Stripe from 'stripe';
import type { RankingRow } from '@/types/RankingRow';

/** Defaults describe an established, fully ranked team; override per test. */
export function makeRankingRow(overrides: Partial<RankingRow> = {}): RankingRow {
  return {
    team_id_master: '11111111-1111-1111-1111-111111111111',
    team_name: 'Test FC 2014',
    club_name: 'Test FC',
    league: null,
    distinction: null,
    state: 'AZ',
    age: 12,
    gender: 'M',
    power_score_final: 0.5,
    sos_norm: 0.5,
    offense_norm: 0.5,
    defense_norm: 0.5,
    rank_in_cohort_final: 100,
    wins: 5,
    losses: 2,
    draws: 1,
    games_played: 8,
    total_games_played: 12,
    total_wins: 5,
    total_losses: 2,
    total_draws: 1,
    win_percentage: 62.5,
    status: 'Active',
    rank_change_7d: 40,
    rank_change_30d: 40,
    last_calculated: '2026-08-24T12:00:00Z',
    last_game: '2026-08-22T00:00:00Z',
    ...overrides,
  };
}

/**
 * Stripe subscription double, returned already typed so callers need no cast.
 *
 * `status` keeps Stripe's union rather than a bare string: the churn and
 * activity branches compare against the exact literal `'canceled'`, so a
 * misspelling would otherwise typecheck and produce a fixture that silently
 * matches nothing.
 */
export function makeStripeSubscription(
  overrides: {
    id?: string;
    status?: Stripe.Subscription.Status;
    interval?: 'month' | 'year';
    unitAmount?: number;
    quantity?: number;
    trialStart?: number | null;
    trialEnd?: number | null;
    canceledAt?: number | null;
    endedAt?: number | null;
    currentPeriodEnd?: number;
    email?: string;
    customer?: unknown;
    cancelAtPeriodEnd?: boolean;
    created?: number;
  } = {}
): Stripe.Subscription {
  const {
    id = `sub_${Math.random().toString(36).slice(2)}`,
    status = 'active',
    interval = 'month',
    unitAmount = 699,
    quantity = 1,
    trialStart = null,
    trialEnd = null,
    canceledAt = null,
    endedAt = null,
    currentPeriodEnd = 0,
    email = 'test@example.com',
    customer,
    cancelAtPeriodEnd = false,
    created = 0,
  } = overrides;
  return {
    id,
    status,
    created,
    trial_start: trialStart,
    trial_end: trialEnd,
    canceled_at: canceledAt,
    ended_at: endedAt,
    cancel_at_period_end: cancelAtPeriodEnd,
    customer: customer ?? { id: 'cus_x', email, deleted: false },
    items: {
      data: [
        {
          id: 'si_x',
          quantity,
          current_period_end: currentPeriodEnd,
          price: { unit_amount: unitAmount, recurring: { interval } },
        },
      ],
    },
  } as unknown as Stripe.Subscription;
}

/**
 * Stripe invoice double shaped for the pinned API version: the generating
 * subscription hangs off `parent.subscription_details`, not the top-level
 * `subscription` field removed in 2025-03-31.basil.
 *
 * The money defaults differ from one another on purpose. When `total`,
 * `amount_due` and `amount_remaining` all default to the same figure, a
 * predicate that reads the wrong one still passes every test.
 */
export function makeStripeInvoice(
  overrides: {
    id?: string;
    amountPaid?: number;
    amountDue?: number;
    amountRemaining?: number;
    total?: number;
    discounts?: string[];
    billingReason?: Stripe.Invoice.BillingReason;
    subscription?: string | null;
    lineSubscription?: string | null;
    attempted?: boolean;
    attemptCount?: number;
    nextPaymentAttempt?: number | null;
    email?: string | null;
    created?: number;
  } = {}
): Stripe.Invoice {
  const {
    id = `in_${Math.random().toString(36).slice(2)}`,
    amountDue = 699,
    amountPaid = 699,
    amountRemaining = amountDue - amountPaid,
    total = amountDue,
    discounts = [],
    billingReason = 'subscription_cycle',
    subscription = 'sub_default',
    lineSubscription = null,
    attempted = true,
    attemptCount = 0,
    nextPaymentAttempt = null,
    email = 'test@example.com',
    created = 1_700_000_000,
  } = overrides;
  return {
    id,
    amount_paid: amountPaid,
    amount_due: amountDue,
    amount_remaining: amountRemaining,
    total,
    discounts,
    billing_reason: billingReason,
    attempted,
    attempt_count: attemptCount,
    next_payment_attempt: nextPaymentAttempt,
    customer_email: email,
    created,
    parent: subscription ? { subscription_details: { subscription } } : null,
    lines: {
      data: lineSubscription ? [{ parent: { subscription_item_details: { subscription: lineSubscription } } }] : [],
    },
  } as unknown as Stripe.Invoice;
}
