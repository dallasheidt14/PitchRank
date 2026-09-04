import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type Stripe from 'stripe';
import { makeStripeInvoice, makeStripeSubscription } from '@/test/fixtures';

const subscriptionsList = vi.fn();
const invoicesList = vi.fn();

vi.mock('@/lib/stripe/server', () => ({
  stripe: {
    subscriptions: { list: (params: unknown) => subscriptionsList(params) },
    invoices: { list: (params: unknown) => invoicesList(params) },
  },
}));

// Report-card metrics degrade on their own; failing the client keeps this suite
// about the Stripe assembly path.
vi.mock('@/lib/supabase/service', () => ({
  createServiceSupabase: () => {
    throw new Error('supabase disabled in this suite');
  },
}));

import { getSubscriptionMetrics } from '../subscription-metrics';

const DAY = 86_400;
const NOW = Date.UTC(2026, 8, 15, 12, 0, 0); // day 15 of a 30-day September
const nowSec = Math.floor(NOW / 1000);
const sept = (d: number) => Date.UTC(2026, 8, d) / 1000;
const at = (y: number, m: number, d: number) => Date.UTC(y, m, d) / 1000;

/** Trial that ended 40 days ago — matured, so it reaches the churn cohort. */
const matured = (
  id: string,
  status: Stripe.Subscription.Status,
  interval: 'month' | 'year',
  over: Parameters<typeof makeStripeSubscription>[0] = {}
) =>
  makeStripeSubscription({
    id,
    status,
    interval,
    unitAmount: interval === 'year' ? 6999 : 699,
    created: nowSec - 47 * DAY,
    trialStart: nowSec - 47 * DAY,
    trialEnd: nowSec - 40 * DAY,
    currentPeriodEnd: interval === 'year' ? at(2027, 3, 5) : at(2026, 9, 5),
    email: `${id}@example.com`,
    ...over,
  });

/**
 * A base with two September trials — one already resolved, one still running —
 * so the projection has something to report. Without them every projected value
 * is zero and a mis-wired input cannot be told from a correct one.
 */
function allSubscriptions() {
  return [
    matured('sub_m1', 'active', 'month'),
    matured('sub_m2', 'active', 'month'),
    matured('sub_m3', 'active', 'month'),
    matured('sub_m4', 'active', 'month'),
    matured('sub_y1', 'active', 'year'),
    matured('sub_y2', 'active', 'year'),
    // Converted, then cancelled 14 days into the paid month — the one measured churn event.
    matured('sub_churned', 'canceled', 'month', { endedAt: nowSec - 26 * DAY }),
    // Trial ended, never charged: in the conversion denominator, not the numerator.
    matured('sub_none', 'canceled', 'month'),
    // Annual, cancelled, service ended THIS month. Its period end sits inside
    // September, so feeding countAnnualRenewals the cohort instead of the active
    // list would wrongly count it as a renewal still ahead.
    matured('sub_cancelled_annual', 'canceled', 'year', { endedAt: sept(10), currentPeriodEnd: sept(20) }),
    // September trial that has already ended and converted.
    makeStripeSubscription({
      id: 'sub_sep_done',
      status: 'active',
      created: sept(1),
      trialStart: sept(1),
      trialEnd: sept(8),
    }),
    // September trial still running.
    makeStripeSubscription({
      id: 'sub_sep_live',
      status: 'trialing',
      created: sept(12),
      trialStart: sept(12),
      trialEnd: sept(19),
    }),
    // An internal account on the annual plan: activated and matured, so it would
    // reach every rate and the ARPU cohort if the exclusion were not applied.
    matured('sub_internal', 'canceled', 'year', { email: 'internal@example.com' }),
    // Created long before the cohort window and cancelled this month. An
    // established subscriber like this is absent from the active base the
    // projected half is charged against, so if observed churn also skipped them
    // the loss would be counted nowhere.
    makeStripeSubscription({
      id: 'sub_established',
      status: 'canceled',
      created: nowSec - 300 * DAY,
      trialStart: nowSec - 300 * DAY,
      trialEnd: nowSec - 293 * DAY,
      endedAt: sept(6),
      email: 'established@example.com',
    }),
    // Active, but cancellation already requested for a period ending next year.
    // Service has not stopped, so it is not this month's loss.
    matured('sub_pending_cancel', 'active', 'year', {
      canceledAt: sept(3),
      endedAt: null,
      cancelAtPeriodEnd: true,
      currentPeriodEnd: at(2027, 5, 1),
    }),
    // Ended 185 days ago: inside the 187-day fetch, outside the 180-day rate window.
    makeStripeSubscription({
      id: 'sub_stale',
      status: 'canceled',
      created: nowSec - 192 * DAY,
      trialStart: nowSec - 192 * DAY,
      trialEnd: nowSec - 185 * DAY,
    }),
  ];
}

const PAID = [
  'sub_m1',
  'sub_m2',
  'sub_m3',
  'sub_m4',
  'sub_y1',
  'sub_y2',
  'sub_churned',
  'sub_cancelled_annual',
  'sub_sep_done',
  'sub_internal',
  'sub_established',
  'sub_pending_cancel',
];

const paidInvoices = () =>
  PAID.map((id) => makeStripeInvoice({ amountPaid: id.startsWith('sub_y') ? 6999 : 699, subscription: id }));

/** An async iterable whose Nth pull rejects, the way a real page fetch fails. */
function rejectingIterable(failOnPull: number): AsyncIterable<never> {
  return {
    [Symbol.asyncIterator]() {
      let pulls = 0;
      return {
        next: async () => {
          pulls += 1;
          if (pulls >= failOnPull) throw new Error('stripe page fetch failed');
          return { value: undefined as never, done: false };
        },
      } as AsyncIterator<never>;
    },
  };
}

function iterate<T>(items: T[]): AsyncIterable<T> {
  return {
    async *[Symbol.asyncIterator]() {
      yield* items;
    },
  };
}

function setStripe(
  options: { paidThrows?: boolean; openThrows?: boolean; cohortThrows?: boolean; openInvoices?: Stripe.Invoice[] } = {}
) {
  const subs = allSubscriptions();
  subscriptionsList.mockImplementation((params: { status?: string; created?: { gte?: number } }) => {
    if (params.status === 'all') {
      // A mid-iteration rejection, not a synchronous throw — the shape Stripe
      // actually produces when a later page fails.
      if (options.cohortThrows) return rejectingIterable(1);
      const since = params.created?.gte ?? 0;
      return iterate(subs.filter((s) => s.created >= since));
    }
    return iterate(subs.filter((s) => s.status === params.status));
  });
  invoicesList.mockImplementation((params: { status?: string }) => {
    if (params.status === 'paid') {
      return options.paidThrows ? rejectingIterable(1) : iterate(paidInvoices());
    }
    return options.openThrows ? rejectingIterable(1) : iterate(options.openInvoices ?? []);
  });
}

beforeEach(() => {
  vi.stubEnv('ADMIN_DASHBOARD_EXCLUDED_EMAILS', 'internal@example.com');
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  subscriptionsList.mockReset();
  invoicesList.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe('getSubscriptionMetrics', () => {
  it('routes each status list to the builder that wants it', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    expect(metrics.activePaid).toEqual({ total: 8, monthly: 5, annual: 3 });
    expect(metrics.trials.total).toBe(1); // only the trialing subscription
    expect(metrics.pastDue.total).toBe(0);
  });

  it('measures conversion from the paid invoices it fetched', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // Eleven trials ended inside the window; ten of them were charged. The
    // internal account is excluded, and sub_established predates the cohort.
    expect(metrics.conversion.sample).toBe(11);
    expect(metrics.conversion.converted).toBe(10);
    expect(metrics.conversion.percent).toBe(91);
    expect(metrics.monthProjection.conversion.isFallback).toBe(false);
  });

  it('measures churn rather than falling back, when the cohort is big enough', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    expect(metrics.monthProjection.churn.isFallback).toBe(false);
    expect(metrics.monthProjection.churn.sample).toBe(9);
    expect(metrics.monthProjection.churn.observed).toBe(1);
  });

  it('assembles the projection from the September trials', async () => {
    setStripe();
    const { trials, ...projection } = metrics_of(await getSubscriptionMetrics());
    expect(trials.trialsToDate).toBe(2);
    expect(trials.landedConverted).toBe(1); // sub_sep_done ended and paid
    expect(trials.landingUnresolved).toBeCloseTo(1 + (2 / 15) * 8, 5);
    expect(projection.grossNewSubs).toBeGreaterThan(1);
    expect(Number.isFinite(projection.netMrr)).toBe(true);
  });

  it('counts cancellations that already happened this month, cohort or not', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // sub_cancelled_annual, plus sub_established which predates the cohort window
    // entirely. sub_pending_cancel is still being served and must not count.
    expect(metrics.monthProjection.observedChurn).toBe(2);
  });

  it('takes annual renewals from the active base, not the whole cohort', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // sub_cancelled_annual has a September period end but is already cancelled;
    // both live annual subscriptions renew in 2027.
    expect(metrics.monthProjection.annualRenewalsAhead).toBe(0);
  });

  it('derives ARPU from the plans converters bought, less internal accounts', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // Ten external converters in the cohort: six monthly at $6.99 and four
    // annual at $5.8325 monthly-equivalent, i.e. $65.27 across ten.
    expect(metrics.monthProjection.arpu).toBeCloseTo(65.27 / 10, 4);
  });

  it('keeps internal accounts out of every rate as well', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    expect(metrics.conversion.excluded).toBe(1);
    expect(metrics.monthProjection.churn.excluded).toBe(1);
  });

  it('charges the remaining-month churn risk to monthly subscribers only', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    const { churn, observedChurn, churnedSubs } = metrics.monthProjection;
    // 2 already cancelled, plus the 5 monthly actives at half a month remaining.
    // Charging all 8 actives instead would give 2.4444.
    expect(churnedSubs).toBeCloseTo(observedChurn + 5 * churn.rate * 0.5, 6);
    expect(churnedSubs).toBeCloseTo(2.2778, 4);
  });

  it('falls back rather than reporting nobody paid when the invoice fetch fails', async () => {
    setStripe({ paidThrows: true });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.monthProjection.available).toBe(false);
    expect(metrics.monthProjection.conversion.isFallback).toBe(true);
    expect(metrics.monthProjection.conversion.rate).toBeGreaterThan(0);
    expect(metrics.conversion.percent).toBeNull();
    expect(metrics.errors.join(' ')).toContain('paid invoices');
  });

  it('marks the projection unavailable when the cohort fetch fails', async () => {
    setStripe({ cohortThrows: true });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.monthProjection.available).toBe(false);
    expect(metrics.monthProjection.trials.trialsToDate).toBe(0);
    expect(metrics.errors.join(' ')).toContain('conversion cohort');
  });

  it('says unpaid invoices are unknown when their fetch fails, not that none exist', async () => {
    setStripe({ openThrows: true });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.unpaidInvoices.available).toBe(false);
    expect(metrics.unpaidInvoices.list).toEqual([]);
    expect(metrics.errors.join(' ')).toContain('open invoices');
  });

  it('reports unpaid invoices as known when the fetch succeeds', async () => {
    setStripe({
      openInvoices: [
        makeStripeInvoice({
          id: 'in_open',
          amountPaid: 0,
          amountDue: 699,
          amountRemaining: 699,
          attempted: true,
          attemptCount: 3,
          nextPaymentAttempt: null,
          subscription: 'sub_m1',
        }),
      ],
    });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.unpaidInvoices.available).toBe(true);
    expect(metrics.unpaidInvoices.total).toBe(1);
    expect(metrics.unpaidInvoices.outstanding).toBe(6.99);
    expect(metrics.unpaidInvoices.noRetryScheduled).toBe(1);
  });

  it('measures only the trials that ended inside the window it reports', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // sub_stale ended 185 days ago and is fetched, but must not reach a rate
    // labelled "last 180 days".
    expect(metrics.conversion.windowDays).toBe(180);
    expect(metrics.conversion.sample).toBe(11);
  });

  it('expands the customer, which the internal-email exclusion depends on', async () => {
    setStripe();
    await getSubscriptionMetrics();
    for (const [params] of subscriptionsList.mock.calls) {
      expect(params.expand).toEqual(['data.customer']);
    }
  });

  it('reaches back past the rate window so its oldest trials are fetched', async () => {
    setStripe();
    await getSubscriptionMetrics();
    const cohortCall = subscriptionsList.mock.calls.map((c) => c[0]).find((p) => p.status === 'all');
    const paidCall = invoicesList.mock.calls.map((c) => c[0]).find((p) => p.status === 'paid');
    expect(cohortCall.created.gte).toBe(nowSec - 187 * DAY);
    expect(paidCall.created.gte).toBe(nowSec - 187 * DAY);
  });
});

/** Narrows the metrics object to the projection under test. */
function metrics_of(metrics: Awaited<ReturnType<typeof getSubscriptionMetrics>>) {
  return metrics.monthProjection;
}
