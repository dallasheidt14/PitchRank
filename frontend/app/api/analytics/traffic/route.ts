import { NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import { getDateRange } from '@/lib/analytics-utils';
import type { TrafficData, ReferralSource, PageMetric } from '@/types/analytics';

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  try {
    const { searchParams } = new URL(req.url);
    const range = searchParams.get('range') || '28d';
    const { startDate, endDate } = getDateRange(range);
    const propertyId = process.env.GA4_PROPERTY_ID;

    if (!propertyId) {
      return NextResponse.json({ error: 'GA4_PROPERTY_ID not configured' }, { status: 500 });
    }

    const client = getAnalyticsDataClient();

    const [overviewRes, referralsRes, pagesRes] = await Promise.all([
      client.properties.runReport({
        property: propertyId,
        requestBody: {
          dateRanges: [{ startDate, endDate }],
          metrics: [
            { name: 'sessions' },
            { name: 'totalUsers' },
            { name: 'screenPageViews' },
            { name: 'averageSessionDuration' },
          ],
        },
      }),
      client.properties.runReport({
        property: propertyId,
        requestBody: {
          dateRanges: [{ startDate, endDate }],
          dimensions: [{ name: 'sessionSource' }],
          metrics: [{ name: 'sessions' }, { name: 'totalUsers' }],
          orderBys: [{ metric: { metricName: 'sessions' }, desc: true }],
          limit: '15',
        },
      }),
      client.properties.runReport({
        property: propertyId,
        requestBody: {
          dateRanges: [{ startDate, endDate }],
          dimensions: [{ name: 'pagePath' }],
          metrics: [{ name: 'screenPageViews' }, { name: 'totalUsers' }],
          orderBys: [{ metric: { metricName: 'screenPageViews' }, desc: true }],
          limit: '20',
        },
      }),
    ]);

    const overviewRow = overviewRes.data.rows?.[0];
    const overview = {
      sessions: parseInt(overviewRow?.metricValues?.[0]?.value || '0', 10),
      users: parseInt(overviewRow?.metricValues?.[1]?.value || '0', 10),
      pageviews: parseInt(overviewRow?.metricValues?.[2]?.value || '0', 10),
      avgSessionDuration: parseFloat(overviewRow?.metricValues?.[3]?.value || '0'),
    };

    const referrals: ReferralSource[] = (referralsRes.data.rows || []).map((row) => ({
      source: row.dimensionValues?.[0]?.value || '(unknown)',
      sessions: parseInt(row.metricValues?.[0]?.value || '0', 10),
      users: parseInt(row.metricValues?.[1]?.value || '0', 10),
    }));

    const topPages: PageMetric[] = (pagesRes.data.rows || []).map((row) => ({
      path: row.dimensionValues?.[0]?.value || '/',
      pageviews: parseInt(row.metricValues?.[0]?.value || '0', 10),
      users: parseInt(row.metricValues?.[1]?.value || '0', 10),
    }));

    const data: TrafficData = {
      overview,
      referrals,
      topPages,
      dateRange: { start: startDate, end: endDate },
    };

    return NextResponse.json(data);
  } catch (error) {
    console.error('GA4 Traffic API error:', error);
    return NextResponse.json({ error: 'Failed to fetch traffic data' }, { status: 500 });
  }
}
