import { describe, it, expect, vi } from 'vitest';
import type Stripe from 'stripe';

vi.mock('server-only', () => ({}));

import {
  computeMrr,
  bucketActivePaid,
  buildTrialPipeline,
  buildPastDue,
  computeConversion,
} from '../subscription-metrics';

const SECONDS_PER_DAY = 86_400;

function makeSub(overrides: {
  id?: string;
  status?: Stripe.Subscription.Status;
  interval?: 'month' | 'year';
  unitAmount?: number;
  quantity?: number;
  trialStart?: number | null;
  trialEnd?: number | null;
  email?: string;
}): Stripe.Subscription {
  const {
    id = `sub_${Math.random().toString(36).slice(2)}`,
    status = 'active',
    interval = 'month',
    unitAmount = 699,
    quantity = 1,
    trialStart = null,
    trialEnd = null,
    email = 'test@example.com',
  } = overrides;
  return {
    id,
    status,
    trial_start: trialStart,
    trial_end: trialEnd,
    customer: { id: 'cus_x', email, deleted: false } as unknown as Stripe.Customer,
    items: {
      data: [
        {
          id: 'si_x',
          quantity,
          price: {
            unit_amount: unitAmount,
            recurring: { interval },
          },
        },
      ],
    },
  } as unknown as Stripe.Subscription;
}

describe('computeMrr', () => {
  it('sums monthly subs at face value', () => {
    const subs = [makeSub({ interval: 'month', unitAmount: 699 }), makeSub({ interval: 'month', unitAmount: 1299 })];
    expect(computeMrr(subs)).toBe(20); // (699 + 1299) / 100 = 19.98 → rounds to 20
  });

  it('normalizes annual subs to monthly equivalent', () => {
    const subs = [makeSub({ interval: 'year', unitAmount: 6999 })];
    // 6999 / 12 = 583.25 cents → 5.83 dollars → rounds to 6
    expect(computeMrr(subs)).toBe(6);
  });

  it('mixes monthly and annual correctly', () => {
    const subs = [
      makeSub({ interval: 'month', unitAmount: 699 }), // 6.99
      makeSub({ interval: 'year', unitAmount: 6999 }), // 5.83
    ];
    // 699 + (6999/12) = 699 + 583.25 = 1282.25 cents → 12.82 dollars → rounds to 13
    expect(computeMrr(subs)).toBe(13);
  });

  it('respects quantity', () => {
    const subs = [makeSub({ interval: 'month', unitAmount: 699, quantity: 3 })];
    expect(computeMrr(subs)).toBe(21); // 6.99 * 3 = 20.97 → rounds to 21
  });

  it('returns 0 for an empty list', () => {
    expect(computeMrr([])).toBe(0);
  });
});

describe('bucketActivePaid', () => {
  it('classifies by interval', () => {
    const subs = [makeSub({ interval: 'month' }), makeSub({ interval: 'month' }), makeSub({ interval: 'year' })];
    expect(bucketActivePaid(subs)).toEqual({ total: 3, monthly: 2, annual: 1 });
  });

  it('handles empty list', () => {
    expect(bucketActivePaid([])).toEqual({ total: 0, monthly: 0, annual: 0 });
  });
});

describe('buildTrialPipeline', () => {
  const now = 1_700_000_000; // arbitrary fixed second

  it('sorts by soonest trial end', () => {
    const subs = [
      makeSub({ id: 'sub_late', trialEnd: now + 5 * SECONDS_PER_DAY }),
      makeSub({ id: 'sub_soon', trialEnd: now + 1 * SECONDS_PER_DAY }),
      makeSub({ id: 'sub_mid', trialEnd: now + 3 * SECONDS_PER_DAY }),
    ];
    const result = buildTrialPipeline(subs, now);
    expect(result.list.map((e) => e.id)).toEqual(['sub_soon', 'sub_mid', 'sub_late']);
  });

  it('endingIn3Days is a subset of endingIn7Days', () => {
    const subs = [
      makeSub({ trialEnd: now + 1 * SECONDS_PER_DAY }), // in 1d → in both
      makeSub({ trialEnd: now + 2 * SECONDS_PER_DAY }), // in 2d → in both
      makeSub({ trialEnd: now + 5 * SECONDS_PER_DAY }), // in 5d → only ≤7d
      makeSub({ trialEnd: now + 10 * SECONDS_PER_DAY }), // in 10d → neither
    ];
    const result = buildTrialPipeline(subs, now);
    expect(result.endingIn3Days).toBe(2);
    expect(result.endingIn7Days).toBe(3);
    expect(result.endingIn3Days).toBeLessThanOrEqual(result.endingIn7Days);
  });

  it('skips subs without trial_end', () => {
    const subs = [makeSub({ trialEnd: null }), makeSub({ trialEnd: now + SECONDS_PER_DAY })];
    const result = buildTrialPipeline(subs, now);
    expect(result.list).toHaveLength(1);
  });

  it('uses customer email', () => {
    const subs = [makeSub({ email: 'jane@example.com', trialEnd: now + SECONDS_PER_DAY })];
    expect(buildTrialPipeline(subs, now).list[0].email).toBe('jane@example.com');
  });
});

describe('buildPastDue', () => {
  it('returns total and list with email + interval', () => {
    const subs = [
      makeSub({ status: 'past_due', interval: 'month', email: 'a@x.com' }),
      makeSub({ status: 'past_due', interval: 'year', email: 'b@x.com' }),
    ];
    const result = buildPastDue(subs);
    expect(result.total).toBe(2);
    expect(result.list[0].email).toBe('a@x.com');
    expect(result.list[1].interval).toBe('year');
  });

  it('returns zero for empty list', () => {
    expect(buildPastDue([])).toEqual({ total: 0, list: [] });
  });
});

describe('computeConversion', () => {
  const now = 1_700_000_000;
  const day = SECONDS_PER_DAY;

  it('returns null percent when sample < 5', () => {
    const subs = [
      makeSub({ status: 'active', trialStart: now - 45 * day, trialEnd: now - 38 * day }),
      makeSub({ status: 'canceled', trialStart: now - 50 * day, trialEnd: now - 43 * day }),
    ];
    const result = computeConversion(subs, now);
    expect(result.sample).toBe(2);
    expect(result.percent).toBeNull();
  });

  it('counts only completed trials in cohort window', () => {
    const subs = [
      // In window, completed, active → counts as converted
      makeSub({ status: 'active', trialStart: now - 45 * day, trialEnd: now - 38 * day }),
      makeSub({ status: 'active', trialStart: now - 50 * day, trialEnd: now - 43 * day }),
      makeSub({ status: 'active', trialStart: now - 55 * day, trialEnd: now - 48 * day }),
      // In window, completed, canceled → counts in sample, not converted
      makeSub({ status: 'canceled', trialStart: now - 45 * day, trialEnd: now - 38 * day }),
      makeSub({ status: 'canceled', trialStart: now - 50 * day, trialEnd: now - 43 * day }),
      // Trial too recent (started < 30d ago) → excluded
      makeSub({ status: 'trialing', trialStart: now - 5 * day, trialEnd: now + 2 * day }),
      // Trial older than 60d → excluded
      makeSub({ status: 'active', trialStart: now - 80 * day, trialEnd: now - 73 * day }),
      // Trial still in flight (trial_end > now) → excluded
      makeSub({ status: 'trialing', trialStart: now - 35 * day, trialEnd: now + 1 * day }),
    ];
    const result = computeConversion(subs, now);
    expect(result.sample).toBe(5);
    expect(result.converted).toBe(3);
    expect(result.percent).toBe(60); // 3/5 = 60%
  });

  it('handles zero sample', () => {
    expect(computeConversion([], now)).toEqual({
      window: '30d',
      sample: 0,
      converted: 0,
      percent: null,
    });
  });
});
