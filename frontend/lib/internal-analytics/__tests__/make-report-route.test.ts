import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse } from 'next/server';
import { TaxonomyAwareError } from '@/lib/internal-analytics/queries/_error';

const { mockRequireAdmin, mockRunReport } = vi.hoisted(() => ({
  mockRequireAdmin: vi.fn(),
  mockRunReport: vi.fn(),
}));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/internal-analytics/report-registry', () => ({ runReport: mockRunReport }));

import { makeReportRoute } from '../make-report-route';

// The factory is typed against ReportKey; tests use real keys so the param
// assertions read naturally. Casting keeps the test independent of the registry.
const OVERVIEW = 'ga4_traffic_overview' as Parameters<typeof makeReportRoute>[0];
const TOP_PAGES = 'ga4_top_pages' as Parameters<typeof makeReportRoute>[0];

function makeRequest(query = ''): Request {
  return new Request(`http://localhost/api/internal/analytics/ga4/overview${query}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1', email: 'a@pitchrank.io' }, supabase: {}, error: null });
  mockRunReport.mockResolvedValue({ rows: [] });
});

describe('makeReportRoute', () => {
  it('returns the requireAdmin error and never runs the report for a non-admin', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await makeReportRoute(OVERVIEW)(makeRequest());

    expect(res.status).toBe(403);
    expect(mockRunReport).not.toHaveBeenCalled();
  });

  it('runs the report with the default range and returns its JSON', async () => {
    mockRunReport.mockResolvedValue({ rows: [{ users: 5 }] });

    const res = await makeReportRoute(OVERVIEW)(makeRequest());

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ rows: [{ users: 5 }] });
    expect(mockRunReport).toHaveBeenCalledWith(OVERVIEW, { date_range: 'last_7_days' });
  });

  it('passes the requested range through to the report', async () => {
    await makeReportRoute(OVERVIEW)(makeRequest('?range=last_30_days'));

    expect(mockRunReport).toHaveBeenCalledWith(OVERVIEW, { date_range: 'last_30_days' });
  });

  it('parses limit for top-N reports, defaulting to 10', async () => {
    await makeReportRoute(TOP_PAGES, 'limit')(makeRequest('?limit=25'));
    expect(mockRunReport).toHaveBeenCalledWith(TOP_PAGES, { date_range: 'last_7_days', limit: 25 });

    mockRunReport.mockClear();
    await makeReportRoute(TOP_PAGES, 'limit')(makeRequest());
    expect(mockRunReport).toHaveBeenCalledWith(TOP_PAGES, { date_range: 'last_7_days', limit: 10 });
  });

  it('parses compare=1 into compare_to_previous for trend reports', async () => {
    await makeReportRoute(OVERVIEW, 'compare')(makeRequest('?compare=1'));
    expect(mockRunReport).toHaveBeenCalledWith(OVERVIEW, { date_range: 'last_7_days', compare_to_previous: true });

    mockRunReport.mockClear();
    await makeReportRoute(OVERVIEW, 'compare')(makeRequest('?compare=0'));
    expect(mockRunReport).toHaveBeenCalledWith(OVERVIEW, { date_range: 'last_7_days', compare_to_previous: false });
  });

  it('maps a TaxonomyAwareError to a 500 carrying the taxonomy label', async () => {
    mockRunReport.mockRejectedValue(
      new TaxonomyAwareError({ type: 'AUTH', message: 'Google API authorization failed', retryable: false })
    );

    const res = await makeReportRoute(OVERVIEW)(makeRequest());

    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({
      error: { type: 'AUTH', message: 'Google API authorization failed', retryable: false },
    });
  });

  it('rethrows non-taxonomy errors so they surface as a framework 500', async () => {
    mockRunReport.mockRejectedValue(new Error('unexpected boom'));

    await expect(makeReportRoute(OVERVIEW)(makeRequest())).rejects.toThrow('unexpected boom');
  });
});
