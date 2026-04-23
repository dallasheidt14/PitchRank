import 'server-only';
import { unstable_cache } from 'next/cache';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import { GA4_PROPERTY_ID, CACHE_TTL_SECONDS, DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT } from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, rangeDays } from '../dates';
import { ga4RowsToObjects } from '../transforms/ga4';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';

export type Ga4TrafficSourcesParams = {
  dateRange: DateRange;
  limit?: number;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4TrafficSourcesRow = {
  source: string;
  medium: string;
  sessions: number;
  activeUsers: number;
  engagementRate: number;
};

async function fetchRaw(range: DateRange, limit: number) {
  try {
    const client = getAnalyticsDataClient();
    const res = await client.properties.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      requestBody: {
        dateRanges: [{ startDate: range.start, endDate: range.end }],
        dimensions: [{ name: 'sessionSource' }, { name: 'sessionMedium' }],
        metrics: [{ name: 'sessions' }, { name: 'activeUsers' }, { name: 'engagementRate' }],
        orderBys: [{ metric: { metricName: 'sessions' }, desc: true }],
        limit: String(limit),
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: Ga4TrafficSourcesParams): Promise<TileResponse<Ga4TrafficSourcesRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const range = resolveDateRange(params.dateRange, tz);
  const limit = Math.min(params.limit ?? DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT);

  const raw = await fetchRaw(range, limit);
  const rows = ga4RowsToObjects(raw as never).map((r) => ({
    source: String(r.sessionSource ?? '(unknown)'),
    medium: String(r.sessionMedium ?? '(none)'),
    sessions: Number(r.sessions ?? 0),
    activeUsers: Number(r.activeUsers ?? 0),
    engagementRate: Number(r.engagementRate ?? 0),
  }));
  const totals = rows.reduce(
    (acc, r) => ({
      sessions: acc.sessions + r.sessions,
      activeUsers: acc.activeUsers + r.activeUsers,
    }),
    { sessions: 0, activeUsers: 0 }
  );
  const fresh = detectFreshness('ga4', range, tz);

  return {
    report: 'ga4_traffic_sources',
    source: 'ga4',
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals,
    derived: {},
    truncated: rows.length >= limit,
    truncation_reason: rows.length >= limit ? 'limit_reached' : undefined,
    data_freshness: fresh.freshness,
    warnings: fresh.warnings,
    generated_at: new Date().toISOString(),
    debug: {
      cost: {
        estimated_units: rangeDays(range) * 2,
        range_days: rangeDays(range),
        metric_count: 3,
        dimension_count: 2,
        limit,
      },
    },
  };
}

export function getGa4TrafficSources(params: Ga4TrafficSourcesParams): Promise<TileResponse<Ga4TrafficSourcesRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `ga4_traffic_sources:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['ga4_traffic_sources', sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:ga4', 'analytics:ga4_traffic_sources'],
  })();
}
