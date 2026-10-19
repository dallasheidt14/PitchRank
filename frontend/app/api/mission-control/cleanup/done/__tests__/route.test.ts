import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { filteringClientMock, type MockRow } from '@/test/supabase-mock';

const db = filteringClientMock();
const { mockRequireAdmin, service } = vi.hoisted(() => ({ mockRequireAdmin: vi.fn(), service: { missing: false } }));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({
  createServiceSupabase: () => {
    if (service.missing) throw new Error('Missing Supabase service configuration');
    return db.client;
  },
}));

const { POST } = await import('../route');

const RUN = '2026-10-21-all';

function markDone(body: unknown = { runId: RUN }) {
  return POST(
    new Request('http://localhost/api/mission-control/cleanup/done', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }) as NextRequest
  );
}

function run(): MockRow {
  return db.tableRows.team_cleanup_runs[0];
}

beforeEach(() => {
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  service.missing = false;
  db.reset();
  db.tableRows.team_cleanup_runs = [{ run_id: RUN, status: 'reviewing', owner_done_at: null, owner_done_by: null }];
});

describe('POST /api/mission-control/cleanup/done', () => {
  it('answers with the admin check when it refuses', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await markDone();

    expect(res.status).toBe(403);
    expect(run().owner_done_at).toBeNull();
  });

  it('marks the review done by the owner, now', async () => {
    const before = Date.now();

    const res = await markDone();

    expect(res.status).toBe(200);
    expect(run().owner_done_by).toBe('owner');
    expect(Date.parse(run().owner_done_at as string)).toBeGreaterThanOrEqual(before);
    expect(await res.json()).toEqual({ ownerDoneAt: run().owner_done_at, ownerDoneBy: 'owner' });
  });

  it('leaves a review already marked done as it was', async () => {
    run().owner_done_at = '2026-10-25T01:00:00+00:00';
    run().owner_done_by = 'deadline';

    const res = await markDone();

    expect(res.status).toBe(409);
    expect([run().owner_done_at, run().owner_done_by]).toEqual(['2026-10-25T01:00:00+00:00', 'deadline']);
  });

  it('refuses a run that is not in review', async () => {
    run().status = 'applying';

    const res = await markDone();

    expect(res.status).toBe(409);
    expect(run().owner_done_at).toBeNull();
  });

  it("refuses an older run's Done without touching the run in review", async () => {
    db.tableRows.team_cleanup_runs.push({
      run_id: '2026-10-14-all',
      status: 'done',
      owner_done_at: null,
      owner_done_by: null,
    });

    const res = await markDone({ runId: '2026-10-14-all' });

    expect(res.status).toBe(409);
    expect(run().owner_done_at).toBeNull();
  });

  it.each([
    ['no run', {}],
    ['a run id longer than any run has', { runId: 'x'.repeat(201) }],
  ])('refuses a body with %s', async (_, body) => {
    const res = await markDone(body);

    expect(res.status).toBe(400);
    expect(run().owner_done_at).toBeNull();
  });

  it('answers in JSON when the service client cannot be built', async () => {
    service.missing = true;

    const res = await markDone();

    expect([res.status, await res.json()]).toEqual([500, { error: 'Could not mark the review done' }]);
  });
});
