import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { filteringClientMock, type MockRow } from '@/test/supabase-mock';
import { makeCleanupCardRow, makePairCardRow } from '@/test/fixtures';
import type { AppliedRun } from '@/lib/mission-control/cleanup';

const db = filteringClientMock();
const { mockRequireAdmin } = vi.hoisted(() => ({ mockRequireAdmin: vi.fn() }));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: () => db.client }));

const { GET, POST } = await import('../route');

const OPEN = '2026-11-04-all';
const LAST = '2026-10-28-all';
const OLDER = '2026-10-21-all';
const PAGE = '20261104T180000Z-a1b2c3';

function card(runId: string, cardId: string, overrides: Record<string, unknown> = {}): MockRow {
  return { ...makeCleanupCardRow({ card_id: cardId, page_run: PAGE, ...overrides }), run_id: runId };
}

function ask(body: unknown) {
  return POST(
    new Request('http://localhost/api/mission-control/cleanup/undo-card', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }) as NextRequest
  );
}

function undos(): MockRow[] {
  return db.tableRows.team_cleanup_card_undos ?? [];
}

beforeEach(() => {
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  db.reset();
  db.tableRows.team_cleanup_runs = [
    { run_id: OPEN, status: 'reviewing', owner_done_at: null },
    { run_id: LAST, status: 'done', owner_done_at: '2026-11-01T01:00:00+00:00' },
    { run_id: OLDER, status: 'done', owner_done_at: '2026-10-25T01:00:00+00:00' },
  ];
  db.tableRows.team_cleanup_cards = [
    card(OPEN, 'auto-applied', { lane: 'auto', decision: 'apply' }),
    card(OPEN, 'auto-kept', { lane: 'auto', decision: 'apply', card: { keep_as_is: true } }),
    card(OPEN, 'owner-chosen', { lane: 'owner', decision: 'apply' }),
    {
      ...makePairCardRow({ card_id: 'merged', page_run: PAGE, lane: 'auto', decision: 'apply' }),
      run_id: LAST,
    },
    card(LAST, 'owner-applied', { lane: 'owner', decision: 'apply' }),
    card(LAST, 'owner-declined', { lane: 'owner', decision: 'dont_apply' }),
    card(OLDER, 'too-old', { lane: 'auto', decision: 'apply' }),
  ];
  db.tableRows.team_cleanup_card_undos = [
    {
      run_id: LAST,
      card_id: 'owner-applied',
      status: 'failed',
      requested_at: '2026-11-01T02:00:00+00:00',
      handled_at: '2026-11-01T03:00:00+00:00',
      result: 'old',
    },
    {
      run_id: LAST,
      card_id: 'owner-applied',
      status: 'pending',
      requested_at: '2026-11-02T02:00:00+00:00',
      handled_at: null,
      result: null,
    },
  ];
  // uq_team_cleanup_card_undos_one_pending: one pending request per card.
  db.unique.team_cleanup_card_undos = (row) => ((row.status ?? 'pending') === 'pending' ? String(row.card_id) : null);
});

describe('GET /api/mission-control/cleanup/undo-card', () => {
  it('answers with the admin check when it refuses', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    expect((await GET()).status).toBe(403);
  });

  it('lists what the open run and the last finished run applied, each with its latest undo', async () => {
    const { runs } = (await (await GET()).json()) as { runs: AppliedRun[] };

    expect(runs.map((run) => [run.runId, run.open, run.changes.map((c) => c.cardId)])).toEqual([
      [OPEN, true, ['auto-applied']],
      [LAST, false, ['owner-applied', 'merged']],
    ]);
    expect(runs[1].changes[1].text).toBe('Phoenix Rising B13 Premier merged into Phoenix Rising 2013 Boys');
    expect(runs[1].changes[0].undo?.status).toBe('pending');
  });
});

describe('POST /api/mission-control/cleanup/undo-card', () => {
  it("files a pending undo of the card in the admin's name", async () => {
    const res = await ask({ runId: LAST, cardId: 'merged', decline: true });

    expect(res.status).toBe(200);
    expect(undos().at(-1)).toEqual({
      run_id: LAST,
      card_id: 'merged',
      decline: true,
      requested_by_user_id: 'admin-1',
    });
  });

  it.each([
    ['an owner card before the review is done', OPEN, 'owner-chosen'],
    ['an automatic card that kept the stored value', OPEN, 'auto-kept'],
    ['a card the owner did not choose Apply', LAST, 'owner-declined'],
  ])('refuses %s, which changed nothing', async (_, runId, cardId) => {
    const res = await ask({ runId, cardId, decline: true });

    expect(res.status).toBe(409);
    expect(undos()).toHaveLength(2);
  });

  it('refuses a run older than the last finished one, and a card not in the run', async () => {
    expect((await ask({ runId: OLDER, cardId: 'too-old', decline: true })).status).toBe(409);
    expect((await ask({ runId: OPEN, cardId: 'merged', decline: true })).status).toBe(404);
    expect(undos()).toHaveLength(2);
  });

  it('refuses a second undo of a card while one waits', async () => {
    const res = await ask({ runId: LAST, cardId: 'owner-applied', decline: false });

    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: 'An undo of this change is already waiting' });
  });

  it.each([[{ runId: LAST, cardId: 'merged' }], [{ runId: LAST, decline: true }]])(
    'refuses a request it cannot file: %o',
    async (body) => {
      expect((await ask(body)).status).toBe(400);
    }
  );
});
