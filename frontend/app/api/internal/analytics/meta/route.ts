import { NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { GA4_PROPERTY_ID, GSC_SITE_URL, DATE_RANGE_PRESETS, DEFAULT_PRESET } from '@/lib/internal-analytics/constants';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  return NextResponse.json({
    presets: DATE_RANGE_PRESETS,
    default_preset: DEFAULT_PRESET,
    ga4_property_id: GA4_PROPERTY_ID,
    gsc_site_url: GSC_SITE_URL,
    admin_email: auth.user.email ?? null,
    timezone: 'America/Phoenix',
  });
}
