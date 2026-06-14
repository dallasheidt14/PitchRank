import { NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { runReport, type ReportKey } from '@/lib/internal-analytics/report-registry';
import { TaxonomyAwareError } from '@/lib/internal-analytics/queries/_error';

type ExtraParam = 'limit' | 'compare' | 'none';

/**
 * Build the GET handler for an admin-only internal analytics report. Every such
 * route shares the same admin gate, `range` parsing, and error taxonomy; they
 * differ only in the report key and which optional query param they read
 * (`limit` for top-N reports, `compare` for trend reports, or neither).
 */
export function makeReportRoute(report: ReportKey, extra: ExtraParam = 'none') {
  return async function GET(req: Request) {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

    const url = new URL(req.url);
    const range = url.searchParams.get('range') ?? 'last_7_days';
    const params: Record<string, unknown> = { date_range: range };
    if (extra === 'limit') {
      params.limit = Number(url.searchParams.get('limit') ?? 10);
    } else if (extra === 'compare') {
      params.compare_to_previous = url.searchParams.get('compare') === '1';
    }

    try {
      const data = await runReport(report, params);
      return NextResponse.json(data);
    } catch (e) {
      if (e instanceof TaxonomyAwareError) return NextResponse.json({ error: e.taxonomy }, { status: 500 });
      throw e;
    }
  };
}
