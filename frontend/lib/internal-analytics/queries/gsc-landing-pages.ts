// frontend/lib/internal-analytics/queries/gsc-landing-pages.ts
import 'server-only';
import { unstable_cache } from 'next/cache';
import { getSearchConsoleClient } from '@/lib/google-auth';
import { GSC_SITE_URL, CACHE_TTL_SECONDS, DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT } from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, rangeDays, todayInPropertyTz } from '../dates';
import { gscRowsToObjects } from '../transforms/gsc';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';

export type GscLandingPagesParams = {
  dateRange: DateRange;
  limit?: number;
  forceFresh?: boolean;
  timezone?: string;
};

export type GscLandingPagesRow = {
  page: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
};

function snapEnd(range: DateRange, tz: string) {
  const today = todayInPropertyTz(tz);
  const cutoff = new Date(Date.parse(today + 'T00:00:00Z') - 2 * 86_400_000).toISOString().slice(0, 10);
  return range.end > cutoff ? { range: { ...range, end: cutoff }, snapped: true } : { range, snapped: false };
}

async function fetchRaw(range: DateRange, limit: number) {
  try {
    const client = getSearchConsoleClient();
    const res = await client.searchanalytics.query({
      siteUrl: GSC_SITE_URL,
      requestBody: { startDate: range.start, endDate: range.end, dimensions: ['page'], rowLimit: limit },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: GscLandingPagesParams): Promise<TileResponse<GscLandingPagesRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const resolved = resolveDateRange(params.dateRange, tz);
  const limit = Math.min(params.limit ?? DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT);
  const { range, snapped } = snapEnd(resolved, tz);

  const raw = await fetchRaw(range, limit);
  const rows = gscRowsToObjects(raw as never, ['page']).map((r) => ({
    page: String(r.page),
    clicks: Number(r.clicks ?? 0),
    impressions: Number(r.impressions ?? 0),
    ctr: Number(r.ctr ?? 0),
    position: Number(r.position ?? 0),
  }));
  const totals = {
    clicks: rows.reduce((s, r) => s + r.clicks, 0),
    impressions: rows.reduce((s, r) => s + r.impressions, 0),
    ctr: 0,
    position: 0,
  };
  totals.ctr = totals.impressions === 0 ? 0 : totals.clicks / totals.impressions;
  totals.position = rows.length === 0 ? 0 : rows.reduce((s, r) => s + r.position, 0) / rows.length;

  const fresh = detectFreshness('gsc', range, tz);
  const warnings = [...fresh.warnings];
  if (snapped) warnings.unshift(`End date snapped to ${range.end} due to GSC reporting lag.`);

  return {
    report: 'gsc_landing_pages',
    source: 'gsc',
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals,
    derived: {},
    truncated: rows.length >= limit,
    truncation_reason: rows.length >= limit ? 'limit_reached' : undefined,
    data_freshness: fresh.freshness,
    warnings,
    generated_at: new Date().toISOString(),
    debug: { cost: { estimated_units: 1, range_days: rangeDays(range), metric_count: 4, dimension_count: 1, limit } },
  };
}

export function getGscLandingPages(params: GscLandingPagesParams): Promise<TileResponse<GscLandingPagesRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `gsc_landing_pages:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['gsc_landing_pages', sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:gsc', 'analytics:gsc_landing_pages'],
  })();
}
