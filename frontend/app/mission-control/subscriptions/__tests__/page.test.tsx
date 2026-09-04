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
    pastDue: { total: 0, list: [] },
    conversion: { windowDays: 180, sample: 20, converted: 10, percent: 50, excluded: 0 },
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
    unpaidInvoices: { available: true, total: 0, outstanding: 0, noRetryScheduled: 0, list: [] },
    generatedAt: new Date('2026-09-04T12:00:00Z').toISOString(),
    errors: [],
    ...over,
  } as SubscriptionMetrics;
}

beforeEach(() => getSubscriptionMetrics.mockReset());

describe('SubscriptionsDashboardPage', () => {
  it('says every charge cleared only when the fetch actually succeeded', async () => {
    getSubscriptionMetrics.mockReturnValue(metrics());
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).toContain('Every charge cleared');
  });

  it('does not claim every charge cleared when the invoice fetch failed', async () => {
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        unpaidInvoices: { available: false, total: 0, outstanding: 0, noRetryScheduled: 0, list: [] },
        errors: ['open invoices: stripe unavailable'],
      })
    );
    const text = textOf(await SubscriptionsDashboardPage());
    expect(text).not.toContain('Every charge cleared');
    expect(text).toContain('unknown rather than empty');
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
  });

  it('renders LTV as not measurable rather than as zero when nobody has churned', async () => {
    const base = metrics();
    getSubscriptionMetrics.mockReturnValue(
      metrics({
        monthProjection: { ...base.monthProjection, avgLifetimeMonths: null, ltv: null, cohortValue: null },
        // Non-zero so a stray "$0.00" can only have come from the LTV card.
        unpaidInvoices: { available: true, total: 1, outstanding: 769.53, noRetryScheduled: 1, list: [] },
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
