import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type Stripe from 'stripe';
import { makeStripeInvoice, makeStripeSubscription } from '@/test/fixtures';

const subscriptionsList = vi.fn();
const invoicesList = vi.fn();

vi.mock('@/lib/stripe/server', async (importOriginal) => ({
  isCancellationScheduled: (await importOriginal<typeof import('@/lib/stripe/server')>()).isCancellationScheduled,
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
// Midnight on Sept 16 in America/Phoenix (UTC-7): calendar day 16, with exactly
// 15.0 of the 30 days elapsed. Fixtures are anchored to Phoenix midnights so a
// "Sept 1" trial is one there and not on the evening of Aug 31.
const NOW = Date.UTC(2026, 8, 16, 7, 0, 0);
const nowSec = Math.floor(NOW / 1000);
const sept = (d: number) => Date.UTC(2026, 8, d, 7) / 1000;
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
    // A renewal failed on two annual seats. Still owed, so still in MRR.
    makeStripeSubscription({ id: 'sub_past_due', status: 'past_due', interval: 'year', unitAmount: 6999, quantity: 2 }),
    // Canceling through `cancel_at` alone, flag still false: out of MRR.
    makeStripeSubscription({ id: 'sub_past_due_canceling', status: 'past_due', cancelAt: at(2026, 9, 5) }),
    // Ended 185 days ago: inside the 187-day fetch, outside the 180-day rate window.
    makeStripeSubscription({
      id: 'sub_stale',
      status: 'canceled',
      created: nowSec - 192 * DAY,
      trialStart: nowSec - 192 * DAY,
      trialEnd: nowSec - 185 * DAY,
      canceledAt: nowSec - 185 * DAY,
      endedAt: nowSec - 185 * DAY,
    }),
    // Paid once, long ago, then every renewal failed: still open, so not churned.
    makeStripeSubscription({ id: 'sub_unpaid', status: 'unpaid', email: 'unpaid@example.com' }),
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
  // No trial and created at 0, so outside every cohort window: only churn and growth see it.
  'sub_past_due',
];

const paidInvoices = () => [
  ...PAID.map((id) =>
    makeStripeInvoice({ amountPaid: id.startsWith('sub_y') ? 6999 : 699, subscription: id, created: nowSec - 10 * DAY })
  ),
  // Older than the 187-day window, so only the lifetime fetch returns it.
  makeStripeInvoice({ amountPaid: 699, subscription: 'sub_unpaid', created: nowSec - 400 * DAY }),
];

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
  options: {
    paidThrows?: boolean;
    lifetimeThrows?: boolean;
    cohortThrows?: boolean;
    activeThrows?: boolean;
    pastDueThrows?: boolean;
    canceledThrows?: boolean;
    unpaidThrows?: boolean;
  } = {}
) {
  const subs = allSubscriptions();
  subscriptionsList.mockImplementation((params: { status?: string; created?: { gte?: number } }) => {
    if (params.status === 'active' && options.activeThrows) return rejectingIterable(1);
    if (params.status === 'past_due' && options.pastDueThrows) return rejectingIterable(1);
    if (params.status === 'canceled' && options.canceledThrows) return rejectingIterable(1);
    if (params.status === 'unpaid' && options.unpaidThrows) return rejectingIterable(1);
    if (params.status === 'all') {
      // A mid-iteration rejection, not a synchronous throw — the shape Stripe
      // actually produces when a later page fails.
      if (options.cohortThrows) return rejectingIterable(1);
      const since = params.created?.gte ?? 0;
      return iterate(subs.filter((s) => s.created >= since));
    }
    return iterate(subs.filter((s) => s.status === params.status));
  });
  invoicesList.mockImplementation((params: { created?: { gte?: number } }) => {
    const windowed = params.created !== undefined;
    if (windowed ? options.paidThrows : options.lifetimeThrows) return rejectingIterable(1);
    const since = params.created?.gte ?? 0;
    return iterate(paidInvoices().filter((inv) => inv.created >= since));
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
  });

  it('sums MRR the way Stripe does: active and past_due, less scheduled cancellations', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // Active: five monthly at $6.99 and two annual at $69.99; sub_pending_cancel
    // is out. Past due: two annual seats; sub_past_due_canceling is out.
    // 5 × 6.99 + 4 × 69.99 / 12 = $58.28.
    expect(metrics.mrr).toBe(58.28);
  });

  it('reports MRR as unknown when the active fetch fails', async () => {
    setStripe({ activeThrows: true });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.mrr).toBeNull();
  });

  it('reports MRR as unknown when the past_due fetch fails', async () => {
    setStripe({ pastDueThrows: true });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.mrr).toBeNull();
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

  it("counts last month's trials, their conversions, and the converts still subscribed", async () => {
    // Every matured trial started July 31, so read the page in mid-August.
    vi.setSystemTime(Date.UTC(2026, 7, 16, 7));
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // sub_none never paid; sub_churned and sub_cancelled_annual paid then left;
    // sub_pending_cancel paid but is set to cancel; sub_internal is excluded.
    // That leaves the six active m/y subs.
    expect(metrics.lastMonth).toEqual({
      available: true,
      label: 'July 2026',
      sample: 10,
      converted: 9,
      retained: 6,
      excluded: 1,
    });
  });

  it('counts all-time churn per person from lifetime payments across every status list', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // Twelve people ever paid: the six m/y subs, sub_churned, sub_cancelled_annual,
    // sub_pending_cancel, sub_established, sub_unpaid (paid only before the
    // 187-day window), and test@example.com, who holds sub_sep_done and
    // sub_past_due. sub_internal is excluded. Three have left.
    expect(metrics.lifetimeChurn).toEqual({ available: true, paid: 12, churned: 3 });
  });

  it('rebuilds MRR at the start of last month and this one from subscriptions that paid', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // Aug 1: sub_established ($6.99) and sub_past_due's two annual seats ($11.665).
    // Sept 1 adds the six m/y subs, sub_cancelled_annual (ends Sept 10),
    // sub_pending_cancel (requested Sept 3) and sub_internal (growth does not
    // exclude, like MRR); sub_churned ended Aug 21 and sub_sep_done's trial runs
    // to Sept 8. sub_none, sub_past_due_canceling and sub_stale never paid.
    expect(metrics.mrrGrowth).toEqual({
      available: true,
      label: 'August 2026',
      from: 18.66,
      to: 75.78,
      change: 57.12,
      percent: 306.1,
    });
  });

  it.each([
    ['active', { activeThrows: true }],
    ['past_due', { pastDueThrows: true }],
    ['canceled', { canceledThrows: true }],
    ['lifetime paid invoice', { lifetimeThrows: true }],
  ])('marks churn and growth unavailable when the %s list fails', async (_name, failure) => {
    setStripe(failure);
    const metrics = await getSubscriptionMetrics();
    expect(metrics.lifetimeChurn.available).toBe(false);
    expect(metrics.mrrGrowth.available).toBe(false);
  });

  it('marks only churn unavailable when the unpaid list fails', async () => {
    setStripe({ unpaidThrows: true });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.lifetimeChurn.available).toBe(false);
    expect(metrics.mrrGrowth.available).toBe(true);
  });

  it('keeps churn and growth available when only the 187-day payments fail', async () => {
    setStripe({ paidThrows: true });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.lifetimeChurn.available).toBe(true);
    expect(metrics.mrrGrowth.available).toBe(true);
  });

  it('counts the month before last the same way', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // Read on Sept 16, two months back is July, when every matured trial started.
    expect(metrics.twoMonthsAgo).toEqual({
      available: true,
      label: 'July 2026',
      sample: 10,
      converted: 9,
      retained: 6,
      excluded: 1,
    });
  });

  it('counts how many of the 180-day converts are still subscribed', async () => {
    setStripe();
    const metrics = await getSubscriptionMetrics();
    // Ten converts ended their trial in the window. sub_churned and
    // sub_cancelled_annual have left and sub_pending_cancel is set to cancel.
    expect(metrics.conversion.converted).toBe(10);
    expect(metrics.conversion.retained).toBe(7);
  });

  it('marks last month unavailable when the cohort fetch fails', async () => {
    setStripe({ cohortThrows: true });
    const metrics = await getSubscriptionMetrics();
    expect(metrics.lastMonth.available).toBe(false);
    expect(metrics.lastMonth.sample).toBe(0);
    expect(metrics.twoMonthsAgo.available).toBe(false);
    expect(metrics.twoMonthsAgo.sample).toBe(0);
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
    const paidCall = invoicesList.mock.calls.map((c) => c[0]).find((p) => p.status === 'paid' && p.created);
    expect(cohortCall.created.gte).toBe(nowSec - 187 * DAY);
    expect(paidCall.created.gte).toBe(nowSec - 187 * DAY);
  });
});

/** Narrows the metrics object to the projection under test. */
function metrics_of(metrics: Awaited<ReturnType<typeof getSubscriptionMetrics>>) {
  return metrics.monthProjection;
}
