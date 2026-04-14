import 'server-only';
import { unstable_cache } from 'next/cache';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import {
  GA4_PROPERTY_ID,
  CACHE_TTL_SECONDS,
  DEFAULT_ROW_LIMIT,
  MAX_ROW_LIMIT,
} from '../constants';
import type { DateRange, TileResponse } from '../types';
import { resolveDateRange, detectFreshness, rangeDays } from '../dates';
import { coalesce, sortedKeys } from './_coalesce';
import { toTaxonomyError, TaxonomyAwareError } from './_error';
import { createServerSupabase } from '@/lib/supabase/server';

export type Ga4MostWantedTeamsParams = {
  dateRange: DateRange;
  limit?: number;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4MostWantedTeamsRow = {
  team_id: string;
  team_name?: string;
  paywall_impressions: number;
};

async function fetchRaw(range: DateRange, limit: number) {
  try {
    const client = getAnalyticsDataClient();
    const res = await client.properties.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      requestBody: {
        dateRanges: [{ startDate: range.start, endDate: range.end }],
        dimensions: [{ name: 'customEvent:team_id' }],
        metrics: [{ name: 'eventCount' }],
        dimensionFilter: {
          filter: {
            fieldName: 'eventName',
            stringFilter: { matchType: 'EXACT', value: 'paywall_impression' },
          },
        },
        orderBys: [{ metric: { metricName: 'eventCount' }, desc: true }],
        limit: String(limit),
      },
    });
    return res.data;
  } catch (e) {
    // 400 typically means customEvent:team_id dimension not configured
    const err = e as { code?: number; status?: number };
    if (err?.code === 400 || err?.status === 400) {
      return { rows: null, __dimensionNotConfigured: true } as never;
    }
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(
  params: Ga4MostWantedTeamsParams,
): Promise<TileResponse<Ga4MostWantedTeamsRow>> {
  const tz = params.timezone ?? 'America/Phoenix';
  const range = resolveDateRange(params.dateRange, tz);
  const limit = Math.min(params.limit ?? DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT);

  const raw = await fetchRaw(range, limit) as never as {
    rows?: Array<{ dimensionValues?: Array<{ value?: string }>; metricValues?: Array<{ value?: string }> }>;
    __dimensionNotConfigured?: boolean;
  };
  const fresh = detectFreshness('ga4', range, tz);

  if (raw.__dimensionNotConfigured) {
    return {
      report: 'ga4_most_wanted_teams',
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
        'customEvent:team_id dimension not configured in GA4 — register it under Admin > Custom definitions',
      ],
      generated_at: new Date().toISOString(),
      debug: { cost: { estimated_units: 0, range_days: rangeDays(range), metric_count: 1, dimension_count: 1, limit } },
    };
  }

  const rawRows = raw.rows ?? [];
  const teamIds = rawRows
    .map((r) => r.dimensionValues?.[0]?.value)
    .filter((id): id is string => Boolean(id) && id !== '(not set)');

  // Resolve team names from Supabase
  const nameMap: Record<string, string> = {};
  if (teamIds.length > 0) {
    try {
      const supabase = await createServerSupabase();
      const { data } = await supabase
        .from('teams')
        .select('id, name')
        .in('id', teamIds);
      for (const t of data ?? []) {
        nameMap[String(t.id)] = t.name as string;
      }
    } catch {
      // name resolution is best-effort; continue without names
    }
  }

  const rows: Ga4MostWantedTeamsRow[] = rawRows.map((r) => {
    const team_id = r.dimensionValues?.[0]?.value ?? '(not set)';
    return {
      team_id,
      team_name: nameMap[team_id],
      paywall_impressions: Number(r.metricValues?.[0]?.value ?? 0),
    };
  });

  const totalImpressions = rows.reduce((s, r) => s + r.paywall_impressions, 0);

  return {
    report: 'ga4_most_wanted_teams',
    source: 'ga4',
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals: { paywall_impressions: totalImpressions },
    derived: {},
    truncated: rows.length >= limit,
    truncation_reason: rows.length >= limit ? 'limit_reached' : undefined,
    data_freshness: fresh.freshness,
    warnings: fresh.warnings,
    generated_at: new Date().toISOString(),
    debug: {
      cost: {
        estimated_units: rangeDays(range) * 1,
        range_days: rangeDays(range),
        metric_count: 1,
        dimension_count: 1,
        limit,
      },
    },
  };
}

export function getGa4MostWantedTeams(
  params: Ga4MostWantedTeamsParams,
): Promise<TileResponse<Ga4MostWantedTeamsRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `ga4_most_wanted_teams:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ['ga4_most_wanted_teams', sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ['analytics:ga4', 'analytics:ga4_most_wanted_teams'],
  })();
}
