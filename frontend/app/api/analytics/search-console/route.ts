import { NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { getSearchConsoleClient } from '@/lib/google-auth';
import { getDateRange } from '@/lib/analytics-utils';
import type { SearchConsoleData, SearchConsoleRow, SearchConsolePageRow, SearchConsoleTotals } from '@/types/analytics';

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  try {
    const { searchParams } = new URL(req.url);
    const range = searchParams.get('range') || '28d';
    const { startDate, endDate } = getDateRange(range);
    const siteUrl = process.env.GSC_SITE_URL;

    if (!siteUrl) {
      return NextResponse.json({ error: 'GSC_SITE_URL not configured' }, { status: 500 });
    }

    const client = getSearchConsoleClient();

    const [queriesRes, pagesRes, totalsRes] = await Promise.all([
      client.searchanalytics.query({
        siteUrl,
        requestBody: {
          startDate,
          endDate,
          dimensions: ['query'],
          rowLimit: 25,
        },
      }),
      client.searchanalytics.query({
        siteUrl,
        requestBody: {
          startDate,
          endDate,
          dimensions: ['page'],
          rowLimit: 25,
        },
      }),
      // Totals need their own date-dimension query: query/page rows are
      // privacy-thresholded (and capped at 25 here), so summing them
      // materially understates clicks and impressions
      client.searchanalytics.query({
        siteUrl,
        requestBody: {
          startDate,
          endDate,
          dimensions: ['date'],
          rowLimit: 1000,
        },
      }),
    ]);

    const topQueries: SearchConsoleRow[] = (queriesRes.data.rows || []).map((row) => ({
      query: row.keys?.[0] || '',
      clicks: row.clicks || 0,
      impressions: row.impressions || 0,
      ctr: row.ctr || 0,
      position: row.position || 0,
    }));

    const topPages: SearchConsolePageRow[] = (pagesRes.data.rows || []).map((row) => ({
      page: row.keys?.[0] || '',
      clicks: row.clicks || 0,
      impressions: row.impressions || 0,
      ctr: row.ctr || 0,
      position: row.position || 0,
    }));

    const totalRows = totalsRes.data.rows || [];
    const totals = totalRows.reduce<SearchConsoleTotals>(
      (acc, row) => ({
        clicks: acc.clicks + (row.clicks || 0),
        impressions: acc.impressions + (row.impressions || 0),
        ctr: 0,
        position: 0,
      }),
      { clicks: 0, impressions: 0, ctr: 0, position: 0 }
    );

    // Compute weighted averages for CTR and position
    if (totals.impressions > 0) {
      totals.ctr = totals.clicks / totals.impressions;
      totals.position =
        totalRows.reduce((sum, row) => sum + (row.position || 0) * (row.impressions || 0), 0) / totals.impressions;
    }

    const data: SearchConsoleData = {
      topQueries,
      topPages,
      totals,
      dateRange: { start: startDate, end: endDate },
    };

    return NextResponse.json(data);
  } catch (error) {
    console.error('Search Console API error:', error);
    return NextResponse.json({ error: 'Failed to fetch Search Console data' }, { status: 500 });
  }
}
