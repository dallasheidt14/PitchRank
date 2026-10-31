import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { filteringClientMock, type MockRow } from '@/test/supabase-mock';
import { makePairCard } from '@/test/fixtures';
import type { SpotCheckReview } from '@/lib/mission-control/cleanup';

const db = filteringClientMock();
const { mockRequireAdmin } = vi.hoisted(() => ({ mockRequireAdmin: vi.fn() }));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: () => db.client }));

const { GET, POST } = await import('../route');

const OLDER = '2026-10-28-all';
const NEWER = '2026-11-04-all';

function sampled(runId: string, position: number, cardId: string, verdict: string | null = null): MockRow {
  return {
    id: `${runId}-${position}`,
    run_id: runId,
    position,
    card_id: cardId,
    verdict,
    note: null,
    judged_at: null,
    judged_by_user_id: null,
  };
}

function cardRow(id: string, swap = false): MockRow {
  return { card_id: id, card: makePairCard({ id, why: `Reviewers cleared it: ${id}` }), swap };
}

function judge(body: unknown) {
  return POST(
    new Request('http://localhost/api/mission-control/cleanup/spot-check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }) as NextRequest
  );
}

function checks(): MockRow[] {
  return db.tableRows.team_cleanup_spot_checks ?? [];
}

beforeEach(() => {
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  db.reset();
  db.tableRows.team_cleanup_spot_checks = [
    sampled(OLDER, 1, 'o1', 'right'),
    sampled(NEWER, 2, 'n2'),
    sampled(NEWER, 1, 'n1', 'wrong'),
  ];
  db.tableRows.team_cleanup_cards = ['o1', 'n1', 'n2'].map((id) => cardRow(id, id === 'n1'));
});

describe('GET /api/mission-control/cleanup/spot-check', () => {
  it('answers with the admin check when it refuses', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    expect((await GET()).status).toBe(403);
  });

  it('lists each run newest first, its merges in order with their cards, and the clean weeks', async () => {
    const body = (await (await GET()).json()) as SpotCheckReview;

    expect(body.runs.map((run) => [run.runId, run.checks.map((c) => [c.cardId, c.verdict, c.swap])])).toEqual([
      [
        NEWER,
        [
          ['n1', 'wrong', true],
          ['n2', null, false],
        ],
      ],
      [OLDER, [['o1', 'right', false]]],
    ]);
    expect(body.runs[0].checks[0].card.why).toBe('Reviewers cleared it: n1');
    expect(body.cleanWeeks).toBe(0);
  });

  it("shows the newest eight weeks' samples whole, and counts the clean weeks across all of them", async () => {
    // Ten weekly runs, the newest sampling three merges and the rest ten each, every one judged right.
    const weeks = Array.from({ length: 10 }, (_, i) => {
      const day = new Date(Date.UTC(2026, 10, 11 - 7 * i));
      return `${day.toISOString().slice(0, 10)}-all`;
    });
    const size = (runId: string) => (runId === weeks[0] ? 3 : 10);
    db.tableRows.team_cleanup_spot_checks = weeks.flatMap((runId) =>
      Array.from({ length: size(runId) }, (_, n) => sampled(runId, n + 1, `${runId}-c${n}`, 'right'))
    );
    db.tableRows.team_cleanup_cards = weeks.flatMap((runId) =>
      Array.from({ length: size(runId) }, (_, n) => cardRow(`${runId}-c${n}`))
    );

    const body = (await (await GET()).json()) as SpotCheckReview;

    expect(body.runs.map((run) => [run.runId, run.checks.length])).toEqual(
      weeks.slice(0, 8).map((runId) => [runId, size(runId)])
    );
    expect(body.cleanWeeks).toBe(10);
  });

  it('shows no sample, rather than an error, before the table exists', async () => {
    db.failing.team_cleanup_spot_checks = { code: 'PGRST205', message: 'no table' };

    const res = await GET();

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ runs: [], cleanWeeks: 0 });
  });
});

describe('POST /api/mission-control/cleanup/spot-check', () => {
  it("records a verdict and its note in the admin's name, and a null verdict takes it back", async () => {
    const res = await judge({ runId: NEWER, cardId: 'n2', verdict: 'wrong', note: '  two squads  ' });

    expect(res.status).toBe(200);
    const row = checks().find((r) => r.card_id === 'n2')!;
    expect([row.verdict, row.note, row.judged_by_user_id]).toEqual(['wrong', 'two squads', 'admin-1']);
    expect(typeof row.judged_at).toBe('string');

    await judge({ runId: NEWER, cardId: 'n2', verdict: null, note: 'two squads' });

    expect([row.verdict, row.judged_at, row.judged_by_user_id, row.note]).toEqual([null, null, null, 'two squads']);
  });

  it("refuses a merge outside the run's sample", async () => {
    const res = await judge({ runId: OLDER, cardId: 'n2', verdict: 'right' });

    expect(res.status).toBe(404);
    expect(checks().find((r) => r.card_id === 'n2')!.verdict).toBeNull();
  });

  it.each([
    [{ runId: NEWER, cardId: 'n2', verdict: 'maybe' }],
    [{ runId: NEWER, verdict: 'right' }],
    [{ runId: NEWER, cardId: 'n2', verdict: 'right', note: 'x'.repeat(2001) }],
  ])('refuses a request it cannot record: %o', async (body) => {
    const res = await judge(body);

    expect(res.status).toBe(400);
    expect(checks().find((r) => r.card_id === 'n2')!.verdict).toBeNull();
  });
});
