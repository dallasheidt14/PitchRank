// frontend/lib/internal-analytics/report-registry.ts
import 'server-only';
import { z } from 'zod';
import type { DateRangePreset } from './types';
import { DATE_RANGE_PRESETS, MAX_ROW_LIMIT } from './constants';
import { getGa4Overview } from './queries/ga4-overview';
import { getGa4TopPages, type Ga4TopPagesParams } from './queries/ga4-top-pages';
import { getGa4UpgradeViews, type Ga4UpgradeViewsParams } from './queries/ga4-upgrade-views';
import { getGscPerformance, type GscPerformanceParams } from './queries/gsc-performance';
import { getGscTopQueries, type GscTopQueriesParams } from './queries/gsc-top-queries';
import { getGscLandingPages, type GscLandingPagesParams } from './queries/gsc-landing-pages';

const DateRangeSchema = z.union([
  z.enum(DATE_RANGE_PRESETS as readonly [DateRangePreset, ...DateRangePreset[]]),
  z.object({ start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/), end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/) }),
]);

const Common = {
  date_range: DateRangeSchema,
  compare_to_previous: z.boolean().optional(),
  forceFresh: z.boolean().optional(),
};

type CommonParams = {
  date_range: DateRangePreset | { start: string; end: string };
  compare_to_previous?: boolean;
  forceFresh?: boolean;
};

type WithLimit = CommonParams & { limit?: number };

export const REPORTS = {
  ga4_traffic_overview: {
    source: 'ga4',
    description: 'Sessions, active users, and pageviews over time with totals and trend.',
    paramsSchema: z.object({ ...Common }),
    handler: (p: CommonParams) =>
      getGa4Overview({
        dateRange: p.date_range as never,
        compareToPrevious: p.compare_to_previous,
        forceFresh: p.forceFresh,
      }),
    summaryRequired: ['totals', 'trend_direction'],
    derivedMetrics: ['sessions_delta', 'trend_direction'],
  },
  ga4_top_pages: {
    source: 'ga4',
    description: 'Top pages by pageviews with engagement rate.',
    paramsSchema: z.object({ ...Common, limit: z.number().int().min(1).max(MAX_ROW_LIMIT).optional() }),
    handler: (p: WithLimit) =>
      getGa4TopPages({ dateRange: p.date_range, limit: p.limit, forceFresh: p.forceFresh } as Ga4TopPagesParams),
    summaryRequired: ['totals'],
  },
  ga4_upgrade_views: {
    source: 'ga4',
    description: 'Pageviews of /upgrade and conversion rate vs total sessions.',
    paramsSchema: z.object({ ...Common }),
    handler: (p: CommonParams) =>
      getGa4UpgradeViews({
        dateRange: p.date_range,
        compareToPrevious: p.compare_to_previous,
        forceFresh: p.forceFresh,
      } as Ga4UpgradeViewsParams),
    summaryRequired: ['totals', 'conversion_rate'],
    derivedMetrics: ['conversion_rate'],
  },
  gsc_performance: {
    source: 'gsc',
    description: 'Clicks, impressions, CTR, and position over time with period-over-period deltas.',
    paramsSchema: z.object({ ...Common }),
    handler: (p: CommonParams) =>
      getGscPerformance({
        dateRange: p.date_range,
        compareToPrevious: p.compare_to_previous,
        forceFresh: p.forceFresh,
      } as GscPerformanceParams),
    summaryRequired: ['totals', 'ctr_delta', 'impressions_delta', 'position_delta'],
  },
  gsc_top_queries: {
    source: 'gsc',
    description: 'Top search queries by clicks with CTR and average position.',
    paramsSchema: z.object({ ...Common, limit: z.number().int().min(1).max(MAX_ROW_LIMIT).optional() }),
    handler: (p: WithLimit) =>
      getGscTopQueries({ dateRange: p.date_range, limit: p.limit, forceFresh: p.forceFresh } as GscTopQueriesParams),
    summaryRequired: ['totals'],
  },
  gsc_landing_pages: {
    source: 'gsc',
    description: 'Top landing pages receiving search traffic (may display as Index Coverage in UI).',
    paramsSchema: z.object({ ...Common, limit: z.number().int().min(1).max(MAX_ROW_LIMIT).optional() }),
    handler: (p: WithLimit) =>
      getGscLandingPages({
        dateRange: p.date_range,
        limit: p.limit,
        forceFresh: p.forceFresh,
      } as GscLandingPagesParams),
    experimental: true,
  },
} as const;

export type ReportKey = keyof typeof REPORTS;

export async function runReport(key: ReportKey, params: unknown) {
  const report = REPORTS[key];
  const validated = report.paramsSchema.parse(params);
  return report.handler(validated as never);
}
