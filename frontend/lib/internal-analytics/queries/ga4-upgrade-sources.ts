import 'server-only';
import { unstable_cache } from 'next/cache';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import { GA4_PROPERTY_ID, CACHE_TTL_SECONDS, DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT } from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, rangeDays } from '../dates';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';

export type Ga4UpgradeSourcesParams = {
  dateRange: DateRange;
  limit?: number;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4UpgradeSourcesRow = {
  source: string;
  views: number;
  subscriptions: number;
  conversion_rate: number;
};

async function fetchRaw(range: DateRange, limit: number) {
  try {
    const client = getAnalyticsDataClient();
    // One report per event type: a single globally-sorted report truncates at
    // its row limit, and view rows dwarf subscription rows, so subscription
    // counts near the cutoff silently vanish
    const reportFor = (eventName: string, rowLimit: number) =>
      client.properties.runReport({
        property: `properties/${GA4_PROPERTY_ID}`,
        requestBody: {
          dateRanges: [{ startDate: range.start, endDate: range.end }],
          dimensions: [{ name: 'customEvent:source' }, { name: 'eventName' }],
          metrics: [{ name: 'eventCount' }],
          dimensionFilter: {
            filter: {
              fieldName: 'eventName',
              stringFilter: { matchType: 'EXACT', value: eventName },
            },
          },
          orderBys: [{ metric: { metricName: 'eventCount' }, desc: true }],
          limit: String(rowLimit),
        },
      });
    // Subscriptions get a high cap: the displayed set is the top `limit`
    // sources by views, and a converting source whose subscription count
    // ranks below `limit` would otherwise show a false 0% conversion
    const [views, subscriptions] = await Promise.all([
      reportFor('upgrade_page_viewed', limit),
      reportFor('subscription_completed', 10000),
    ]);
    return { rows: [...(views.data.rows ?? []), ...(subscriptions.data.rows ?? [])] };
  } catch (e) {
    const err = e as { code?: number; status?: number };
    if (err?.code === 400 || err?.status === 400) {
      return { rows: null, __dimensionNotConfigured: true } as never;
    }
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: Ga4UpgradeSourcesParams): Promise<TileResponse<Ga4UpgradeSourcesRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const range = resolveDateRange(params.dateRange, tz);
  const limit = Math.min(params.limit ?? DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT);

  const raw = (await fetchRaw(range, limit)) as never as {
    rows?: Array<{ dimensionValues?: Array<{ value?: string }>; metricValues?: Array<{ value?: string }> }>;
    __dimensionNotConfigured?: boolean;
  };
  const fresh = detectFreshness('ga4', range, tz);

  if (raw.__dimensionNotConfigured) {
    return {
      report: 'ga4_upgrade_sources',
      source: 'ga4',
      date_range: range,
      timezone: tz,
      rows: [],
      row_count: 0,
      totals: {},
      derived: {},
      truncated: false,
      data_freshness: fresh.freshness,
      warnings: [
        ...(fresh.warnings ?? []),
        'customEvent:source dimension not configured in GA4 — register it under Admin > Custom definitions',
      ],
      generated_at: new Date().toISOString(),
      debug: { cost: { estimated_units: 0, range_days: rangeDays(range), metric_count: 1, dimension_count: 2, limit } },
    };
  }

  // Pivot: source -> { views, subscriptions }
  const pivot: Record<string, { views: number; subscriptions: number }> = {};
  for (const row of raw.rows ?? []) {
    const source = row.dimensionValues?.[0]?.value ?? '(not set)';
    const eventName = row.dimensionValues?.[1]?.value ?? '';
    const count = Number(row.metricValues?.[0]?.value ?? 0);
    if (!pivot[source]) pivot[source] = { views: 0, subscriptions: 0 };
    if (eventName === 'upgrade_page_viewed') pivot[source].views += count;
    else if (eventName === 'subscription_completed') pivot[source].subscriptions += count;
  }

  const rows: Ga4UpgradeSourcesRow[] = Object.entries(pivot)
    .map(([source, { views, subscriptions }]) => ({
      source,
      views,
      subscriptions,
      conversion_rate: views > 0 ? subscriptions / views : 0,
    }))
    .sort((a, b) => b.views - a.views)
    .slice(0, limit);

  const totalViews = rows.reduce((s, r) => s + r.views, 0);
  const totalSubs = rows.reduce((s, r) => s + r.subscriptions, 0);

  return {
    report: 'ga4_upgrade_sources',
    source: 'ga4',
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals: { views: totalViews, subscriptions: totalSubs },
    derived: {
      conversion_rate: totalViews > 0 ? totalSubs / totalViews : 0,
    },
    truncated: rows.length >= limit,
    truncation_reason: rows.length >= limit ? 'limit_reached' : undefined,
    data_freshness: fresh.freshness,
    warnings: fresh.warnings,
    generated_at: new Date().toISOString(),
    debug: {
      cost: {
        estimated_units: rangeDays(range) * 2,
        range_days: rangeDays(range),
        metric_count: 1,
        dimension_count: 2,
        limit,
      },
    },
  };
}

export function getGa4UpgradeSources(params: Ga4UpgradeSourcesParams): Promise<TileResponse<Ga4UpgradeSourcesRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `ga4_upgrade_sources:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['ga4_upgrade_sources', sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:ga4', 'analytics:ga4_upgrade_sources'],
  })();
}
