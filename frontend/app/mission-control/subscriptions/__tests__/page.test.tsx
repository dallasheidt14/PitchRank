import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ReactElement, ReactNode } from 'react';
import type { SubscriptionMetrics } from '@/lib/admin/subscription-metrics';

const getSubscriptionMetrics = vi.fn();
vi.mock('@/lib/admin/subscription-metrics', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/admin/subscription-metrics')>();
  return { ...actual, getSubscriptionMetrics: () => getSubscriptionMetrics() };
});

import SubscriptionsDashboardPage from '../page';

/**
 * Flatten a server component's element tree to its visible text.
 *
 * The numbers are covered by the metric suites; what these tests guard is the
 * sentence rendered beside them, because an inverted availability branch tells
 * the operator that no invoices are outstanding when the fetch simply failed.
 */
function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join(' ');
  const element = node as ReactElement<{ children?: ReactNode }>;
  if (typeof element === 'object' && 'props' in element && typeof element.type === 'function') {
    return textOf((element.type as (props: unknown) => ReactNode)(element.props));
  }
  if (typeof element === 'object' && 'props' in element) {
    return Object.values(element.props ?? {})
      .map((value) =>
        typeof value === 'string' || typeof value === 'number' ? String(value) : textOf(value as ReactNode)
      )
      .join(' ');
  }
  return '';
}

function metrics(over: Partial<SubscriptionMetrics> = {}): SubscriptionMetrics {
  const rate = { rate: 0.5, observed: 10, sample: 20, excluded: 0, isFallback: false };
  return {
    mrr: 403.19,
    activePaid: { total: 60, monthly: 46, annual: 14 },
    trials: { total: 15, canceledPending: 0, endingIn3Days: 2, endingIn7Days: 5, list: [] },
    conversion: { windowDays: 180, sample: 20, converted: 10, percent: 50, excluded: 0, retained: 7 },
    lastMonth: { available: true, label: 'September 2026', sample: 12, converted: 6, retained: 5, excluded: 0 },
    twoMonthsAgo: { available: true, label: 'August 2026', sample: 10, converted: 4, retained: 1, excluded: 0 },
    lifetimeChurn: { available: true, paid: 80, churned: 20 },
    mrrGrowth: { available: true, label: 'September 2026', from: 380, to: 403.19, change: 23.19, percent: 6.1 },
    reportCard: {
      totalRequests: 0,
      uniqueEmails: 0,
      last7Days: 0,
      last30Days: 0,
      conversion: { leads: 0, converted: 0, percent: null, excluded: 0 },
      trialConversion: { leads: 0, trialed: 0, percent: null, excluded: 0 },
      recentLeads: [],
    },
    monthProjection: {
      available: true,
      trials: {
        trialsToDate: 11,
        daysElapsed: 4,
        dayOfMonth: 5,
        daysInMonth: 30,
        dailyRate: 2.75,
        projected: 82.5,
        low: 51,
        high: 114,
        landedConverted: 3,
        landingUnresolved: 60,
      },
      conversion: rate,
      churn: rate,
      arpu: 6.78,
      grossNewSubs: 33,
      grossNewMrr: 223.74,
      observedChurn: 1,
      churnedSubs: 5,
      annualRenewalsAhead: 0,
      lostMrr: 33.9,
      netSubs: 28,
      netMrr: 189.84,
      cohortSubs: 41,
      cohortMrr: 277.98,
      avgLifetimeMonths: 6.2,
      ltv: 42.16,
      cohortValue: 1728,
    },
    generatedAt: new Date('2026-09-04T12:00:00Z').toISOString(),
    errors: [],
    ...over,
  } as SubscriptionMetrics;
}

beforeEach(() => getSubscriptionMetrics.mockReset());

describe('SubscriptionsDashboardPage', () => {
  it('dates the page in the business timezone, not the UTC the server runs in', async () => {
    // 00:33 UTC on Sept 6 is 5:33pm on Sept 5 in Phoenix. Rendered unzoned this
    // read as the 6th to an operator for whom it was still the 5th.
    getSubscriptionMetrics.mockReturnValue(metrics({ generatedAt: '2026-09-06T00:33:00.000Z' }));
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('9/5/2026');
    expect(text).not.toContain('9/6/2026');
    // Named on the page so the reader never has to guess which clock it is.
    expect(text).toContain('MST');
  });

  it('names the month the operator is still in on the last evening of it', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics({ generatedAt: '2026-10-01T02:00:00.000Z' }));
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('September');
    expect(text).not.toContain('October');
  });

  it('labels the projection with the calendar day, not the elapsed fraction', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('day 5 of 30');
  });

  it('describes MRR the way Stripe counts it', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('active + past due, less scheduled cancellations');
  });

  it('shows MRR as not loaded rather than a partial sum when a fetch failed', async () => {
    getSubscriptionMetrics.mockReturnValue(
      metrics({ mrr: null, errors: ['past_due subscriptions: stripe unavailable'] })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('could not be loaded');
    expect(text).not.toContain('active + past due, less scheduled cancellations');
  });

  it("shows last month's trial conversion and how many of those converts are still subscribed", async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('Last Month');
    expect(text).toContain('September 2026');
    expect(text).toContain('50%');
    expect(text).toContain('6 of 12 trials started in September 2026');
    expect(text).toContain('83%');
    expect(text).toContain('5 of those 6 paid subscribers');
  });

  it('shows the same two cards for the month before last', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('2 Months Ago');
    expect(text).toContain('4 of 10 trials started in August 2026');
    expect(text).toContain('40%');
    expect(text).toContain('1 of those 4 paid subscribers');
    expect(text).toContain('25%');
  });

  it('splits active paid subscribers into monthly and annual shares', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('46 monthly (77%) · 14 annual (23%)');
  });

  it('shows a dash for the monthly and annual shares when there are no paid subscribers', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics({ activePaid: { total: 0, monthly: 0, annual: 0 } }));
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('0 monthly (—) · 0 annual (—)');
  });

  it('shows all-time churn among everyone who ever paid', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('25%');
    expect(text).toContain('20 of 80 subscribers who ever paid have since canceled');
  });

  it('shows monthly MRR growth in dollars and percent', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('Monthly Growth · September 2026');
    expect(text).toContain('+$23.19 | +6.1%');
    expect(text).toContain('MRR $380.00 at the start of September 2026 → $403.19 a month later');
  });

  it('signs a shrinking month negative', async () => {
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        mrrGrowth: { available: true, label: 'September 2026', from: 400, to: 390, change: -10, percent: -2.5 },
      })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('−$10.00 | −2.5%');
  });

  it('shows a flat month as +0%, and a dash when there was no MRR to grow from', async () => {
    getSubscriptionMetrics.mockReturnValue(
      metrics({ mrrGrowth: { available: true, label: 'September 2026', from: 400, to: 400, change: 0, percent: 0 } })
    );
    expect(textOf(await SubscriptionsDashboardPage())).toContain('+$0.00 | +0%');
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        mrrGrowth: { available: true, label: 'September 2026', from: 0, to: 6.99, change: 6.99, percent: null },
      })
    );
    expect(textOf(await SubscriptionsDashboardPage())).toContain('+$6.99 | —');
  });

  it('marks churn unavailable on its own card', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics({ lifetimeChurn: { available: false, paid: 0, churned: 0 } }));
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toMatch(/Churn · all time[^%$]*—[^%$]*could not be loaded/);
    expect(text).not.toContain('subscribers who ever paid');
    expect(text).toContain('+$23.19 | +6.1%');
  });

  it('marks growth unavailable on its own card', async () => {
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        mrrGrowth: { available: false, label: 'September 2026', from: 0, to: 0, change: 0, percent: null },
      })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toMatch(/Monthly Growth · September 2026[^%$]*—[^%$]*could not be loaded/);
    expect(text).not.toContain('at the start of September');
    expect(text).toContain('20 of 80 subscribers who ever paid');
  });

  it('hides 180-day retention while the conversion card above says there is not enough data', async () => {
    getSubscriptionMetrics.mockReturnValue(
      metrics({ conversion: { windowDays: 180, sample: 3, converted: 1, percent: null, excluded: 0, retained: 1 } })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('Not enough data yet');
    expect(text).not.toContain('Retention · last');
  });

  it('shows retention over the 180-day conversion cohort', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('Retention · last');
    expect(text).toContain('70%');
    expect(text).toContain('7 of those 10 paid subscribers');
  });

  it('shows a dash rather than NaN when last month had no trials to divide by', async () => {
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        lastMonth: { available: true, label: 'September 2026', sample: 0, converted: 0, retained: 0, excluded: 0 },
      })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('—');
    expect(text).not.toContain('NaN');
  });

  it('marks last month unavailable rather than printing zeros when its fetch failed', async () => {
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        lastMonth: { available: false, label: 'September 2026', sample: 0, converted: 0, retained: 0, excluded: 0 },
        twoMonthsAgo: { available: false, label: 'August 2026', sample: 0, converted: 0, retained: 0, excluded: 0 },
      })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('could not be loaded');
    expect(text).not.toContain('Trial → Paid');
  });

  it('does not show unpaid invoice or past-due lists', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).not.toContain('Unpaid Invoices');
    expect(text).not.toContain('Attention Needed');
  });

  it('marks the projection unavailable rather than printing its zeros', async () => {
    const base = metrics();
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        monthProjection: { ...base.monthProjection, available: false },
        errors: ['conversion cohort: stripe unavailable'],
      })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('could not be loaded');
    // The figures must go with it. Printing them under that heading is how a
    // failed fetch turns into a plausible-looking forecast.
    expect(text).not.toContain('Projected Trials');
    expect(text).not.toContain('New Subs This Month');
    expect(text).toContain('nothing to show');
  });

  it('renders LTV as not measurable rather than as zero when nobody has churned', async () => {
    const base = metrics();
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        monthProjection: { ...base.monthProjection, avgLifetimeMonths: null, ltv: null, cohortValue: null },
      })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('not measurable');
    expect(text).not.toContain('$0.00');
  });

  it('says when a rate is a historical fallback rather than a measurement', async () => {
    const base = metrics();
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        monthProjection: {
          ...base.monthProjection,
          churn: { rate: 0.2568, observed: 1, sample: 3, excluded: 0, isFallback: true },
        },
      })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('historical fallback');
  });
});
