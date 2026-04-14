import 'server-only';
import { unstable_cache } from 'next/cache';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import {
  GA4_PROPERTY_ID,
  CACHE_TTL_SECONDS,
} from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, rangeDays } from '../dates';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';

export type Ga4UpgradeFunnelParams = {
  dateRange: DateRange;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4UpgradeFunnelRow = {
  step: string;
  label: string;
  count: number;
  pct_of_top: number;
};

const FUNNEL_EVENTS = [
  { step: 'upgrade_page_viewed', label: 'Viewed' },
  { step: 'plan_selected', label: 'Plan selected' },
  { step: 'checkout_initiated', label: 'Checkout started' },
  { step: 'subscription_completed', label: 'Subscribed' },
] as const;

async function fetchRaw(range: DateRange) {
  try {
    const client = getAnalyticsDataClient();
    const res = await client.properties.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      requestBody: {
        dateRanges: [{ startDate: range.start, endDate: range.end }],
        dimensions: [{ name: 'eventName' }],
        metrics: [{ name: 'eventCount' }],
        dimensionFilter: {
          filter: {
            fieldName: 'eventName',
            inListFilter: {
              values: FUNNEL_EVENTS.map((e) => e.step),
            },
          },
        },
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(
  params: Ga4UpgradeFunnelParams,
): Promise<TileResponse<Ga4UpgradeFunnelRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const range = resolveDateRange(params.dateRange, tz);

  const raw = await fetchRaw(range);
  const countMap: Record<string, number> = {};
  for (const row of raw.rows ?? []) {
    const eventName = row.dimensionValues?.[0]?.value ?? '';
    const count = Number(row.metricValues?.[0]?.value ?? 0);
    countMap[eventName] = count;
  }

  const viewed = countMap['upgrade_page_viewed'] ?? 0;
  const completed = countMap['subscription_completed'] ?? 0;
  const checkout = countMap['checkout_initiated'] ?? 0;

  const rows: Ga4UpgradeFunnelRow[] = FUNNEL_EVENTS.map(({ step, label }) => {
    const count = countMap[step] ?? 0;
    return {
      step,
      label,
      count,
      pct_of_top: viewed > 0 ? count / viewed : 0,
    };
  });

  const fresh = detectFreshness('ga4', range, tz);

  return {
    report: 'ga4_upgrade_funnel',
    source: 'ga4',
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals: {
      upgrade_page_viewed: viewed,
      subscription_completed: completed,
    },
    derived: {
      conversion_rate: viewed > 0 ? completed / viewed : 0,
      cart_abandonment: checkout > 0 ? 1 - completed / checkout : 0,
    },
    truncated: false,
    data_freshness: fresh.freshness,
    warnings: fresh.warnings,
    generated_at: new Date().toISOString(),
    debug: {
      cost: {
        estimated_units: rangeDays(range) * 1,
        range_days: rangeDays(range),
        metric_count: 1,
        dimension_count: 1,
        limit: FUNNEL_EVENTS.length,
      },
    },
  };
}

export function getGa4UpgradeFunnel(
  params: Ga4UpgradeFunnelParams,
): Promise<TileResponse<Ga4UpgradeFunnelRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `ga4_upgrade_funnel:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['ga4_upgrade_funnel', sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:ga4', 'analytics:ga4_upgrade_funnel'],
  })();
}
