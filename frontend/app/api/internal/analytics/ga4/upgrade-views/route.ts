import { makeReportRoute } from '@/lib/internal-analytics/make-report-route';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export const GET = makeReportRoute('ga4_upgrade_views', 'compare');
