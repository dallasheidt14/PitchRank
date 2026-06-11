import { NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { getAnalyticsDataClient } from '@/lib/google-auth';
import { getDateRange } from '@/lib/analytics-utils';
import type { FunnelData, FunnelStep, ConversionRates } from '@/types/analytics';

const FUNNEL_EVENTS = [
  { event: 'plan_selected', label: 'Plan Selected' },
  { event: 'checkout_initiated', label: 'Checkout Started' },
  { event: 'subscription_completed', label: 'Subscribed' },
] as const;

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

    const [eventsRes, pageViewsRes] = await Promise.all([
      client.properties.runReport({
        property: `properties/${propertyId}`,
        requestBody: {
          dateRanges: [{ startDate, endDate }],
          dimensions: [{ name: 'eventName' }],
          metrics: [{ name: 'eventCount' }],
          dimensionFilter: {
            filter: {
              fieldName: 'eventName',
              inListFilter: { values: FUNNEL_EVENTS.map((e) => e.event) },
            },
          },
        },
      }),
      client.properties.runReport({
        property: `properties/${propertyId}`,
        requestBody: {
          dateRanges: [{ startDate, endDate }],
          metrics: [{ name: 'screenPageViews' }],
          dimensionFilter: {
            filter: { fieldName: 'pagePath', stringFilter: { matchType: 'EXACT', value: '/upgrade' } },
          },
        },
      }),
    ]);

    const eventCounts = new Map<string, number>();
    for (const row of eventsRes.data.rows || []) {
      const name = row.dimensionValues?.[0]?.value || '';
      const count = parseInt(row.metricValues?.[0]?.value || '0', 10);
      eventCounts.set(name, count);
    }

    const upgradeViews = parseInt(pageViewsRes.data.rows?.[0]?.metricValues?.[0]?.value || '0', 10);

    const funnel: FunnelStep[] = [
      { event: 'upgrade_page_viewed', label: 'Page Viewed', count: upgradeViews },
      ...FUNNEL_EVENTS.map((e) => ({
        event: e.event,
        label: e.label,
        count: eventCounts.get(e.event) || 0,
      })),
    ];

    const viewed = funnel[0].count;
    const planned = funnel[1].count;
    const checkout = funnel[2].count;
    const completed = funnel[3].count;

    const conversionRates: ConversionRates = {
      viewToPlanSelected: viewed > 0 ? planned / viewed : 0,
      planToCheckout: planned > 0 ? checkout / planned : 0,
      checkoutToComplete: checkout > 0 ? completed / checkout : 0,
      overallConversion: viewed > 0 ? completed / viewed : 0,
      cartAbandonmentRate: checkout > 0 ? 1 - completed / checkout : 0,
    };

    const data: FunnelData = {
      funnel,
      conversionRates,
      dateRange: { start: startDate, end: endDate },
    };

    return NextResponse.json(data);
  } catch (error) {
    console.error('GA4 Funnel API error:', error);
    return NextResponse.json({ error: 'Failed to fetch funnel data' }, { status: 500 });
  }
}
