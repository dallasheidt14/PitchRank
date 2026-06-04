import { describe, it, expect, vi } from 'vitest';
import type Stripe from 'stripe';

vi.mock('server-only', () => ({}));

import {
  computeMrr,
  bucketActivePaid,
  buildTrialPipeline,
  buildPastDue,
  computeConversion,
  dedupeEmails,
  computeLeadConversion,
  computeLeadToTrial,
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
      makeSub({ status: 'active', trialEnd: now - 7 * day }),
      makeSub({ status: 'canceled', trialEnd: now - 7 * day }),
    ];
    const result = computeConversion(subs, now);
    expect(result.sample).toBe(2);
    expect(result.percent).toBeNull();
  });

  it('counts active and past_due as converted; trial-end-in-future is excluded', () => {
    const subs = [
      // Recent conversions (trial just ended) — these were the bug: previously excluded
      makeSub({ status: 'active', trialEnd: now - 1 * day }),
      makeSub({ status: 'active', trialEnd: now - 3 * day }),
      makeSub({ status: 'active', trialEnd: now - 10 * day }),
      // past_due — paid at least once, currently in dunning → converted
      makeSub({ status: 'past_due', trialEnd: now - 5 * day }),
      // canceled after trial — counts in sample, not converted
      makeSub({ status: 'canceled', trialEnd: now - 5 * day }),
      makeSub({ status: 'canceled', trialEnd: now - 20 * day }),
      // Trial still in flight — excluded so it doesn't penalize conversion
      makeSub({ status: 'trialing', trialEnd: now + 2 * day }),
      // No trial at all — excluded (can't measure trial conversion on a non-trial sub)
      makeSub({ status: 'active', trialEnd: null }),
    ];
    const result = computeConversion(subs, now);
    expect(result.sample).toBe(6);
    expect(result.converted).toBe(4);
    expect(result.percent).toBe(67); // 4/6 = 66.67% → 67
  });

  it('reports the windowDays passed by caller', () => {
    const result = computeConversion([], now, undefined, 90);
    expect(result.windowDays).toBe(90);
  });

  it('handles zero sample', () => {
    expect(computeConversion([], now)).toEqual({
      windowDays: expect.any(Number),
      sample: 0,
      converted: 0,
      percent: null,
      excluded: 0,
    });
  });

  it('excludes test/internal users from the cohort and counts them separately', () => {
    const excluded = new Set([
      'cartermheidt@gmail.com',
      'brooksheidt@gmail.com',
      'dallasheidt@gmail.com',
      'dallas@rightsideuplending.com',
    ]);
    const subs = [
      // Real cohort: 5 users, 4 converted → 80%
      makeSub({ status: 'active', email: 'a@example.com', trialEnd: now - 5 * day }),
      makeSub({ status: 'active', email: 'b@example.com', trialEnd: now - 5 * day }),
      makeSub({ status: 'active', email: 'c@example.com', trialEnd: now - 5 * day }),
      makeSub({ status: 'active', email: 'd@example.com', trialEnd: now - 5 * day }),
      makeSub({ status: 'canceled', email: 'e@example.com', trialEnd: now - 5 * day }),
      // Test users — must NOT be in sample
      makeSub({ status: 'canceled', email: 'cartermheidt@gmail.com', trialEnd: now - 5 * day }),
      makeSub({ status: 'canceled', email: 'dallasheidt@gmail.com', trialEnd: now - 5 * day }),
    ];
    const result = computeConversion(subs, now, excluded);
    expect(result.sample).toBe(5);
    expect(result.converted).toBe(4);
    expect(result.percent).toBe(80);
    expect(result.excluded).toBe(2);
  });

  it('email match is case-insensitive', () => {
    const excluded = new Set(['dallasheidt@gmail.com']);
    const subs = [makeSub({ status: 'canceled', email: 'DallasHeidt@Gmail.com', trialEnd: now - 5 * day })];
    const result = computeConversion(subs, now, excluded);
    expect(result.sample).toBe(0);
    expect(result.excluded).toBe(1);
  });

  it('regression: a 7-day trial that started 10 days ago and converted IS counted', () => {
    // This was the reported bug: the old logic required trial_start to be 31-60d ago,
    // so a recently-converted trial (typical case for a young business) was dropped.
    const subs = Array.from({ length: 9 }, (_, i) =>
      makeSub({ status: 'active', email: `user${i}@example.com`, trialEnd: now - 3 * day })
    );
    const result = computeConversion(subs, now);
    expect(result.sample).toBe(9);
    expect(result.converted).toBe(9);
    expect(result.percent).toBe(100);
  });
});

describe('dedupeEmails', () => {
  it('returns lowercased distinct emails', () => {
    const result = dedupeEmails(['A@b.com', 'a@B.com', 'c@d.com']);
    expect(result.size).toBe(2);
    expect(result.has('a@b.com')).toBe(true);
    expect(result.has('c@d.com')).toBe(true);
  });

  it('trims surrounding whitespace', () => {
    const result = dedupeEmails(['  user@example.com  ', 'user@example.com']);
    expect(result.size).toBe(1);
    expect(result.has('user@example.com')).toBe(true);
  });

  it('skips empty and non-string values', () => {
    const result = dedupeEmails([
      '',
      '   ',
      'real@example.com',
      null as unknown as string,
      undefined as unknown as string,
    ]);
    expect(result.size).toBe(1);
    expect(result.has('real@example.com')).toBe(true);
  });

  it('returns empty set for empty input', () => {
    expect(dedupeEmails([]).size).toBe(0);
  });
});

describe('computeLeadConversion', () => {
  const excluded = new Set<string>(['internal@pitchrank.io']);

  it('counts leads found in active subs as converted', () => {
    const leads = new Set(['paid@example.com', 'free@example.com']);
    const active = [makeSub({ status: 'active', email: 'paid@example.com' })];
    const result = computeLeadConversion(leads, active, [], excluded);
    expect(result.leads).toBe(2);
    expect(result.converted).toBe(1);
    expect(result.percent).toBeNull(); // sample < 5
    expect(result.excluded).toBe(0);
  });

  it('counts leads found in past_due subs as converted', () => {
    const leads = new Set(['dunning@example.com']);
    const pastDue = [makeSub({ status: 'past_due', email: 'dunning@example.com' })];
    const result = computeLeadConversion(leads, [], pastDue, excluded);
    expect(result.converted).toBe(1);
  });

  it('returns rounded percent once sample >= 5', () => {
    const leads = new Set(['a@example.com', 'b@example.com', 'c@example.com', 'd@example.com', 'e@example.com']);
    const active = [
      makeSub({ status: 'active', email: 'a@example.com' }),
      makeSub({ status: 'active', email: 'b@example.com' }),
    ];
    const result = computeLeadConversion(leads, active, [], excluded);
    expect(result.leads).toBe(5);
    expect(result.converted).toBe(2);
    expect(result.percent).toBe(40);
  });

  it('drops excluded emails from both numerator and denominator', () => {
    const leads = new Set(['internal@pitchrank.io', 'real@example.com']);
    const active = [
      makeSub({ status: 'active', email: 'internal@pitchrank.io' }),
      makeSub({ status: 'active', email: 'real@example.com' }),
    ];
    const result = computeLeadConversion(leads, active, [], excluded);
    expect(result.leads).toBe(1);
    expect(result.converted).toBe(1);
    expect(result.excluded).toBe(1);
  });

  it('matches case-insensitively', () => {
    const leads = new Set(['mixed@example.com']);
    const active = [makeSub({ status: 'active', email: 'MIXED@Example.com' })];
    const result = computeLeadConversion(leads, active, [], excluded);
    expect(result.converted).toBe(1);
  });

  it('returns zero/null when no leads', () => {
    const result = computeLeadConversion(new Set(), [], [], excluded);
    expect(result).toEqual({ leads: 0, converted: 0, percent: null, excluded: 0 });
  });
});

describe('computeLeadToTrial', () => {
  const excluded = new Set<string>(['internal@pitchrank.io']);
  const start = 1_700_000_000;

  it('counts a lead whose email ever started a trial', () => {
    const leads = new Set(['trialer@example.com', 'never@example.com']);
    const subs = [makeSub({ status: 'trialing', email: 'trialer@example.com', trialStart: start })];
    const result = computeLeadToTrial(leads, subs, excluded);
    expect(result.leads).toBe(2);
    expect(result.trialed).toBe(1);
    expect(result.percent).toBeNull(); // sample < 5
    expect(result.excluded).toBe(0);
  });

  it('counts a lead who trialed and later cancelled', () => {
    // marina case: started a trial, then cancelled → sub is now canceled but
    // still has trial_start, so she counts as having trialed.
    const leads = new Set(['marina@example.com']);
    const subs = [makeSub({ status: 'canceled', email: 'marina@example.com', trialStart: start })];
    const result = computeLeadToTrial(leads, subs, excluded);
    expect(result.trialed).toBe(1);
  });

  it('does not count a paid lead who never trialed', () => {
    const leads = new Set(['direct@example.com']);
    const subs = [makeSub({ status: 'active', email: 'direct@example.com', trialStart: null })];
    const result = computeLeadToTrial(leads, subs, excluded);
    expect(result.trialed).toBe(0);
  });

  it('returns rounded percent once sample >= 5', () => {
    const leads = new Set(['a@example.com', 'b@example.com', 'c@example.com', 'd@example.com', 'e@example.com']);
    const subs = [
      makeSub({ status: 'trialing', email: 'a@example.com', trialStart: start }),
      makeSub({ status: 'canceled', email: 'b@example.com', trialStart: start }),
    ];
    const result = computeLeadToTrial(leads, subs, excluded);
    expect(result.leads).toBe(5);
    expect(result.trialed).toBe(2);
    expect(result.percent).toBe(40);
  });

  it('drops excluded emails from both numerator and denominator', () => {
    const leads = new Set(['internal@pitchrank.io', 'real@example.com']);
    const subs = [
      makeSub({ status: 'trialing', email: 'internal@pitchrank.io', trialStart: start }),
      makeSub({ status: 'trialing', email: 'real@example.com', trialStart: start }),
    ];
    const result = computeLeadToTrial(leads, subs, excluded);
    expect(result.leads).toBe(1);
    expect(result.trialed).toBe(1);
    expect(result.excluded).toBe(1);
  });

  it('matches case-insensitively', () => {
    const leads = new Set(['mixed@example.com']);
    const subs = [makeSub({ status: 'canceled', email: 'MIXED@Example.com', trialStart: start })];
    const result = computeLeadToTrial(leads, subs, excluded);
    expect(result.trialed).toBe(1);
  });

  it('an excluded email trial sub does not bleed into another lead', () => {
    // The trialed set is built before exclusion, so an excluded email's trial
    // sub lands in it — but matching is by exact email, so it must not inflate
    // a different, non-trialing lead's count.
    const leads = new Set(['internal@pitchrank.io', 'real@example.com']);
    const subs = [makeSub({ status: 'trialing', email: 'internal@pitchrank.io', trialStart: start })];
    const result = computeLeadToTrial(leads, subs, excluded);
    expect(result.leads).toBe(1); // only real@ counts toward denominator
    expect(result.trialed).toBe(0); // real@ never trialed; excluded sub doesn't bleed over
    expect(result.excluded).toBe(1);
  });

  it('returns zero/null when no leads', () => {
    const result = computeLeadToTrial(new Set(), [], excluded);
    expect(result).toEqual({ leads: 0, trialed: 0, percent: null, excluded: 0 });
  });
});
