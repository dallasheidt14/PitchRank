import { NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { runReport } from '@/lib/internal-analytics/report-registry';
import { TaxonomyAwareError } from '@/lib/internal-analytics/queries/_error';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  const url = new URL(req.url);
  const range = url.searchParams.get('range') ?? 'last_7_days';
  const limit = Number(url.searchParams.get('limit') ?? 10);
  try {
    const data = await runReport('ga4_traffic_sources', { date_range: range, limit });
    return NextResponse.json(data);
  } catch (e) {
    if (e instanceof TaxonomyAwareError) return NextResponse.json({ error: e.taxonomy }, { status: 500 });
    throw e;
  }
}