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
  cancelAtPeriodEnd?: boolean;
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
    cancelAtPeriodEnd = false,
  } = overrides;
  return {
    id,
    status,
    trial_start: trialStart,
    trial_end: trialEnd,
    cancel_at_period_end: cancelAtPeriodEnd,
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
  it('sums monthly subs preserving cents', () => {
    const subs = [makeSub({ interval: 'month', unitAmount: 699 }), makeSub({ interval: 'month', unitAmount: 1299 })];
    expect(computeMrr(subs)).toBe(19.98); // 699 + 1299 = 1998 cents → 19.98 dollars
  });

  it('normalizes annual subs to monthly equivalent with cents', () => {
    const subs = [makeSub({ interval: 'year', unitAmount: 6999 })];
    // 6999 / 12 = 583.25 cents → rounds to nearest cent → 5.83 dollars
    expect(computeMrr(subs)).toBe(5.83);
  });

  it('mixes monthly and annual correctly', () => {
    const subs = [
      makeSub({ interval: 'month', unitAmount: 699 }), // 699 cents
      makeSub({ interval: 'year', unitAmount: 6999 }), // 583.25 cents
    ];
    // 699 + 583.25 = 1282.25 cents → rounds to 1282 cents → 12.82 dollars
    expect(computeMrr(subs)).toBe(12.82);
  });

  it('respects quantity', () => {
    const subs = [makeSub({ interval: 'month', unitAmount: 699, quantity: 3 })];
    expect(computeMrr(subs)).toBe(20.97); // 6.99 * 3
  });

  it('returns 0 for an empty list', () => {
    expect(computeMrr([])).toBe(0);
  });

  it('rounds half-cent up', () => {
    // 6999 / 12 = 583.25 cents → rounds to 583 cents (banker would round, but Math.round half-up)
    // Pick a value that lands exactly on .5 cents to verify behavior
    const subs = [makeSub({ interval: 'year', unitAmount: 12 * 199 + 6 })]; // 12*199 + 6 = 2394 → /12 = 199.5 cents
    // 199.5 → Math.round → 200 cents → 2.00 dollars
    expect(computeMrr(subs)).toBe(2);
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
    expect(result.activeTotal).toBe(3);
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

  it('hides trials marked cancel_at_period_end and counts them separately', () => {
    const subs = [
      // active trial — included
      makeSub({ id: 'sub_active', trialEnd: now + 2 * SECONDS_PER_DAY }),
      // canceled trial — hidden but counted
      makeSub({
        id: 'sub_canceled_a',
        trialEnd: now + 1 * SECONDS_PER_DAY,
        cancelAtPeriodEnd: true,
        email: 'colvillem@gmail.com',
      }),
      makeSub({
        id: 'sub_canceled_b',
        trialEnd: now + 3 * SECONDS_PER_DAY,
        cancelAtPeriodEnd: true,
        email: 'ronald.warzoha@gmail.com',
      }),
    ];
    const result = buildTrialPipeline(subs, now);
    expect(result.activeTotal).toBe(1);
    expect(result.canceledPending).toBe(2);
    expect(result.list.map((e) => e.id)).toEqual(['sub_active']);
    // canceled trials must not affect ending buckets
    expect(result.endingIn3Days).toBe(1);
    expect(result.endingIn7Days).toBe(1);
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

  it('counts active and past_due as converted; excludes still-in-flight and out-of-window', () => {
    const subs = [
      // In window, completed, active → converted
      makeSub({ status: 'active', trialStart: now - 45 * day, trialEnd: now - 38 * day }),
      makeSub({ status: 'active', trialStart: now - 50 * day, trialEnd: now - 43 * day }),
      makeSub({ status: 'active', trialStart: now - 55 * day, trialEnd: now - 48 * day }),
      // In window, completed, past_due → converted (paid at least once, now in dunning)
      makeSub({ status: 'past_due', trialStart: now - 45 * day, trialEnd: now - 38 * day }),
      // In window, completed, canceled → in sample, not converted
      makeSub({ status: 'canceled', trialStart: now - 45 * day, trialEnd: now - 38 * day }),
      makeSub({ status: 'canceled', trialStart: now - 50 * day, trialEnd: now - 43 * day }),
      // Trial too recent (started < 30d ago) → excluded
      makeSub({ status: 'trialing', trialStart: now - 5 * day, trialEnd: now + 2 * day }),
      // Trial older than 60d → excluded
      makeSub({ status: 'active', trialStart: now - 80 * day, trialEnd: now - 73 * day }),
      // Trial still in flight (trial_end > now) → excluded — does not penalize conversion
      makeSub({ status: 'trialing', trialStart: now - 35 * day, trialEnd: now + 1 * day }),
    ];
    const result = computeConversion(subs, now);
    expect(result.sample).toBe(6);
    expect(result.converted).toBe(4);
    expect(result.percent).toBe(67); // 4/6 = 66.67% → rounds to 67
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
