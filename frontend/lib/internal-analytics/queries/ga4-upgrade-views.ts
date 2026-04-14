// frontend/lib/internal-analytics/queries/ga4-upgrade-views.ts
import 'server-only';
import { unstable_cache } from 'next/cache';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import { GA4_PROPERTY_ID, CACHE_TTL_SECONDS } from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, rangeDays, previousPeriod } from '../dates';
import { ga4RowsToObjects } from '../transforms/ga4';
import { pctDelta } from '../transforms/trend';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';

export type Ga4UpgradeViewsParams = {
  dateRange: DateRange;
  compareToPrevious?: boolean;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4UpgradeViewsRow = {
  date: string;
  upgradeViews: number;
  totalSessions: number;
};

async function fetchRaw(range: DateRange) {
  const client = getAnalyticsDataClient();
  try {
    const [upgrade, total] = await Promise.all([
      client.properties.runReport({
        property: `properties/${GA4_PROPERTY_ID}`,
        requestBody: {
          dateRanges: [{ startDate: range.start, endDate: range.end }],
          dimensions: [{ name: 'date' }],
          metrics: [{ name: 'screenPageViews' }],
          dimensionFilter: {
            filter: { fieldName: 'pagePath', stringFilter: { matchType: 'EXACT', value: '/upgrade' } },
          },
          orderBys: [{ dimension: { dimensionName: 'date' } }],
        },
      }),
      client.properties.runReport({
        property: `properties/${GA4_PROPERTY_ID}`,
        requestBody: {
          dateRanges: [{ startDate: range.start, endDate: range.end }],
          dimensions: [{ name: 'date' }],
          metrics: [{ name: 'sessions' }],
          orderBys: [{ dimension: { dimensionName: 'date' } }],
        },
      }),
    ]);
    return { upgrade: upgrade.data, total: total.data };
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: Ga4UpgradeViewsParams): Promise<TileResponse<Ga4UpgradeViewsRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const range = resolveDateRange(params.dateRange, tz);

  if (params.compareToPrevious && rangeDays(range) > 90) {
    throw new TaxonomyAwareError({
      type: 'VALIDATION',
      retryable: false,
      message: 'Comparison disabled for ranges over 90 days (doubles API calls).',
    });
  }

  const current = params.compareToPrevious
    ? await Promise.all([fetchRaw(range), fetchRaw(previousPeriod(range))])
    : [await fetchRaw(range)];

  const { upgrade, total } = current[0];
  const upRows = ga4RowsToObjects(upgrade as never);
  const totRows = ga4RowsToObjects(total as never);
  const totByDate = new Map(totRows.map((r) => [String(r.date), Number(r.sessions ?? 0)]));

  const rows: Ga4UpgradeViewsRow[] = [];
  for (const date of new Set([...upRows.map((r) => String(r.date)), ...totRows.map((r) => String(r.date))])) {
    const upRow = upRows.find((r) => r.date === date);
    rows.push({
      date,
      upgradeViews: Number(upRow?.screenPageViews ?? 0),
      totalSessions: totByDate.get(date) ?? 0,
    });
  }
  rows.sort((a, b) => a.date.localeCompare(b.date));

  const totals = rows.reduce(
    (acc, r) => ({
      upgradeViews: acc.upgradeViews + r.upgradeViews,
      totalSessions: acc.totalSessions + r.totalSessions,
    }),
    { upgradeViews: 0, totalSessions: 0 }
  );
  const conversionRate = totals.totalSessions === 0 ? 0 : totals.upgradeViews / totals.totalSessions;

  let derived: Record<string, number | string> = { conversion_rate: conversionRate };
  let previous_period: TileResponse<Ga4UpgradeViewsRow>['previous_period'];

  if (params.compareToPrevious && current[1]) {
    const prev = current[1];
    const prevUp = ga4RowsToObjects(prev.upgrade as never);
    const prevTot = ga4RowsToObjects(prev.total as never);
    const prevTotals = {
      upgradeViews: prevUp.reduce((s, r) => s + Number(r.screenPageViews ?? 0), 0),
      totalSessions: prevTot.reduce((s, r) => s + Number(r.sessions ?? 0), 0),
    };
    derived = {
      ...derived,
      upgrade_views_delta: pctDelta(totals.upgradeViews, prevTotals.upgradeViews),
      conversion_rate_delta:
        (prevTotals.totalSessions === 0 ? 0 : prevTotals.upgradeViews / prevTotals.totalSessions) - conversionRate,
    };
    previous_period = { rows: [], totals: prevTotals, derived: {} };
  }

  const fresh = detectFreshness('ga4', range, tz);

  return {
    report: 'ga4_upgrade_views',
    source: 'ga4',
    date_range: range,
    timezone: tz,
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
        estimated_units: rangeDays(range) * 2,
        range_days: rangeDays(range),
        metric_count: 2,
        dimension_count: 1,
        limit: 0,
      },
    },
  };
}

export function getGa4UpgradeViews(params: Ga4UpgradeViewsParams): Promise<TileResponse<Ga4UpgradeViewsRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `ga4_upgrade_views:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['ga4_upgrade_views', sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:ga4', 'analytics:ga4_upgrade_views'],
  })();
}
