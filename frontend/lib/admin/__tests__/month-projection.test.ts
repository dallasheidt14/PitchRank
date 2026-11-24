import { describe, it, expect } from 'vitest';
import type Stripe from 'stripe';
import { makeStripeInvoice as invoice, makeStripeSubscription as sub } from '@/test/fixtures';
import { SECONDS_PER_DAY } from '../constants';

import {
  buildCashForecast,
  buildMonthProjection,
  collectPaidSubscriptionIds,
  computeLifetimeChurn,
  computeLifetimeConversionByPlan,
  computeMonthCohort,
  computePaidChurnRate,
  computeRenewalCollectionRate,
  computeRetention,
  computeTrialConversionRate,
  computeTrialProjection,
  countAnnualRenewals,
  countObservedChurn,
  countTrialsByMonth,
  FALLBACK_CHURN_RATE,
  FALLBACK_CONVERSION_RATE,
  FALLBACK_RENEWAL_RATE,
  netOfStripeFee,
  type CohortWindow,
  type RateEstimate,
} from '../month-projection';

const NONE = new Set<string>();
const window = (over: Partial<CohortWindow> & Pick<CohortWindow, 'subs' | 'now'>): CohortWindow => ({
  paidSubIds: NONE,
  windowStart: over.now - 180 * SECONDS_PER_DAY,
  excludedEmails: NONE,
  ...over,
});

describe('collectPaidSubscriptionIds', () => {
  it('ignores the $0 invoice that opens a trial', () => {
    const invoices = [
      invoice({
        amountPaid: 0,
        amountDue: 0,
        total: 0,
        billingReason: 'subscription_create',
        subscription: 'sub_trial',
      }),
      invoice({ amountPaid: 699, subscription: 'sub_paid' }),
    ];
    expect(collectPaidSubscriptionIds(invoices)).toEqual(new Set(['sub_paid']));
  });

  it('counts a fully discounted renewal, which Stripe marks paid at $0', () => {
    const invoices = [
      invoice({
        amountPaid: 0,
        amountDue: 0,
        total: 0,
        discounts: ['di_freebie'],
        billingReason: 'subscription_cycle',
        subscription: 'sub_coupon',
      }),
    ];
    expect(collectPaidSubscriptionIds(invoices)).toEqual(new Set(['sub_coupon']));
  });

  it('does not count a coupon carried onto the trial-opening invoice', () => {
    // Stripe copies a subscription-level discount onto every invoice it makes,
    // including the $0 one that opens the trial. Counting that would book the
    // trial as converted on day one.
    const invoices = [
      invoice({
        amountPaid: 0,
        amountDue: 0,
        total: 0,
        discounts: ['di_freebie'],
        billingReason: 'subscription_create',
        subscription: 'sub_trialing',
      }),
    ];
    expect(collectPaidSubscriptionIds(invoices)).toEqual(new Set());
  });

  it('counts a paid first invoice for a customer who got no trial', () => {
    const invoices = [
      invoice({ amountPaid: 699, billingReason: 'subscription_create', subscription: 'sub_returning' }),
    ];
    expect(collectPaidSubscriptionIds(invoices)).toEqual(new Set(['sub_returning']));
  });

  it('does not count a part-discounted invoice that was never paid', () => {
    const invoices = [
      invoice({ amountPaid: 0, amountDue: 350, amountRemaining: 350, total: 350, discounts: ['di_half'] }),
    ];
    expect(collectPaidSubscriptionIds(invoices)).toEqual(new Set());
  });

  it('reads the subscription from the invoice parent', () => {
    expect(collectPaidSubscriptionIds([invoice({ subscription: 'sub_parent' })])).toEqual(new Set(['sub_parent']));
  });

  it('falls back to a line item when the parent carries no subscription', () => {
    const invoices = [invoice({ subscription: null, lineSubscription: 'sub_line' })];
    expect(collectPaidSubscriptionIds(invoices)).toEqual(new Set(['sub_line']));
  });

  it('prefers the parent over the line item', () => {
    const invoices = [invoice({ subscription: 'sub_parent', lineSubscription: 'sub_line' })];
    expect(collectPaidSubscriptionIds(invoices)).toEqual(new Set(['sub_parent']));
  });

  it('deduplicates renewals of one subscription', () => {
    const invoices = [invoice({ subscription: 'sub_a' }), invoice({ subscription: 'sub_a' })];
    expect(collectPaidSubscriptionIds(invoices).size).toBe(1);
  });

  it('returns an empty set for no invoices', () => {
    expect(collectPaidSubscriptionIds([])).toEqual(new Set());
  });
});

describe('computeTrialConversionRate', () => {
  const now = 1_700_000_000;
  const day = SECONDS_PER_DAY;

  it('scores on activation, whatever the subscription status is now', () => {
    const subs = [
      sub({ id: 'sub_1', status: 'active', trialEnd: now - 5 * day }),
      sub({ id: 'sub_2', status: 'canceled', trialEnd: now - 5 * day }),
      sub({ id: 'sub_3', status: 'canceled', trialEnd: now - 5 * day }),
      sub({ id: 'sub_4', status: 'past_due', trialEnd: now - 5 * day }),
      sub({ id: 'sub_5', status: 'past_due', trialEnd: now - 5 * day }),
    ];
    // sub_2 paid then cancelled — still converted. sub_5 was declined — not converted.
    const result = computeTrialConversionRate(window({ subs, now, paidSubIds: new Set(['sub_1', 'sub_2', 'sub_4']) }));
    expect(result.sample).toBe(5);
    expect(result.observed).toBe(3);
    expect(result.rate).toBeCloseTo(0.6);
    expect(result.isFallback).toBe(false);
  });

  it('ignores trials still in flight', () => {
    const subs = Array.from({ length: 6 }, (_, i) => sub({ id: `sub_${i}`, trialEnd: now + 2 * day }));
    expect(computeTrialConversionRate(window({ subs, now })).sample).toBe(0);
  });

  it('ignores trials that ended before the window opened', () => {
    const subs = Array.from({ length: 6 }, (_, i) => sub({ id: `sub_${i}`, trialEnd: now - 200 * day }));
    expect(computeTrialConversionRate(window({ subs, now })).sample).toBe(0);
  });

  it('removes excluded emails from both halves and counts them separately', () => {
    const subs = [
      ...Array.from({ length: 5 }, (_, i) =>
        sub({ id: `sub_${i}`, email: `user${i}@example.com`, trialEnd: now - 5 * day })
      ),
      sub({ id: 'sub_owner', email: 'Owner@Example.com', trialEnd: now - 5 * day }),
    ];
    const result = computeTrialConversionRate(
      window({
        subs,
        now,
        paidSubIds: new Set(['sub_0', 'sub_1', 'sub_2', 'sub_3', 'sub_owner']),
        excludedEmails: new Set(['owner@example.com']),
      })
    );
    expect(result.sample).toBe(5);
    expect(result.observed).toBe(4);
    expect(result.excluded).toBe(1);
  });

  it('falls back below the minimum sample', () => {
    const subs = [sub({ id: 'sub_1', trialEnd: now - day })];
    const result = computeTrialConversionRate(window({ subs, now, paidSubIds: new Set(['sub_1']) }));
    expect(result.rate).toBe(FALLBACK_CONVERSION_RATE);
    expect(result.isFallback).toBe(true);
  });
});

describe('computeMonthCohort', () => {
  // Phoenix is UTC-7 all year, so its midnight on the 1st is 07:00 UTC.
  const phoenix = (y: number, m: number, d: number, h = 0) => Date.UTC(y, m - 1, d, h + 7) / 1000;
  const now = new Date(phoenix(2026, 9, 16) * 1000);
  const august = phoenix(2026, 8, 15);
  const trial = (start: number) => ({ trialStart: start, trialEnd: start + 7 * SECONDS_PER_DAY });

  // Apart from the baseline rows, each row isolates one condition, so dropping that condition changes a count.
  const subs = [
    sub({ id: 'kept', status: 'active', ...trial(august) }),
    sub({ id: 'kept_past_due', status: 'past_due', ...trial(august) }),
    sub({ id: 'first_instant', status: 'active', ...trial(phoenix(2026, 8, 1)) }),
    // Started in August, ended in September: counted, because the cohort is by start.
    sub({ id: 'ends_next_month', status: 'active', ...trial(phoenix(2026, 8, 28)) }),
    sub({ id: 'canceled', status: 'canceled', ...trial(august) }),
    sub({ id: 'set_to_cancel', status: 'active', ...trial(august), cancelAtPeriodEnd: true }),
    sub({ id: 'cancel_at', status: 'past_due', ...trial(august), cancelAt: phoenix(2026, 10, 15) }),
    sub({ id: 'never_paid', status: 'active', ...trial(august) }),
    sub({ id: 'internal', status: 'active', ...trial(august), email: 'staff@example.com' }),
    // Started in July, ended in August: not counted.
    sub({ id: 'july', status: 'active', ...trial(phoenix(2026, 8, 1) - 1) }),
    sub({ id: 'september', status: 'active', ...trial(phoenix(2026, 9, 1)) }),
  ];
  const paid = new Set(subs.map((s) => s.id).filter((id) => id !== 'never_paid'));
  const excluded = new Set(['staff@example.com']);

  it('counts trials started in the previous Phoenix month, their conversions, and the converts still subscribed', () => {
    expect(computeMonthCohort(subs, paid, now, 1, excluded)).toEqual({
      label: 'August 2026',
      sample: 8,
      converted: 7,
      retained: 4,
      excluded: 1,
    });
  });

  it('reaches back into the previous year in January', () => {
    const december = [sub({ id: 'dec', status: 'active', trialStart: phoenix(2026, 12, 15) })];
    const result = computeMonthCohort(december, new Set(['dec']), new Date(phoenix(2027, 1, 15) * 1000), 1, NONE);
    expect(result).toEqual({ label: 'December 2026', sample: 1, converted: 1, retained: 1, excluded: 0 });
  });
});

describe('computeMonthCohort two months back', () => {
  const phoenix = (y: number, m: number, d: number) => Date.UTC(y, m - 1, d, 7) / 1000;
  const trial = (id: string, start: number) => sub({ id, status: 'active', trialStart: start });

  it('steps back two whole Phoenix months, across a year boundary', () => {
    const subs = [
      trial('dec', phoenix(2026, 12, 1)),
      trial('nov', phoenix(2026, 11, 30)),
      trial('jan', phoenix(2027, 1, 1)),
    ];
    const result = computeMonthCohort(subs, new Set(['dec']), new Date(phoenix(2027, 2, 10) * 1000), 2, NONE);
    expect(result).toEqual({ label: 'December 2026', sample: 1, converted: 1, retained: 1, excluded: 0 });
  });
});

describe('countTrialsByMonth', () => {
  const phoenix = (y: number, m: number, d: number, h = 0) => Date.UTC(y, m - 1, d, h + 7) / 1000;
  const trial = (id: string, start: number | null, over: Parameters<typeof sub>[0] = {}) =>
    sub({ id, status: 'canceled', trialStart: start, ...over });

  it('counts trials started in each Phoenix month from June through the current one, oldest first', () => {
    const subs = [
      trial('may', phoenix(2026, 6, 1) - 1),
      trial('june_first_instant', phoenix(2026, 6, 1)),
      // 11pm on June 30 in Phoenix is already July 1 in UTC.
      trial('june_last_evening', phoenix(2026, 6, 30, 23)),
      trial('august', phoenix(2026, 8, 12), { status: 'active' }),
      trial('august_internal', phoenix(2026, 8, 12), { email: 'staff@example.com' }),
      trial('no_trial', null, { status: 'active', created: phoenix(2026, 8, 12) }),
      trial('september', phoenix(2026, 9, 3), { status: 'trialing' }),
    ];
    const now = new Date(phoenix(2026, 9, 16) * 1000);
    expect(countTrialsByMonth(subs, now, new Set(['staff@example.com']))).toEqual([
      { label: 'June 2026', trials: 2 },
      { label: 'July 2026', trials: 0 },
      { label: 'August 2026', trials: 1 },
      { label: 'September 2026', trials: 1 },
    ]);
  });

  it('keeps every month back to June once the year turns over', () => {
    const labels = countTrialsByMonth([], new Date(phoenix(2027, 2, 10) * 1000), NONE).map((m) => m.label);
    expect(labels).toEqual([
      'June 2026',
      'July 2026',
      'August 2026',
      'September 2026',
      'October 2026',
      'November 2026',
      'December 2026',
      'January 2027',
      'February 2027',
    ]);
  });
});

describe('computeRetention', () => {
  const now = 1_700_000_000;
  const day = SECONDS_PER_DAY;
  const ended = now - 10 * day;

  it('counts converts in the window still subscribed with no cancellation scheduled', () => {
    // Apart from the baseline rows, each row isolates one condition.
    const subs = [
      sub({ id: 'kept', status: 'active', trialEnd: ended }),
      sub({ id: 'kept_past_due', status: 'past_due', trialEnd: ended }),
      sub({ id: 'canceled', status: 'canceled', trialEnd: ended }),
      sub({ id: 'unpaid', status: 'unpaid', trialEnd: ended }),
      sub({ id: 'set_to_cancel', status: 'active', trialEnd: ended, cancelAtPeriodEnd: true }),
      sub({ id: 'never_paid', status: 'active', trialEnd: ended }),
      sub({ id: 'internal', status: 'active', trialEnd: ended, email: 'staff@example.com' }),
      sub({ id: 'too_old', status: 'active', trialEnd: now - 181 * day }),
      sub({ id: 'still_trialing', status: 'active', trialEnd: now + day }),
    ];
    const paid = new Set(subs.map((s) => s.id).filter((id) => id !== 'never_paid'));
    const result = computeRetention(
      window({ subs, now, paidSubIds: paid, excludedEmails: new Set(['staff@example.com']) })
    );
    expect(result).toBe(2);
  });
});

describe('computeLifetimeChurn', () => {
  it('counts canceled subscribers among everyone who ever paid', () => {
    const subs = [
      sub({ id: 'active', status: 'active', email: 'a@example.com' }),
      sub({ id: 'past_due', status: 'past_due', email: 'b@example.com' }),
      sub({ id: 'left', status: 'canceled', email: 'c@example.com' }),
      sub({ id: 'set_to_cancel', status: 'active', cancelAtPeriodEnd: true, email: 'd@example.com' }),
      sub({ id: 'never_paid', status: 'canceled', email: 'e@example.com' }),
      sub({ id: 'internal', status: 'canceled', email: 'staff@example.com' }),
    ];
    const everPaid = new Set(['active', 'past_due', 'left', 'set_to_cancel', 'internal']);
    expect(computeLifetimeChurn(subs, everPaid, new Set(['staff@example.com']))).toEqual({ paid: 4, churned: 1 });
  });

  it('counts people, not subscriptions, so a returning subscriber is not churned', () => {
    const subs = [
      // Active first, so a later canceled row for the same person must not overwrite it.
      sub({ id: 'new', status: 'active', email: 'Back@example.com' }),
      sub({ id: 'old', status: 'canceled', email: 'back@example.com' }),
      sub({ id: 'twice_gone_a', status: 'canceled', email: 'gone@example.com' }),
      sub({ id: 'twice_gone_b', status: 'canceled', email: 'gone@example.com' }),
      sub({ id: 'unpaid', status: 'unpaid', email: 'owing@example.com' }),
    ];
    const everPaid = new Set(subs.map((s) => s.id));
    expect(computeLifetimeChurn(subs, everPaid, NONE)).toEqual({ paid: 3, churned: 1 });
  });
});

describe('computePaidChurnRate', () => {
  const now = 1_700_000_000;
  const day = SECONDS_PER_DAY;
  const matured = now - 45 * day;
  const all = (subs: Stripe.Subscription[]) => new Set(subs.map((s) => s.id));

  const payer = (id: string, status: Stripe.Subscription.Status, cancelOffsetDays?: number) =>
    sub({
      id,
      status,
      trialEnd: matured,
      canceledAt: cancelOffsetDays === undefined ? null : matured + cancelOffsetDays * day,
      endedAt: cancelOffsetDays === undefined ? null : matured + cancelOffsetDays * day,
    });
  const survivors = (n: number) => Array.from({ length: n }, (_, i) => payer(`sub_ok_${i}`, 'active'));

  it('measures cancellations inside the first paid month', () => {
    const subs = [...survivors(4), payer('sub_5', 'canceled', 10), payer('sub_6', 'canceled', 20)];
    const result = computePaidChurnRate(window({ subs, now, paidSubIds: all(subs) }));
    expect(result.sample).toBe(6);
    expect(result.observed).toBe(2);
    expect(result.rate).toBeCloseTo(1 / 3);
  });

  it('excludes subscriptions that never activated, so a declined card is not churn', () => {
    const subs = [...survivors(5), payer('sub_declined', 'canceled', 5)];
    const paid = new Set(subs.filter((s) => s.id !== 'sub_declined').map((s) => s.id));
    const result = computePaidChurnRate(window({ subs, now, paidSubIds: paid }));
    expect(result.sample).toBe(5);
    expect(result.observed).toBe(0);
  });

  it('ignores a cancellation beyond the first paid month', () => {
    const subs = [...survivors(4), payer('sub_late', 'canceled', 40)];
    expect(computePaidChurnRate(window({ subs, now, paidSubIds: all(subs) })).observed).toBe(0);
  });

  it('ignores a cancellation recorded at or before the trial ended', () => {
    const subs = [
      ...survivors(4),
      sub({ id: 'sub_at', status: 'canceled', trialEnd: matured, endedAt: matured }),
      sub({ id: 'sub_before', status: 'canceled', trialEnd: matured, endedAt: matured - 2 * day }),
    ];
    const result = computePaidChurnRate(window({ subs, now, paidSubIds: all(subs) }));
    expect(result.sample).toBe(6);
    expect(result.observed).toBe(0);
  });

  it('ignores a subscriber whose trial ended before the window opened', () => {
    const subs = [
      ...survivors(5),
      sub({ id: 'sub_old', status: 'canceled', trialEnd: now - 200 * day, endedAt: now - 190 * day }),
    ];
    const result = computePaidChurnRate(window({ subs, now, paidSubIds: all(subs) }));
    expect(result.sample).toBe(5);
    expect(result.observed).toBe(0);
  });

  it('does not count a subscriber who is still being served', () => {
    // Converted, then set cancel-at-period-end three days later: still active,
    // canceled_at set, ended_at null. Service has not stopped.
    const subs = [
      ...survivors(4),
      sub({ id: 'sub_pending', status: 'active', trialEnd: matured, canceledAt: matured + 3 * day, endedAt: null }),
    ];
    const result = computePaidChurnRate(window({ subs, now, paidSubIds: all(subs) }));
    expect(result.sample).toBe(5);
    expect(result.observed).toBe(0);
  });

  it('measures from service end, not from a period-end cancellation request', () => {
    const subs = [
      ...survivors(4),
      sub({
        id: 'sub_annual',
        status: 'canceled',
        trialEnd: matured,
        canceledAt: matured + 3 * day,
        endedAt: matured + 365 * day,
      }),
    ];
    expect(computePaidChurnRate(window({ subs, now, paidSubIds: all(subs) })).observed).toBe(0);
  });

  it('falls back to canceled_at when no end was recorded', () => {
    const subs = [
      ...survivors(4),
      sub({ id: 'sub_x', status: 'canceled', trialEnd: matured, canceledAt: matured + 3 * day }),
    ];
    expect(computePaidChurnRate(window({ subs, now, paidSubIds: all(subs) })).observed).toBe(1);
  });

  it('ignores subscribers whose first paid month has not finished', () => {
    const subs = Array.from({ length: 6 }, (_, i) => sub({ id: `sub_${i}`, trialEnd: now - 5 * day }));
    const result = computePaidChurnRate(window({ subs, now, paidSubIds: all(subs) }));
    expect(result.sample).toBe(0);
    expect(result.rate).toBe(FALLBACK_CHURN_RATE);
  });

  it('removes excluded emails from the cohort', () => {
    const subs = [
      ...survivors(5),
      sub({
        id: 'sub_owner',
        status: 'canceled',
        trialEnd: matured,
        endedAt: matured + 5 * day,
        email: 'owner@example.com',
      }),
    ];
    const result = computePaidChurnRate(
      window({ subs, now, paidSubIds: all(subs), excludedEmails: new Set(['owner@example.com']) })
    );
    expect(result.sample).toBe(5);
    expect(result.observed).toBe(0);
    expect(result.excluded).toBe(1);
  });
});

describe('computeTrialProjection', () => {
  // Midnight on Sept 5 in America/Phoenix (UTC-7, no DST): the 5th calendar
  // day, with exactly 4.0 days of the month elapsed. The gap between those two
  // numbers is the bug this suite pins — the run rate divides by the 4.
  const now = new Date(Date.UTC(2026, 8, 5, 7, 0, 0));
  const sept = (d: number) => Date.UTC(2026, 8, d, 7) / 1000;
  const aug = (d: number) => Date.UTC(2026, 7, d, 7) / 1000;
  const septTrial = (id: string, startDay: number) =>
    sub({ id, trialStart: sept(startDay), trialEnd: sept(startDay + 7) });
  const eleven = () => [1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 4].map((d, i) => septTrial(`s${i}`, d));

  it('extrapolates the run rate across the whole month', () => {
    const result = computeTrialProjection(eleven(), now, NONE, NONE);
    expect(result.trialsToDate).toBe(11);
    expect(result.daysElapsed).toBe(4);
    expect(result.dayOfMonth).toBe(5);
    expect(result.daysInMonth).toBe(30);
    expect(result.dailyRate).toBeCloseTo(2.75);
    expect(result.projected).toBeCloseTo(82.5);
  });

  it('pins the band to the sampling error of the observed count', () => {
    const result = computeTrialProjection(eleven(), now, NONE, NONE);
    const margin = 1.2816 * Math.sqrt(11);
    expect(result.low).toBeCloseTo((11 - margin) * 7.5, 4);
    expect(result.high).toBeCloseTo((11 + margin) * 7.5, 4);
  });

  it('never reports a negative lower bound', () => {
    expect(computeTrialProjection([septTrial('a', 1)], now, NONE, NONE).low).toBe(0);
  });

  it('keeps a positive upper bound when nothing has arrived yet', () => {
    const result = computeTrialProjection([], now, NONE, NONE);
    expect(result.projected).toBe(0);
    expect(result.high).toBeCloseTo(1.6094 * 7.5, 4);
  });

  it('excludes trials started in a previous month from the run rate', () => {
    const subs = [sub({ id: 'aug', trialStart: aug(30), trialEnd: sept(6) }), septTrial('sep', 2)];
    expect(computeTrialProjection(subs, now, NONE, NONE).trialsToDate).toBe(1);
  });

  it('counts a resolved carry-in trial as an observed conversion', () => {
    // Started Aug 25, converted Sept 1 — the cash landed in September even
    // though the trial did not start here.
    const subs = [sub({ id: 'carry', trialStart: aug(25), trialEnd: sept(1) })];
    const result = computeTrialProjection(subs, now, new Set(['carry']), NONE);
    expect(result.trialsToDate).toBe(0);
    expect(result.landedConverted).toBe(1);
    expect(result.landingUnresolved).toBeCloseTo(0, 5);
  });

  it('does not count a resolved trial that never activated', () => {
    const subs = [sub({ id: 'carry', trialStart: aug(25), trialEnd: sept(1) })];
    const result = computeTrialProjection(subs, now, NONE, NONE);
    expect(result.landedConverted).toBe(0);
    expect(result.landingUnresolved).toBeCloseTo(0, 5);
  });

  it('does not expect a conversion from a trial already set to cancel', () => {
    const subs = [
      sub({ id: 'live', trialStart: sept(2), trialEnd: sept(9) }),
      sub({ id: 'quitting', trialStart: sept(2), trialEnd: sept(9), cancelAtPeriodEnd: true }),
    ];
    const result = computeTrialProjection(subs, now, NONE, NONE);
    // Both are still running, but one has told us it will not convert.
    expect(result.trialsToDate).toBe(2);
    // Only the live one is unresolved; the run rate of 0.5/day still projects
    // over the 19 remaining start-days.
    expect(result.landingUnresolved).toBeCloseTo(1 + 0.5 * 19, 5);
  });

  it('treats a trial set to cancel through cancel_at alone as not converting', () => {
    const subs = [
      sub({ id: 'live', trialStart: sept(2), trialEnd: sept(9) }),
      sub({ id: 'quitting', trialStart: sept(2), trialEnd: sept(9), cancelAt: sept(9) }),
    ];
    const result = computeTrialProjection(subs, now, NONE, NONE);
    expect(result.trialsToDate).toBe(2);
    expect(result.landingUnresolved).toBeCloseTo(1 + 0.5 * 19, 5);
  });

  it('treats a trial already canceled before its trial end as not converting', () => {
    const subs = [
      sub({ id: 'live', trialStart: sept(2), trialEnd: sept(9) }),
      sub({ id: 'gone', status: 'canceled', trialStart: sept(2), trialEnd: sept(9), cancelAtPeriodEnd: true }),
    ];
    const result = computeTrialProjection(subs, now, NONE, NONE);
    expect(result.trialsToDate).toBe(2);
    expect(result.landingUnresolved).toBeCloseTo(1 + 0.5 * 19, 5);
  });

  it('leaves a trial still running as unresolved rather than counting it', () => {
    const subs = [sub({ id: 'live', trialStart: sept(2), trialEnd: sept(9) })];
    const result = computeTrialProjection(subs, now, new Set(['live']), NONE);
    expect(result.landedConverted).toBe(0);
    expect(result.landingUnresolved).toBeGreaterThanOrEqual(1);
  });

  it('drops excluded accounts from the trial count and the landings', () => {
    const subs = [
      ...eleven(),
      sub({ id: 'internal', email: 'owner@example.com', trialStart: sept(2), trialEnd: sept(9) }),
    ];
    const result = computeTrialProjection(subs, now, NONE, new Set(['owner@example.com']));
    expect(result.trialsToDate).toBe(11);
  });

  it('excludes subscriptions that never had a trial', () => {
    const subs = [sub({ id: 'none' }), septTrial('sep', 2)];
    expect(computeTrialProjection(subs, now, NONE, NONE).trialsToDate).toBe(1);
  });

  it('projects only the starts early enough to finish inside the month', () => {
    const result = computeTrialProjection(eleven(), now, NONE, NONE);
    // 11 in flight, plus the run rate over the 19 remaining start-days whose
    // 7-day trial still closes before month end.
    expect(result.landingUnresolved).toBeCloseTo(11 + 2.75 * 19, 5);
  });

  it('drops late-month starts whose trial ends after the month does', () => {
    const lateInMonth = new Date(Date.UTC(2026, 8, 28, 19, 0, 0));
    const subs = Array.from({ length: 84 }, (_, i) => septTrial(`s${i}`, Math.floor(i / 3) + 1));
    const result = computeTrialProjection(subs, lateInMonth, new Set(subs.map((s) => s.id)), NONE);
    expect(result.trialsToDate).toBe(84);
    // Starts on days 1-21 have ended by midday on the 28th (63 of them, all
    // paid); days 22-23 are still running; days 24-28 convert in October and
    // count in neither.
    expect(result.landedConverted).toBe(63);
    expect(result.landingUnresolved).toBeCloseTo(6, 5);
  });

  it('stays finite on the last day of the month', () => {
    const lastDay = new Date(Date.UTC(2026, 8, 30, 19, 0, 0));
    const subs = Array.from({ length: 60 }, (_, i) => septTrial(`s${i}`, (i % 28) + 1));
    const result = computeTrialProjection(subs, lastDay, NONE, NONE);
    expect(Number.isFinite(result.landingUnresolved)).toBe(true);
    expect(Number.isFinite(result.projected)).toBe(true);
    expect(result.daysElapsed).toBe(29.5);
    expect(result.dayOfMonth).toBe(30);
  });

  it('uses the real length of a short month', () => {
    const feb = new Date(Date.UTC(2026, 1, 10, 19, 0, 0));
    const subs = [
      sub({ id: 'f', trialStart: Date.UTC(2026, 1, 2, 7) / 1000, trialEnd: Date.UTC(2026, 1, 9, 7) / 1000 }),
    ];
    expect(computeTrialProjection(subs, feb, NONE, NONE).daysInMonth).toBe(28);
  });

  it('measures the month in America/Phoenix, not the UTC the server runs in', () => {
    // 00:30 UTC on Sept 1 is still 5:30pm on Aug 31 in Phoenix. Bucketing by
    // UTC put this trial in September and rolled the day counter over seven
    // hours early, which is how the dashboard came to show the 6th on the 5th.
    const augustEvening = sub({ id: 'aug31', trialStart: Date.UTC(2026, 8, 1, 0, 30) / 1000, trialEnd: sept(8) });
    const result = computeTrialProjection([augustEvening, septTrial('sep', 2)], now, NONE, NONE);
    expect(result.trialsToDate).toBe(1);
  });

  it('does not credit the run rate with a day that has barely started', () => {
    // One minute past midnight on the 6th: the calendar says day 6, but only
    // five days of evidence exist. Dividing by 6 understated every rate, and
    // made the projection drop at the moment the day ticked over.
    const justAfterMidnight = new Date(Date.UTC(2026, 8, 6, 7, 1, 0));
    const subs = Array.from({ length: 15 }, (_, i) => septTrial(`s${i}`, (i % 5) + 1));
    const result = computeTrialProjection(subs, justAfterMidnight, NONE, NONE);
    expect(result.dayOfMonth).toBe(6);
    expect(result.daysElapsed).toBeCloseTo(5, 2);
    expect(result.dailyRate).toBeCloseTo(3, 2);
    expect(result.projected).toBeCloseTo(90, 1);
  });

  it('does not extrapolate out of the opening hours of a month', () => {
    // 30 minutes into the 1st. Undivided this projects past 1,400; the run rate
    // is held to what a full first day would show until one has passed.
    const dayOne = new Date(Date.UTC(2026, 8, 1, 7, 30, 0));
    const subs = [septTrial('a', 1), septTrial('b', 1)];
    const result = computeTrialProjection(subs, dayOne, NONE, NONE);
    expect(result.dailyRate).toBe(2);
    expect(result.projected).toBe(60);
    expect(result.high).toBeLessThan(150);
  });
});

describe('countAnnualRenewals', () => {
  const now = new Date(Date.UTC(2026, 8, 15, 12, 0, 0));
  const at = (y: number, m: number, d: number) => Date.UTC(y, m, d) / 1000;

  it('counts an annual renewal still ahead of us this month', () => {
    const subs = [sub({ id: 'a', interval: 'year', currentPeriodEnd: at(2026, 8, 20) })];
    expect(countAnnualRenewals(subs, now)).toBe(1);
  });

  it('ignores a renewal earlier in the month, which has already resolved', () => {
    const subs = [sub({ id: 'b', interval: 'year', currentPeriodEnd: at(2026, 8, 2) })];
    expect(countAnnualRenewals(subs, now)).toBe(0);
  });

  it('ignores annual subscriptions renewing in a later month', () => {
    const subs = [sub({ id: 'a', interval: 'year', currentPeriodEnd: at(2027, 3, 5) })];
    expect(countAnnualRenewals(subs, now)).toBe(0);
  });

  it('ignores monthly subscriptions entirely', () => {
    const subs = [sub({ id: 'm', interval: 'month', currentPeriodEnd: at(2026, 8, 20) })];
    expect(countAnnualRenewals(subs, now)).toBe(0);
  });

  it('finds an annual item that is not the first on the subscription', () => {
    const multi = sub({ id: 'multi', interval: 'month', currentPeriodEnd: at(2026, 8, 20) });
    (multi.items.data as unknown[]).push({
      id: 'si_annual',
      quantity: 1,
      current_period_end: at(2026, 8, 22),
      price: { unit_amount: 6999, recurring: { interval: 'year' } },
    });
    expect(countAnnualRenewals([multi], now)).toBe(1);
  });
});

describe('countObservedChurn', () => {
  const now = new Date(Date.UTC(2026, 8, 15, 12, 0, 0));
  const at = (d: number) => Date.UTC(2026, 8, d) / 1000;

  it('counts an activated subscriber whose service ended this month', () => {
    const subs = [sub({ id: 'gone', status: 'canceled', endedAt: at(9) })];
    expect(countObservedChurn(subs, now, new Set(['gone']), NONE)).toBe(1);
  });

  it('ignores a subscriber who never activated', () => {
    const subs = [sub({ id: 'never', status: 'canceled', endedAt: at(9) })];
    expect(countObservedChurn(subs, now, NONE, NONE)).toBe(0);
  });

  it('ignores service that ended in a previous month', () => {
    const subs = [sub({ id: 'old', status: 'canceled', endedAt: Date.UTC(2026, 7, 20) / 1000 })];
    expect(countObservedChurn(subs, now, new Set(['old']), NONE)).toBe(0);
  });

  it('ignores excluded accounts', () => {
    const subs = [sub({ id: 'owner', status: 'canceled', endedAt: at(9), email: 'owner@example.com' })];
    expect(countObservedChurn(subs, now, new Set(['owner']), new Set(['owner@example.com']))).toBe(0);
  });

  it('ignores a subscriber who has only requested cancellation', () => {
    // Still active and still being served; canceled_at is the request time.
    const subs = [sub({ id: 'pending', status: 'active', cancelAtPeriodEnd: true, canceledAt: at(3), endedAt: null })];
    expect(countObservedChurn(subs, now, new Set(['pending']), NONE)).toBe(0);
  });
});

describe('buildMonthProjection', () => {
  const trials = {
    trialsToDate: 11,
    daysElapsed: 15,
    dayOfMonth: 16,
    daysInMonth: 30,
    dailyRate: 2.75,
    projected: 82.5,
    low: 50,
    high: 115,
    landedConverted: 10,
    landingUnresolved: 40,
  };
  const rate = (r: number): RateEstimate => ({ rate: r, observed: 10, sample: 50, excluded: 0, isFallback: false });

  const build = (over: Partial<Parameters<typeof buildMonthProjection>[0]> = {}) =>
    buildMonthProjection({
      trials,
      conversion: rate(0.5),
      churn: rate(0.2),
      arpu: 7,
      activeMonthly: 10,
      annualRenewalsAhead: 0,
      observedChurn: 0,
      ...over,
    });

  it('counts conversions that already happened and estimates only the rest', () => {
    const result = build();
    expect(result.grossNewSubs).toBeCloseTo(10 + 40 * 0.5); // 30
  });

  it('does not re-estimate a resolved conversion', () => {
    const allResolved = build({ trials: { ...trials, landedConverted: 20, landingUnresolved: 0 } });
    expect(allResolved.grossNewSubs).toBe(20);
  });

  it('adds cancellations that already happened to the estimate for the rest', () => {
    const result = build({ observedChurn: 3 });
    // 3 observed + 10 monthly x 0.2 prorated over the 15 remaining days.
    expect(result.churnedSubs).toBeCloseTo(3 + 10 * 0.2 * 0.5);
    expect(result.observedChurn).toBe(3);
  });

  it('prorates the remaining-month risk by how much month is left', () => {
    const early = build({ trials: { ...trials, daysElapsed: 1 } });
    const late = build({ trials: { ...trials, daysElapsed: 29 } });
    expect(early.churnedSubs).toBeGreaterThan(late.churnedSubs);
  });

  it('charges an annual renewal still ahead at the full rate, not a prorated one', () => {
    const none = build({ annualRenewalsAhead: 0 });
    const three = build({ annualRenewalsAhead: 3 });
    expect(three.churnedSubs - none.churnedSubs).toBeCloseTo(3 * 0.2);
    expect(three.annualRenewalsAhead).toBe(3);
  });

  it('nets month gross against month churn', () => {
    const result = build({ observedChurn: 1 });
    expect(result.netSubs).toBeCloseTo(30 - (1 + 1));
    expect(result.netMrr).toBeCloseTo(result.netSubs * 7);
  });

  it('derives lifetime and LTV from the churn rate', () => {
    const result = build({ churn: rate(0.25), arpu: 8 });
    expect(result.avgLifetimeMonths).toBeCloseTo(4);
    expect(result.ltv).toBeCloseTo(32);
  });

  it('reports lifetime as unmeasurable rather than zero when nobody churned', () => {
    const result = build({ churn: rate(0) });
    expect(result.avgLifetimeMonths).toBeNull();
    expect(result.ltv).toBeNull();
  });
});

describe('netOfStripeFee', () => {
  it('takes 2.9% + 30¢ off each plan price', () => {
    expect(netOfStripeFee(699)).toBe(649);
    expect(netOfStripeFee(6999)).toBe(6766);
  });

  it('takes nothing from no charge at all', () => {
    expect(netOfStripeFee(0)).toBe(0);
  });
});

describe('computeRenewalCollectionRate', () => {
  // Midnight Sept 16 in Phoenix; renewals due before Aug 26 have settled.
  const now = new Date(Date.UTC(2026, 8, 16, 7));
  const d = (m: number, day: number) => Date.UTC(2026, m - 1, day, 7) / 1000;
  // Anchored May 10, so renewals fall due Jun 10, Jul 10 and Aug 10 before the settle window.
  const monthly = (id: string, over: Parameters<typeof sub>[0] = {}) =>
    sub({ id, interval: 'month', billingCycleAnchor: d(5, 10), email: `${id}@example.com`, ...over });
  const renewal = (id: string, created: number, over: Parameters<typeof invoice>[0] = {}) =>
    invoice({ subscription: id, created, ...over });
  const measure = (
    subs: Stripe.Subscription[],
    invoices: Stripe.Invoice[],
    { at = now, excluded = NONE }: { at?: Date; excluded?: Set<string> } = {}
  ) => {
    const { observed, sample } = computeRenewalCollectionRate(
      subs,
      invoices,
      at,
      new Set(subs.map((s) => s.id)),
      excluded
    );
    return { observed, sample };
  };

  it('scores each renewal date a paid invoice collected', () => {
    const invoices = [renewal('a', d(6, 10)), renewal('a', d(7, 10)), renewal('a', d(8, 10))];
    expect(measure([monthly('a')], invoices)).toEqual({ observed: 3, sample: 3 });
  });

  it('counts a renewal date with no paid invoice as a miss', () => {
    expect(measure([monthly('b')], [renewal('b', d(6, 10))])).toEqual({ observed: 1, sample: 2 });
  });

  it('counts a subscription that stays open unpaid as one miss, however long it stays open', () => {
    const stuck = monthly('stuck', { status: 'unpaid', billingCycleAnchor: d(4, 10) });
    expect(measure([stuck], [])).toEqual({ observed: 0, sample: 1 });
    expect(measure([stuck], [], { at: new Date(Date.UTC(2026, 9, 16, 7)) })).toEqual({ observed: 0, sample: 1 });
  });

  it('stops at the first miss even when a later renewal was paid', () => {
    expect(measure([monthly('c')], [renewal('c', d(6, 10)), renewal('c', d(8, 10))])).toEqual({
      observed: 1,
      sample: 2,
    });
  });

  it('leaves out renewals after a cancellation asked for more than a week ahead', () => {
    const left = monthly('d', { status: 'canceled', canceledAt: d(7, 1), endedAt: d(7, 10) });
    expect(measure([left], [renewal('d', d(6, 10))])).toEqual({ observed: 1, sample: 1 });
  });

  it('leaves out renewals after service ended, even with no cancellation time recorded', () => {
    const ended = monthly('gone', { status: 'canceled', canceledAt: null, endedAt: d(7, 1) });
    expect(measure([ended], [renewal('gone', d(6, 10))])).toEqual({ observed: 1, sample: 1 });
  });

  it('counts a cancellation asked for inside the last week as a missed renewal', () => {
    const late = monthly('e', { status: 'canceled', canceledAt: d(7, 5), endedAt: d(7, 10) });
    expect(measure([late], [renewal('e', d(6, 10))])).toEqual({ observed: 1, sample: 2 });
  });

  it('waits out retries before scoring a renewal date', () => {
    // Anchored Jun 1: Sept 1 is due but inside the settle window, so it is not a miss yet.
    const recent = monthly('f', { billingCycleAnchor: d(6, 1) });
    expect(measure([recent], [renewal('f', d(7, 1)), renewal('f', d(8, 1))])).toEqual({ observed: 2, sample: 2 });
  });

  it('leaves out internal accounts', () => {
    const owner = monthly('g', { email: 'owner@example.com' });
    const rate = computeRenewalCollectionRate(
      [owner],
      [renewal('g', d(6, 10))],
      now,
      new Set(['g']),
      new Set(['owner@example.com'])
    );
    expect(rate).toMatchObject({ observed: 0, sample: 0, excluded: 1 });
  });

  it('matches an invoice created within two days of the date, not three', () => {
    const invoices = [
      renewal('two', d(6, 12)),
      renewal('two', d(7, 10)),
      renewal('two', d(8, 10)),
      renewal('three', d(6, 13)),
    ];
    expect(measure([monthly('two'), monthly('three')], invoices)).toEqual({ observed: 3, sample: 4 });
  });

  it('asks the matched invoice for real payment or a coupon, as activation does', () => {
    const invoices = [
      renewal('free', d(6, 10), { amountPaid: 0, amountDue: 0, total: 0 }),
      renewal('coupon', d(6, 10), { amountPaid: 0, amountDue: 0, total: 0, discounts: ['di_x'] }),
    ];
    expect(measure([monthly('free'), monthly('coupon')], invoices)).toEqual({ observed: 1, sample: 3 });
  });

  it('does not take a subscription-creation invoice for a renewal', () => {
    const invoices = [renewal('h', d(6, 10), { billingReason: 'subscription_create' })];
    expect(measure([monthly('h')], invoices)).toEqual({ observed: 0, sample: 1 });
  });

  it("holds a 31st anchor to a shorter month's last day, then returns to the 31st", () => {
    const anchor = Date.UTC(2026, 0, 31, 7) / 1000;
    const invoices = [
      renewal('eom', Date.UTC(2026, 1, 28, 7) / 1000),
      renewal('eom', Date.UTC(2026, 2, 31, 7) / 1000),
      renewal('eom', Date.UTC(2026, 3, 30, 7) / 1000),
    ];
    const at = new Date(Date.UTC(2026, 4, 25, 7));
    expect(measure([monthly('eom', { billingCycleAnchor: anchor })], invoices, { at })).toEqual({
      observed: 3,
      sample: 3,
    });
  });

  it('falls back below the minimum sample and measures from it upward', () => {
    const collected = [renewal('a', d(6, 10)), renewal('a', d(7, 10)), renewal('a', d(8, 10))];
    const few = computeRenewalCollectionRate([monthly('a')], collected, now, new Set(['a']), NONE);
    expect(few).toMatchObject({ isFallback: true, rate: FALLBACK_RENEWAL_RATE });
    const enough = computeRenewalCollectionRate(
      [monthly('a'), monthly('b')],
      [...collected, renewal('b', d(6, 10))],
      now,
      new Set(['a', 'b']),
      NONE
    );
    expect(enough).toMatchObject({ isFallback: false, observed: 4, sample: 5, rate: 0.8 });
  });

  it('ignores annual plans and subscriptions that never paid', () => {
    const annual = sub({ id: 'yr', interval: 'year', billingCycleAnchor: d(5, 10) });
    const never = monthly('np');
    const rate = computeRenewalCollectionRate([annual, never], [renewal('yr', d(6, 10))], now, new Set(['yr']), NONE);
    expect(rate).toMatchObject({ observed: 0, sample: 0 });
  });
});

describe('computeLifetimeConversionByPlan', () => {
  const nowSec = Date.UTC(2026, 8, 16, 7) / 1000;
  const day = SECONDS_PER_DAY;

  it('measures each plan over every trial that has ended, however long ago', () => {
    const subs = [
      sub({ id: 'm1', interval: 'month', trialEnd: nowSec - 10 * day }),
      sub({ id: 'm2', interval: 'month', trialEnd: nowSec - 400 * day }),
      sub({ id: 'm3', interval: 'month', trialEnd: nowSec - 5 * day }),
      sub({ id: 'm4', interval: 'month', status: 'trialing', trialEnd: nowSec + 3 * day }),
      sub({ id: 'y1', interval: 'year', trialEnd: nowSec - 20 * day }),
      sub({ id: 'y2', interval: 'year', trialEnd: nowSec - 30 * day }),
    ];
    const paid = new Set(['m1', 'm2', 'm4', 'y1']);
    const { month, year } = computeLifetimeConversionByPlan(subs, paid, nowSec, NONE);
    expect(month).toMatchObject({ observed: 2, sample: 3 });
    expect(year).toMatchObject({ observed: 1, sample: 2 });
  });
});

describe('buildCashForecast', () => {
  // Midnight Sept 16 in Phoenix: the month window runs 15 days, to Oct 1.
  const now = new Date(Date.UTC(2026, 8, 16, 7));
  const nowSec = now.getTime() / 1000;
  const day = SECONDS_PER_DAY;
  const estimate = (rate: number): RateEstimate => ({ rate, observed: 0, sample: 0, excluded: 0, isFallback: false });
  const forecast = (
    subs: Stripe.Subscription[],
    {
      at = now,
      excludedEmails = NONE,
      paidSubIds = new Set(subs.map((s) => s.id)),
      monthRate = 0.5,
    }: { at?: Date; excludedEmails?: Set<string>; paidSubIds?: Set<string>; monthRate?: number } = {}
  ) =>
    buildCashForecast({
      now: at,
      subs,
      paidSubIds,
      conversion: { month: estimate(monthRate), year: estimate(0.4) },
      renewalRate: estimate(0.9),
      excludedEmails,
    });
  const trial = (id: string, over: Parameters<typeof sub>[0] = {}) =>
    sub({ id, status: 'trialing', trialEnd: nowSec + 2 * day, ...over });

  it('dates a renewal on its period end, at the collection rate, in every window that holds it', () => {
    const { week, fortnight, month } = forecast([sub({ id: 'r', currentPeriodEnd: nowSec + 4 * day })]).windows;
    // 649 net × 0.9.
    expect([week.renewals, fortnight.renewals, month.renewals]).toEqual([5.84, 5.84, 5.84]);
  });

  it('leaves a charge due exactly at the end of a window to the next one', () => {
    const { week, fortnight } = forecast([sub({ id: 'edge', currentPeriodEnd: nowSec + 7 * day })]).windows;
    expect(week.renewals).toBe(0);
    expect(fortnight.renewals).toBe(5.84);
  });

  it('leaves out a renewal whose cancellation is scheduled, either way it was set', () => {
    const subs = [
      sub({ id: 'flag', cancelAtPeriodEnd: true, currentPeriodEnd: nowSec + 4 * day }),
      sub({ id: 'date', cancelAt: nowSec + 4 * day, currentPeriodEnd: nowSec + 4 * day }),
    ];
    expect(forecast(subs).windows.week.renewals).toBe(0);
  });

  it('counts a trial on its end at its own plan rate, set to cancel or not', () => {
    expect(forecast([trial('m', { interval: 'month', unitAmount: 699 })]).windows.week.trials).toBe(3.25);
    const leaving = trial('y', { interval: 'year', unitAmount: 6999, cancelAtPeriodEnd: true });
    // 6766 net × 0.4.
    expect(forecast([leaving]).windows.week.trials).toBe(27.06);
  });

  it('leaves out internal accounts', () => {
    const owner = trial('owner', { email: 'owner@example.com' });
    expect(forecast([owner], { excludedEmails: new Set(['owner@example.com']) }).windows.week.trials).toBe(0);
  });

  it('forecasts no renewal for a subscriber who has never paid', () => {
    // A declined first charge leaves the subscription past due; its trial already counts as not converted.
    const declined = sub({ id: 'declined', status: 'past_due', currentPeriodEnd: nowSec + 4 * day });
    expect(forecast([declined], { paidSubIds: NONE }).windows.week.renewals).toBe(0);
    expect(forecast([declined]).windows.week.renewals).toBe(5.84);
  });

  it('books a trial ending in the window as a trial, never also as a renewal, and nothing for unpaid', () => {
    const ending = trial('ending', { trialEnd: nowSec + 3 * day });
    const unpaid = sub({ id: 'unpaid', status: 'unpaid', currentPeriodEnd: nowSec + 4 * day });
    const { week } = forecast([ending, unpaid]).windows;
    expect(week.renewals).toBe(0);
    expect(week.trials).toBe(3.25);
  });

  it('expects no charge from a trial cancelled outright before its end', () => {
    const cancelled = sub({
      id: 'cancelled',
      status: 'canceled',
      trialStart: nowSec - 3 * day,
      trialEnd: nowSec + 4 * day,
      canceledAt: nowSec - day,
      endedAt: nowSec - day,
    });
    expect(forecast([cancelled]).windows.week.trials).toBe(0);
  });

  it('takes the fee once per charge: once for two seats billed together, twice for two subscriptions', () => {
    const seats = sub({ id: 'seats', currentPeriodEnd: nowSec + 4 * day });
    (seats.items.data as unknown[]).push({
      id: 'si_second',
      quantity: 1,
      current_period_end: nowSec + 4 * day,
      price: { unit_amount: 699, recurring: { interval: 'month' } },
    });
    // (1398 − 71) × 0.9, against 2 × 649 × 0.9.
    expect(forecast([seats]).windows.week.renewals).toBe(11.94);
    const pair = [
      sub({ id: 'one', currentPeriodEnd: nowSec + 4 * day }),
      sub({ id: 'two', currentPeriodEnd: nowSec + 5 * day }),
    ];
    expect(forecast(pair).windows.week.renewals).toBe(11.68);
  });

  it('adds trials yet to start at the last fortnight of starts, where one can finish in time', () => {
    const started = [
      sub({ id: 'in', status: 'canceled', trialStart: nowSec - 13 * day, trialEnd: nowSec - 6 * day }),
      sub({ id: 'out', status: 'canceled', trialStart: nowSec - 15 * day, trialEnd: nowSec - 8 * day }),
    ];
    const { week, fortnight, month } = forecast(started).windows;
    // 324.5 cents a trial over 14 days: 7 days of starts finish within 14 days, 8 within the 15 to Oct 1.
    expect(week.newTrials).toBeNull();
    expect(fortnight.newTrials).toBe(1.62);
    expect(month.newTrials).toBe(1.85);
  });

  it('adds no new trials to a month with a week or less left', () => {
    const started = [sub({ id: 'in', status: 'canceled', trialStart: nowSec - 3 * day, trialEnd: nowSec + 4 * day })];
    const lastWeek = new Date(Date.UTC(2026, 8, 24, 7));
    expect(forecast(started, { at: lastWeek }).windows.month.newTrials).toBeNull();
  });

  it('skips a subscription with no plan rather than turning every sum into NaN', () => {
    const base = trial('base', { trialStart: nowSec - 3 * day, trialEnd: nowSec + 4 * day });
    const planless = trial('planless', { trialStart: nowSec - 3 * day, trialEnd: nowSec + 4 * day });
    (planless.items.data[0].price as { recurring: unknown }).recurring = null;
    const without = forecast([base]).windows;
    const withIt = forecast([base, planless]).windows;
    expect(withIt.week.trials).toBe(without.week.trials);
    expect(withIt.fortnight.newTrials).toBe(without.fortnight.newTrials);
    expect(Number.isFinite(withIt.week.trials)).toBe(true);
    expect(Number.isFinite(withIt.fortnight.newTrials)).toBe(true);
  });

  it('rounds each part to the cent and totals the rounded parts', () => {
    const subs = [
      sub({ id: 'renews', currentPeriodEnd: nowSec + 4 * day }),
      trial('ends'),
      sub({ id: 'started', status: 'canceled', trialStart: nowSec - 13 * day, trialEnd: nowSec - 6 * day }),
    ];
    expect(forecast(subs).windows.fortnight).toEqual({
      end: nowSec + 14 * day,
      renewals: 5.84,
      trials: 3.25,
      newTrials: 1.62,
      total: 10.71,
    });
  });

  it('totals the rounded parts even where rounding the whole would add a cent', () => {
    // Four renewals at 584.1 cents round down to $23.36 and a trial at 310.2 to $3.10: the parts
    // make $26.46, where the unrounded 2646.6 cents would round up to $26.47.
    const subs = [1, 2, 3, 4].map((n) => sub({ id: `renews${n}`, currentPeriodEnd: nowSec + n * day }));
    const { week } = forecast([...subs, trial('ends')], { monthRate: 0.478 }).windows;
    expect(week).toMatchObject({ renewals: 23.36, trials: 3.1, total: 26.46 });
  });
});
