import { describe, it, expect } from 'vitest';
import type Stripe from 'stripe';
import { makeStripeInvoice as invoice, makeStripeSubscription as sub } from '@/test/fixtures';
import { SECONDS_PER_DAY } from '../constants';

import {
  buildMonthProjection,
  buildUnpaidInvoices,
  collectPaidSubscriptionIds,
  computePaidChurnRate,
  computeTrialConversionRate,
  computeTrialProjection,
  countAnnualRenewals,
  countObservedChurn,
  describeRate,
  FALLBACK_CHURN_RATE,
  FALLBACK_CONVERSION_RATE,
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
  // 2026-09-04 UTC — day 4 of a 30-day month.
  const now = new Date(Date.UTC(2026, 8, 4, 12, 0, 0));
  const sept = (d: number) => Date.UTC(2026, 8, d) / 1000;
  const aug = (d: number) => Date.UTC(2026, 7, d) / 1000;
  const septTrial = (id: string, startDay: number) =>
    sub({ id, trialStart: sept(startDay), trialEnd: sept(startDay + 7) });
  const eleven = () => [1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 4].map((d, i) => septTrial(`s${i}`, d));

  it('extrapolates the run rate across the whole month', () => {
    const result = computeTrialProjection(eleven(), now, NONE, NONE);
    expect(result.trialsToDate).toBe(11);
    expect(result.daysElapsed).toBe(4);
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
    const lateInMonth = new Date(Date.UTC(2026, 8, 28, 12, 0, 0));
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
    const lastDay = new Date(Date.UTC(2026, 8, 30, 12, 0, 0));
    const subs = Array.from({ length: 60 }, (_, i) => septTrial(`s${i}`, (i % 28) + 1));
    const result = computeTrialProjection(subs, lastDay, NONE, NONE);
    expect(Number.isFinite(result.landingUnresolved)).toBe(true);
    expect(Number.isFinite(result.projected)).toBe(true);
    expect(result.daysElapsed).toBe(30);
  });

  it('uses the real length of a short month', () => {
    const feb = new Date(Date.UTC(2026, 1, 10, 12, 0, 0));
    const subs = [sub({ id: 'f', trialStart: Date.UTC(2026, 1, 2) / 1000, trialEnd: Date.UTC(2026, 1, 9) / 1000 })];
    expect(computeTrialProjection(subs, feb, NONE, NONE).daysInMonth).toBe(28);
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
    expect(result.grossNewMrr).toBeCloseTo(210);
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

  it('values the whole cohort separately from the month', () => {
    const result = build();
    expect(result.cohortSubs).toBeCloseTo(41.25);
    expect(result.cohortMrr).toBeCloseTo(288.75);
  });

  it('derives lifetime and LTV from the churn rate', () => {
    const result = build({ churn: rate(0.25), arpu: 8 });
    expect(result.avgLifetimeMonths).toBeCloseTo(4);
    expect(result.ltv).toBeCloseTo(32);
    expect(result.cohortValue).toBeCloseTo(41.25 * 32);
  });

  it('reports lifetime as unmeasurable rather than zero when nobody churned', () => {
    const result = build({ churn: rate(0) });
    expect(result.avgLifetimeMonths).toBeNull();
    expect(result.ltv).toBeNull();
    expect(result.cohortValue).toBeNull();
  });
});

describe('buildUnpaidInvoices', () => {
  const unpaid = (o: Parameters<typeof invoice>[0] = {}) =>
    invoice({ amountPaid: 0, amountDue: 699, amountRemaining: 699, attempted: true, attemptCount: 1, ...o });

  it('keeps only invoices Stripe actually tried to collect', () => {
    const invoices = [
      unpaid({ id: 'in_1' }),
      unpaid({ id: 'in_2', attempted: false }),
      unpaid({ id: 'in_3', amountRemaining: 0 }),
    ];
    const result = buildUnpaidInvoices(invoices);
    expect(result.total).toBe(1);
    expect(result.list[0].id).toBe('in_1');
  });

  it('ignores invoices with no subscription behind them', () => {
    expect(buildUnpaidInvoices([unpaid({ subscription: null })]).total).toBe(0);
  });

  it('reports what is still owed, not the original amount', () => {
    const result = buildUnpaidInvoices([unpaid({ amountDue: 6999, amountPaid: 3000, amountRemaining: 3999 })]);
    expect(result.list[0].amountRemaining).toBe(39.99);
    expect(result.outstanding).toBe(39.99);
  });

  it('reads whether a retry is scheduled from Stripe, not from the attempt count', () => {
    const invoices = [
      unpaid({ id: 'done', attemptCount: 1, nextPaymentAttempt: null }),
      unpaid({ id: 'pending', attemptCount: 5, nextPaymentAttempt: 1_800_000_000 }),
    ];
    const result = buildUnpaidInvoices(invoices);
    expect(result.noRetryScheduled).toBe(1);
    expect(result.list.find((e) => e.id === 'done')?.retryScheduled).toBe(false);
    expect(result.list.find((e) => e.id === 'pending')?.retryScheduled).toBe(true);
  });

  it('sorts the largest recoverable balance first', () => {
    const invoices = [unpaid({ id: 'small', amountRemaining: 699 }), unpaid({ id: 'big', amountRemaining: 6999 })];
    expect(buildUnpaidInvoices(invoices).list.map((e) => e.id)).toEqual(['big', 'small']);
  });

  it('breaks an equal-amount tie by invoice date', () => {
    const invoices = [
      unpaid({ id: 'newer', amountRemaining: 699, created: 1_700_000_500 }),
      unpaid({ id: 'older', amountRemaining: 699, created: 1_700_000_000 }),
    ];
    expect(buildUnpaidInvoices(invoices).list.map((e) => e.id)).toEqual(['older', 'newer']);
  });

  it('survives a missing email', () => {
    expect(buildUnpaidInvoices([unpaid({ email: null })]).list[0].email).toBe('(no email)');
  });

  it('returns empty totals for no invoices', () => {
    expect(buildUnpaidInvoices([])).toEqual({ list: [], total: 0, outstanding: 0, noRetryScheduled: 0 });
  });
});

describe('describeRate', () => {
  it('reports a measured rate with the cohort behind it', () => {
    expect(describeRate({ rate: 0.473, observed: 79, sample: 167, excluded: 0, isFallback: false })).toBe(
      '47.3% from 79 of 167'
    );
  });

  it('says so when the number is a historical fallback rather than a measurement', () => {
    expect(describeRate({ rate: 0.478, observed: 1, sample: 3, excluded: 0, isFallback: true })).toBe(
      '47.8% (historical fallback — only 3 in cohort)'
    );
  });
});
