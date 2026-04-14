// frontend/lib/internal-analytics/queries/ga4-overview.ts
import 'server-only';
import { unstable_cache } from 'next/cache';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import { GA4_PROPERTY_ID, CACHE_TTL_SECONDS } from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, previousPeriod, rangeDays } from '../dates';
import { ga4RowsToObjects } from '../transforms/ga4';
import { computeTrend, pctDelta } from '../transforms/trend';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';

export type Ga4OverviewParams = {
  dateRange: DateRange;
  compareToPrevious?: boolean;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4OverviewRow = {
  date: string;
  sessions: number;
  activeUsers: number;
  screenPageViews: number;
};

async function fetchOverviewRaw(range: DateRange): Promise<unknown> {
  try {
    const client = getAnalyticsDataClient();
    const res = await client.properties.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      requestBody: {
        dateRanges: [{ startDate: range.start, endDate: range.end }],
        dimensions: [{ name: 'date' }],
        metrics: [{ name: 'sessions' }, { name: 'activeUsers' }, { name: 'screenPageViews' }],
        orderBys: [{ dimension: { dimensionName: 'date' } }],
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

function normalize(
  raw: unknown,
  range: DateRange,
  timezone: string,
  previous?: { raw: unknown; range: DateRange }
): TileResponse<Ga4OverviewRow> {
  const rows = ga4RowsToObjects(raw as never).map((r) => ({
    date: String(r.date),
    sessions: Number(r.sessions ?? 0),
    activeUsers: Number(r.activeUsers ?? 0),
    screenPageViews: Number(r.screenPageViews ?? 0),
  }));

  const totals = rows.reduce(
    (acc, r) => ({
      sessions: acc.sessions + r.sessions,
      activeUsers: acc.activeUsers + r.activeUsers,
      screenPageViews: acc.screenPageViews + r.screenPageViews,
    }),
    { sessions: 0, activeUsers: 0, screenPageViews: 0 }
  );

  const trend = computeTrend(rows.map((r) => r.sessions));
  const fresh = detectFreshness('ga4', range, timezone);

  let previous_period: TileResponse<Ga4OverviewRow>['previous_period'] | undefined;
  let derived: Record<string, number | string> = {
    trend_direction: trend.trend_direction,
    trend_strength: trend.trend_strength,
  };

  if (previous) {
    const prevRows = ga4RowsToObjects(previous.raw as never).map((r) => ({
      date: String(r.date),
      sessions: Number(r.sessions ?? 0),
      activeUsers: Number(r.activeUsers ?? 0),
      screenPageViews: Number(r.screenPageViews ?? 0),
    }));
    const prevTotals = prevRows.reduce(
      (acc, r) => ({
        sessions: acc.sessions + r.sessions,
        activeUsers: acc.activeUsers + r.activeUsers,
        screenPageViews: acc.screenPageViews + r.screenPageViews,
      }),
      { sessions: 0, activeUsers: 0, screenPageViews: 0 }
    );
    derived = {
      ...derived,
      sessions_delta: pctDelta(totals.sessions, prevTotals.sessions),
      users_delta: pctDelta(totals.activeUsers, prevTotals.activeUsers),
      pageviews_delta: pctDelta(totals.screenPageViews, prevTotals.screenPageViews),
    };
    previous_period = { rows: prevRows, totals: prevTotals, derived: {} };
  }

  return {
    report: 'ga4_traffic_overview',
    source: 'ga4',
    date_range: range,
    timezone,
    rows,
    row_count: rows.length,
    totals,
    derived,
    previous_period,
    truncated: false,
    data_freshness: fresh.freshness,
    warnings: fresh.warnings,
    generated_at: new Date().toISOString(),
    debug: {
      cost: {
        estimated_units: rangeDays(range),
        range_days: rangeDays(range),
        metric_count: 3,
        dimension_count: 1,
        limit: 0,
      },
    },
  };
}

async function runOnce(params: Ga4OverviewParams): Promise<TileResponse<Ga4OverviewRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const range = resolveDateRange(params.dateRange, tz);

  if (params.compareToPrevious && rangeDays(range) > 90) {
    throw new TaxonomyAwareError({
      type: 'VALIDATION',
      retryable: false,
      message: 'Comparison disabled for ranges over 90 days (doubles API calls).',
    });
  }

  if (params.compareToPrevious) {
    const prevRange = previousPeriod(range);
    const [raw, prevRaw] = await Promise.all([fetchOverviewRaw(range), fetchOverviewRaw(prevRange)]);
    return normalize(raw, range, tz, { raw: prevRaw, range: prevRange });
  }
  const raw = await fetchOverviewRaw(range);
  return normalize(raw, range, tz);
}

export function getGa4Overview(params: Ga4OverviewParams): Promise<TileResponse<Ga4OverviewRow>> {
  const key = `ga4_overview:${sortedKeys({ ...params, forceFresh: undefined })}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['ga4_overview', sortedKeys({ ...params, forceFresh: undefined })], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:ga4', 'analytics:ga4_overview'],
  })();
}
