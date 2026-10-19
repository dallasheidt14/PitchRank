import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { filteringClientMock, type MockRow } from '@/test/supabase-mock';

const db = filteringClientMock();
const { mockRequireAdmin } = vi.hoisted(() => ({ mockRequireAdmin: vi.fn() }));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: () => db.client }));

const { POST } = await import('../route');

const RUN = '2026-10-21-all';

function askUndo(body: unknown = { runId: RUN, stage: 'states', lane: 'auto' }) {
  return POST(
    new Request('http://localhost/api/mission-control/cleanup/undo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }) as NextRequest
  );
}

function requests(): MockRow[] {
  return db.tableRows.team_cleanup_requests ?? [];
}

beforeEach(() => {
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  db.reset();
  db.tableRows.team_cleanup_runs = [{ run_id: RUN, status: 'reviewing' }];
  // uq_team_cleanup_requests_one_pending: one pending request per run, stage, lane and action.
  db.unique.team_cleanup_requests = (row) =>
    (row.status ?? 'pending') === 'pending'
      ? `${row.run_id}|${row.stage}|${row.lane}|${String(row.action ?? 'revert')}`
      : null;
});

describe('POST /api/mission-control/cleanup/undo', () => {
  it('answers with the admin check when it refuses', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await askUndo();

    expect(res.status).toBe(403);
    expect(requests()).toEqual([]);
  });

  it("files a pending undo of the lane in the admin's name", async () => {
    const res = await askUndo();

    expect(res.status).toBe(200);
    expect(requests()).toEqual([{ run_id: RUN, stage: 'states', lane: 'auto', requested_by_user_id: 'admin-1' }]);
  });

  it.each([
    [{ runId: RUN, stage: 'merges', lane: 'auto' }],
    [{ runId: RUN, stage: 'states', lane: 'both' }],
    [{ stage: 'states', lane: 'owner' }],
  ])('refuses a request that names no stage, lane or run it can undo: %o', async (body) => {
    const res = await askUndo(body);

    expect(res.status).toBe(400);
    expect(requests()).toEqual([]);
  });

  it('refuses a run that is not in review', async () => {
    db.tableRows.team_cleanup_runs = [{ run_id: RUN, status: 'done' }];

    const res = await askUndo();

    expect(res.status).toBe(409);
    expect(requests()).toEqual([]);
  });

  it('refuses a second undo of a lane while the first still waits, and allows one after it was handled', async () => {
    expect((await askUndo()).status).toBe(200);

    const again = await askUndo();

    expect(again.status).toBe(409);
    expect(await again.json()).toEqual({ error: 'An undo of these changes is already waiting' });
    requests()[0].status = 'done';
    expect((await askUndo()).status).toBe(200);
    expect((await askUndo({ runId: RUN, stage: 'states', lane: 'owner' })).status).toBe(200);
  });
});
