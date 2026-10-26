import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { makeCleanupCardRow, makePairCardRow, type CleanupCardFixture } from '@/test/fixtures';
import { filteringClientMock } from '@/test/supabase-mock';

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
// The earlier build's page run sorts after the later one's: only created_at says which is newer.
const EARLIER = '20261021T180020Z-ffffff';
const LATER = '20261021T180010Z-000000';
// Another stage's build, saved after this one: a newest-build check that ignored the stage would refuse every save here.
const AGES = '20261021T190000Z-a1b2c3';
const MERGES = '20261021T200000Z-d4e5f6';
const id = (pageRun: string, n: number) => `${pageRun}_000000000000000${n}`;

function makeRequest(body: unknown) {
  return new Request('http://localhost/api/mission-control/cleanup/decisions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }) as NextRequest;
}

function save(body: Record<string, unknown>) {
  return POST(makeRequest({ runId: RUN, stage: 'states', pageRun: LATER, ...body }));
}

function card(cardId: string): CleanupCardFixture {
  return db.tableRows.team_cleanup_cards.find((row) => row.card_id === cardId) as CleanupCardFixture;
}

beforeEach(() => {
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  service.missing = false;
  db.reset();
  db.tableRows.team_cleanup_runs = [{ run_id: RUN, status: 'reviewing', owner_done_at: null, owner_done_by: null }];
  const later = '2026-10-21T18:02:00.5+00:00';
  db.tableRows.team_cleanup_cards = [
    makeCleanupCardRow({ page_run: EARLIER, card_id: id(EARLIER, 1), created_at: '2026-10-21T18:01:00+00:00' }),
    makeCleanupCardRow({ page_run: LATER, card_id: id(LATER, 1), position: 1, created_at: later }),
    makeCleanupCardRow({
      page_run: LATER,
      card_id: id(LATER, 2),
      position: 2,
      decision: 'dont_apply',
      decided_at: '2026-10-21T19:00:00+00:00',
      decided_by_user_id: 'admin-1',
      created_at: later,
    }),
    makeCleanupCardRow({ page_run: LATER, card_id: id(LATER, 3), position: 3, created_at: later }),
    makeCleanupCardRow({
      page_run: LATER,
      card_id: id(LATER, 4),
      lane: 'auto',
      decision: 'apply',
      decided_at: '2026-10-21T18:00:10+00:00',
      created_at: later,
    }),
    makeCleanupCardRow({
      stage: 'ages',
      page_run: AGES,
      card_id: id(AGES, 1),
      created_at: '2026-10-21T19:01:00+00:00',
    }),
    makePairCardRow({ page_run: MERGES, card_id: id(MERGES, 1), created_at: '2026-10-21T20:01:00+00:00' }),
  ];
});

describe('POST /api/mission-control/cleanup/decisions', () => {
  it('answers with the admin check when it refuses', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await save({ cardIds: [id(LATER, 1)], decision: 'apply' });

    expect(res.status).toBe(403);
    expect(card(id(LATER, 1)).decision).toBeNull();
  });

  it("saves a decision with the server's time and the admin who made it", async () => {
    const before = Date.now();

    const res = await save({ cardIds: [id(LATER, 1)], decision: 'apply' });

    const saved = card(id(LATER, 1));
    expect(res.status).toBe(200);
    expect(saved.decision).toBe('apply');
    expect(saved.decided_by_user_id).toBe('admin-1');
    expect(Date.parse(saved.decided_at!)).toBeGreaterThanOrEqual(before);
    expect((await res.json()).updated).toMatchObject([
      { card_id: id(LATER, 1), decision: 'apply', decided_at: saved.decided_at },
    ]);
  });

  it('clears a decision together with its time and who made it', async () => {
    await save({ cardIds: [id(LATER, 2)], decision: null });

    const cleared = card(id(LATER, 2));
    expect([cleared.decision, cleared.decided_at, cleared.decided_by_user_id]).toEqual([null, null, null]);
  });

  it('saves a note alone, trimmed, leaving the decision as it was', async () => {
    await save({ cardIds: [id(LATER, 2)], note: '  played in UT all fall  ' });
    expect([card(id(LATER, 2)).note, card(id(LATER, 2)).decision]).toEqual(['played in UT all fall', 'dont_apply']);

    await save({ cardIds: [id(LATER, 2)], note: '   ' });
    expect(card(id(LATER, 2)).note).toBeNull();
  });

  it("never writes the automatic lane's cards, another stage's or an earlier build's", async () => {
    await save({ cardIds: [id(LATER, 1), id(LATER, 4), id(AGES, 1), id(EARLIER, 1)], decision: 'dont_apply' });

    expect(card(id(LATER, 1)).decision).toBe('dont_apply');
    expect(card(id(LATER, 4)).decision).toBe('apply');
    expect(card(id(AGES, 1)).decision).toBeNull();
    expect(card(id(EARLIER, 1)).decision).toBeNull();
  });

  it('leaves a decided card as it is when asked for the undecided ones only', async () => {
    const res = await save({
      cardIds: [id(LATER, 1), id(LATER, 2), id(LATER, 3)],
      decision: 'apply',
      onlyUndecided: true,
    });

    expect([1, 2, 3].map((n) => card(id(LATER, n)).decision)).toEqual(['apply', 'dont_apply', 'apply']);
    expect((await res.json()).updated.map((row: { card_id: string }) => row.card_id)).toEqual([
      id(LATER, 1),
      id(LATER, 3),
    ]);
  });

  it('saves a swap alone on a duplicate-team card, and answers with it', async () => {
    const res = await POST(
      makeRequest({ runId: RUN, stage: 'merges', pageRun: MERGES, cardIds: [id(MERGES, 1)], swap: true })
    );

    expect(res.status).toBe(200);
    expect([card(id(MERGES, 1)).swap, card(id(MERGES, 1)).decision]).toEqual([true, null]);
    expect((await res.json()).updated).toMatchObject([{ card_id: id(MERGES, 1), swap: true }]);
  });

  it('refuses a page build the table saved before the newest one', async () => {
    const res = await POST(
      makeRequest({ runId: RUN, stage: 'states', pageRun: EARLIER, cardIds: [id(EARLIER, 1)], decision: 'apply' })
    );

    expect(res.status).toBe(409);
    expect(card(id(EARLIER, 1)).decision).toBeNull();
  });

  it('refuses once the review is marked done', async () => {
    db.tableRows.team_cleanup_runs[0].owner_done_at = '2026-10-25T01:00:00+00:00';
    db.tableRows.team_cleanup_runs[0].owner_done_by = 'deadline';

    const res = await save({ cardIds: [id(LATER, 1)], decision: 'apply' });

    expect(res.status).toBe(409);
    expect((await res.json()).error).toBe('The review is marked done, so its choices are locked');
    expect(card(id(LATER, 1)).decision).toBeNull();
  });

  it('refuses a run that is not in review', async () => {
    db.tableRows.team_cleanup_runs[0].status = 'applying';

    const res = await save({ cardIds: [id(LATER, 1)], decision: 'apply' });

    expect(res.status).toBe(409);
    expect(card(id(LATER, 1)).decision).toBeNull();
  });

  it.each([
    ['an unknown decision', { cardIds: [id(LATER, 1)], decision: 'maybe' }],
    ['no decision and no note', { cardIds: [id(LATER, 1)] }],
    ['no card', { cardIds: [], decision: 'apply' }],
    ['more cards than one write takes', { cardIds: Array.from({ length: 101 }, (_, n) => `c${n}`), decision: 'apply' }],
    ['a note longer than the table keeps', { cardIds: [id(LATER, 1)], note: 'x'.repeat(2001) }],
    ['an unknown stage', { stage: 'reconcile', cardIds: [id(LATER, 1)], decision: 'apply' }],
    ['onlyUndecided that is not true or false', { cardIds: [id(LATER, 1)], decision: 'apply', onlyUndecided: 'yes' }],
    ['a swap on a card that is not a pair', { cardIds: [id(LATER, 1)], decision: 'apply', swap: true }],
    ['a swap that is not true or false', { stage: 'merges', pageRun: MERGES, cardIds: [id(MERGES, 1)], swap: 'yes' }],
  ])('refuses %s', async (_, body) => {
    const res = await save(body);

    expect(res.status).toBe(400);
    expect(card(id(LATER, 1)).decision).toBeNull();
    expect(card(id(MERGES, 1)).swap).toBe(false);
    expect(db.queriesFor('team_cleanup_cards')).toEqual([]);
  });

  it('answers in JSON when the service client cannot be built', async () => {
    service.missing = true;

    const res = await save({ cardIds: [id(LATER, 1)], decision: 'apply' });

    expect([res.status, await res.json()]).toEqual([500, { error: 'Could not save the choice' }]);
  });

  it('refuses a body that is not an object', async () => {
    const res = await POST(makeRequest(['apply']));

    expect(res.status).toBe(400);
  });
});
