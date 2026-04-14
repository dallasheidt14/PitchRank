// frontend/lib/internal-analytics/queries/gsc-performance.ts
import 'server-only';
import { unstable_cache } from 'next/cache';
import { getSearchConsoleClient } from '@/lib/google-auth';
import { GSC_SITE_URL, CACHE_TTL_SECONDS } from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, rangeDays, previousPeriod, todayInPropertyTz } from '../dates';
import { gscRowsToObjects, computeGscDeltas } from '../transforms/gsc';
import { computeTrend } from '../transforms/trend';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';

export type GscPerformanceParams = {
  dateRange: DateRange;
  compareToPrevious?: boolean;
  forceFresh?: boolean;
  timezone?: string;
};

export type GscPerformanceRow = {
  date: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
};

function snapEndDate(range: DateRange, tz: string): { range: DateRange; snapped: boolean } {
  const today = todayInPropertyTz(tz);
  const cutoff = new Date(Date.parse(today + 'T00:00:00Z') - 2 * 86_400_000).toISOString().slice(0, 10);
  if (range.end > cutoff) return { range: { ...range, end: cutoff }, snapped: true };
  return { range, snapped: false };
}

async function fetchRaw(range: DateRange) {
  try {
    const client = getSearchConsoleClient();
    const res = await client.searchanalytics.query({
      siteUrl: GSC_SITE_URL,
      requestBody: {
        startDate: range.start,
        endDate: range.end,
        dimensions: ['date'],
        rowLimit: 25_000,
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: GscPerformanceParams): Promise<TileResponse<GscPerformanceRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const resolved = resolveDateRange(params.dateRange, tz);
  if (params.compareToPrevious && rangeDays(resolved) > 90) {
    throw new TaxonomyAwareError({
      type: 'VALIDATION',
      retryable: false,
      message: 'Comparison disabled for ranges over 90 days (doubles API calls).',
    });
  }

  const { range, snapped } = snapEndDate(resolved, tz);

  const [raw, prevRaw] = params.compareToPrevious
    ? await Promise.all([fetchRaw(range), fetchRaw(previousPeriod(range))])
    : [await fetchRaw(range), undefined];

  const rows = gscRowsToObjects(raw as never, ['date']).map((r) => ({
    date: String(r.date),
    clicks: Number(r.clicks ?? 0),
    impressions: Number(r.impressions ?? 0),
    ctr: Number(r.ctr ?? 0),
    position: Number(r.position ?? 0),
  }));
  const totals = rows.reduce(
    (acc, r) => ({
      clicks: acc.clicks + r.clicks,
      impressions: acc.impressions + r.impressions,
      ctr: 0, // recomputed below
      position: 0,
    }),
    { clicks: 0, impressions: 0, ctr: 0, position: 0 }
  );
  totals.ctr = totals.impressions === 0 ? 0 : totals.clicks / totals.impressions;
  totals.position = rows.length === 0 ? 0 : rows.reduce((s, r) => s + r.position, 0) / rows.length;

  const trend = computeTrend(rows.map((r) => r.clicks));
  let derived: Record<string, number | string> = {
    trend_direction: trend.trend_direction,
    trend_strength: trend.trend_strength,
  };
  let previous_period: TileResponse<GscPerformanceRow>['previous_period'];

  if (prevRaw) {
    const prevRows = gscRowsToObjects(prevRaw as never, ['date']).map((r) => ({
      date: String(r.date),
      clicks: Number(r.clicks ?? 0),
      impressions: Number(r.impressions ?? 0),
      ctr: Number(r.ctr ?? 0),
      position: Number(r.position ?? 0),
    }));
    const prevTotals = {
      clicks: prevRows.reduce((s, r) => s + r.clicks, 0),
      impressions: prevRows.reduce((s, r) => s + r.impressions, 0),
      ctr: 0,
      position: 0,
    };
    prevTotals.ctr = prevTotals.impressions === 0 ? 0 : prevTotals.clicks / prevTotals.impressions;
    prevTotals.position = prevRows.length === 0 ? 0 : prevRows.reduce((s, r) => s + r.position, 0) / prevRows.length;
    derived = { ...derived, ...computeGscDeltas(totals, prevTotals) };
    previous_period = { rows: prevRows, totals: prevTotals, derived: {} };
  }

  const fresh = detectFreshness('gsc', range, tz);
  const warnings = [...fresh.warnings];
  if (snapped) warnings.unshift(`End date snapped to ${range.end} due to GSC reporting lag.`);

  return {
    report: 'gsc_performance',
    source: 'gsc',
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals,
    derived,
    previous_period,
    truncated: false,
    data_freshness: fresh.freshness,
    warnings,
    generated_at: new Date().toISOString(),
    debug: {
      cost: {
        estimated_units: rangeDays(range),
        range_days: rangeDays(range),
        metric_count: 4,
        dimension_count: 1,
        limit: 25_000,
      },
    },
  };
}

export function getGscPerformance(params: GscPerformanceParams): Promise<TileResponse<GscPerformanceRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `gsc_performance:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['gsc_performance', sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:gsc', 'analytics:gsc_performance'],
  })();
}
