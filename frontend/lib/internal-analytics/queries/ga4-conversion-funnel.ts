// frontend/lib/internal-analytics/queries/ga4-conversion-funnel.ts
import 'server-only';
import { unstable_cache } from 'next/cache';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import { GA4_PROPERTY_ID, CACHE_TTL_SECONDS } from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, rangeDays } from '../dates';
import { ga4RowsToObjects } from '../transforms/ga4';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';

export type Ga4ConversionFunnelParams = {
  dateRange: DateRange;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4ConversionFunnelRow = {
  event: FunnelEvent;
  label: string;
  users: number;
};

const FUNNEL_STEPS = [
  { event: 'upgrade_page_viewed', label: 'Viewed /upgrade' },
  { event: 'plan_selected', label: 'Selected a plan' },
  { event: 'checkout_initiated', label: 'Started checkout' },
  { event: 'subscription_completed', label: 'Subscribed' },
] as const;

type FunnelEvent = (typeof FUNNEL_STEPS)[number]['event'];

async function fetchRaw(range: DateRange): Promise<unknown> {
  try {
    const client = getAnalyticsDataClient();
    const res = await client.properties.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      requestBody: {
        dateRanges: [{ startDate: range.start, endDate: range.end }],
        dimensions: [{ name: 'eventName' }],
        metrics: [{ name: 'activeUsers' }],
        dimensionFilter: {
          filter: {
            fieldName: 'eventName',
            inListFilter: { values: FUNNEL_STEPS.map((s) => s.event) },
          },
        },
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

function normalize(raw: unknown, range: DateRange, timezone: string): TileResponse<Ga4ConversionFunnelRow> {
  const raws = ga4RowsToObjects(raw as never);
  const usersByEvent = new Map<string, number>();
  for (const r of raws) usersByEvent.set(String(r.eventName), Number(r.activeUsers ?? 0));

  const rows: Ga4ConversionFunnelRow[] = FUNNEL_STEPS.map((s) => ({
    event: s.event,
    label: s.label,
    users: usersByEvent.get(s.event) ?? 0,
  }));

  const totals = {
    viewed: rows[0].users,
    plan_selected: rows[1].users,
    checkout_initiated: rows[2].users,
    subscribed: rows[3].users,
  };

  const derived: Record<string, number> = {
    view_to_plan: totals.viewed === 0 ? 0 : totals.plan_selected / totals.viewed,
    plan_to_checkout: totals.plan_selected === 0 ? 0 : totals.checkout_initiated / totals.plan_selected,
    checkout_to_subscribe: totals.checkout_initiated === 0 ? 0 : totals.subscribed / totals.checkout_initiated,
    overall: totals.viewed === 0 ? 0 : totals.subscribed / totals.viewed,
  };

  const fresh = detectFreshness('ga4', range, timezone);
  const warnings = [...fresh.warnings, 'Step 4 (Subscribed) is client-side; Stripe is authoritative and may differ.'];

  return {
    report: 'ga4_conversion_funnel',
    source: 'ga4',
    date_range: range,
    timezone,
    rows,
    row_count: rows.length,
    totals,
    derived,
    truncated: false,
    data_freshness: fresh.freshness,
    warnings,
    generated_at: new Date().toISOString(),
    debug: {
      cost: {
        estimated_units: 1,
        range_days: rangeDays(range),
        metric_count: 1,
        dimension_count: 1,
        limit: 0,
      },
    },
  };
}

async function runOnce(params: Ga4ConversionFunnelParams): Promise<TileResponse<Ga4ConversionFunnelRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const range = resolveDateRange(params.dateRange, tz);
  const raw = await fetchRaw(range);
  return normalize(raw, range, tz);
}

export function getGa4ConversionFunnel(
  params: Ga4ConversionFunnelParams
): Promise<TileResponse<Ga4ConversionFunnelRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `ga4_conversion_funnel:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['ga4_conversion_funnel', sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:ga4', 'analytics:ga4_conversion_funnel'],
  })();
}
