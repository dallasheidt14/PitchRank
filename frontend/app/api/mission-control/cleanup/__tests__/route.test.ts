import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextResponse } from 'next/server';
import { makeCleanupCardRow, makePairCardRow } from '@/test/fixtures';
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

const { GET } = await import('../route');

const RUN = '2026-10-21-all';
// The earlier build's page run sorts after the later one's: only created_at says which is newer.
const EARLIER = '20261021T180020Z-ffffff';
const LATER = '20261021T180010Z-000000';

beforeEach(() => {
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin' }, supabase: {}, error: null });
  service.missing = false;
  db.reset();
  db.tableRows.team_cleanup_runs = [
    { run_id: '2026-10-14-all', scope: { states: ['ALL'] }, status: 'done', owner_done_at: null, owner_done_by: null },
    { run_id: RUN, scope: { states: ['ALL'] }, status: 'reviewing', owner_done_at: null, owner_done_by: null },
  ];
  db.tableRows.team_cleanup_cards = [
    makeCleanupCardRow({ page_run: EARLIER, created_at: '2026-10-21T18:01:00+00:00' }),
    makeCleanupCardRow({ page_run: LATER, position: 2, created_at: '2026-10-21T18:02:00.5+00:00' }),
    makeCleanupCardRow({
      page_run: LATER,
      card_id: `${LATER}_0000000000000002`,
      position: 1,
      created_at: '2026-10-21T18:02:00.5+00:00',
    }),
    makeCleanupCardRow({
      page_run: LATER,
      card_id: `${LATER}_0000000000000003`,
      lane: 'auto',
      decision: 'apply',
      decided_at: '2026-10-21T18:00:10+00:00',
      created_at: '2026-10-21T18:02:00.5+00:00',
    }),
    makeCleanupCardRow({ run_id: '2026-10-14-all', page_run: '20261014T180000Z-a1b2c3', stage: 'ages' }),
  ];
});

describe('GET /api/mission-control/cleanup', () => {
  it('answers with the admin check when it refuses', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await GET();

    expect(res.status).toBe(403);
    expect(db.queries).toEqual([]);
  });

  it('shows each stage page as the build saved last, its own cards apart from the automatic ones', async () => {
    const body = await (await GET()).json();

    expect(body.run).toEqual({
      runId: RUN,
      states: ['ALL'],
      status: 'reviewing',
      ownerDoneAt: null,
      ownerDoneBy: null,
      ownerDoneLabel: null,
    });
    expect(body.stages.map((s: { stage: string; pageRun: string }) => [s.stage, s.pageRun])).toEqual([
      ['states', LATER],
    ]);
    expect(body.stages[0].cards.map((r: { card_id: string }) => r.card_id)).toEqual([
      `${LATER}_0000000000000002`,
      `${LATER}_0000000000000001`,
    ]);
    expect(body.stages[0].auto.map((r: { card_id: string }) => r.card_id)).toEqual([`${LATER}_0000000000000003`]);
  });

  it('names when the review was marked done in Arizona time', async () => {
    Object.assign(db.tableRows.team_cleanup_runs[1], {
      owner_done_at: '2026-10-26T01:00:00+00:00',
      owner_done_by: 'deadline',
    });

    const body = await (await GET()).json();

    expect(body.run.ownerDoneLabel).toBe('Sun, Oct 25, 6:00 PM');
  });

  it('answers in JSON when the service client cannot be built', async () => {
    service.missing = true;

    const res = await GET();

    expect([res.status, await res.json()]).toEqual([500, { error: 'Could not read the cleanup review' }]);
  });

  it('says so when no run is open', async () => {
    db.tableRows.team_cleanup_runs = [db.tableRows.team_cleanup_runs[0]];

    const body = await (await GET()).json();

    expect(body).toEqual({
      run: null,
      stages: [],
      undo: [],
      previous: { runId: '2026-10-14-all', stages: ['ages'], undo: [] },
    });
  });

  it('names only the stages the last finished run published cards for, in run order', async () => {
    db.tableRows.team_cleanup_cards.push(
      makePairCardRow({ run_id: '2026-10-14-all', page_run: '20261014T190000Z-a1b2c3' }),
      makeCleanupCardRow({ run_id: '2026-10-14-all', page_run: '20261014T170000Z-a1b2c3', stage: 'clubs' })
    );

    const body = await (await GET()).json();

    expect(body.previous.stages).toEqual(['clubs', 'ages', 'merges']);
  });

  it("returns a pair card's swap with the card", async () => {
    db.tableRows.team_cleanup_cards.push(
      makePairCardRow({ page_run: '20261021T200000Z-d4e5f6', created_at: '2026-10-21T20:00:00+00:00', swap: true })
    );

    const body = await (await GET()).json();

    const merges = body.stages.find((s: { stage: string }) => s.stage === 'merges');
    expect(merges.cards.map((r: { swap: boolean }) => r.swap)).toEqual([true]);
  });

  it("shows each lane's latest undo request in Arizona time", async () => {
    db.tableRows.team_cleanup_requests = [
      {
        run_id: RUN,
        stage: 'states',
        lane: 'auto',
        status: 'failed',
        requested_at: '2026-10-22T18:00:00+00:00',
        handled_at: '2026-10-22T18:17:00+00:00',
        result: 'Not reverting: other writes',
      },
      {
        run_id: RUN,
        stage: 'states',
        lane: 'auto',
        status: 'pending',
        requested_at: '2026-10-22T19:00:00+00:00',
        handled_at: null,
        result: null,
      },
      {
        run_id: RUN,
        stage: 'clubs',
        lane: 'owner',
        status: 'done',
        requested_at: '2026-10-22T17:00:00+00:00',
        handled_at: '2026-10-22T17:17:00+00:00',
        result: 'reverted',
      },
      {
        run_id: '2026-10-14-all',
        stage: 'ages',
        lane: 'auto',
        status: 'done',
        requested_at: '2026-10-15T17:00:00+00:00',
        handled_at: '2026-10-15T17:17:00+00:00',
        result: null,
      },
    ];

    const body = await (await GET()).json();

    expect(body.undo).toEqual([
      {
        stage: 'states',
        lane: 'auto',
        status: 'pending',
        requestedLabel: 'Thu, Oct 22, 12:00 PM',
        handledLabel: null,
        result: null,
      },
      {
        stage: 'clubs',
        lane: 'owner',
        status: 'done',
        requestedLabel: 'Thu, Oct 22, 10:00 AM',
        handledLabel: 'Thu, Oct 22, 10:17 AM',
        result: 'reverted',
      },
    ]);
  });

  it('offers the latest finished run with its own undo statuses, and none when no run has finished', async () => {
    db.tableRows.team_cleanup_runs.push({
      run_id: '2026-10-07-ca',
      scope: { states: ['CA'] },
      status: 'done',
      owner_done_at: null,
      owner_done_by: null,
    });
    db.tableRows.team_cleanup_requests = [
      {
        run_id: '2026-10-14-all',
        stage: 'ages',
        lane: 'owner',
        status: 'done',
        requested_at: '2026-10-22T17:00:00+00:00',
        handled_at: '2026-10-22T17:17:00+00:00',
        result: 'reverted',
      },
    ];

    const body = await (await GET()).json();

    expect(body.previous).toEqual({
      runId: '2026-10-14-all',
      stages: ['ages'],
      undo: [
        {
          stage: 'ages',
          lane: 'owner',
          status: 'done',
          requestedLabel: 'Thu, Oct 22, 10:00 AM',
          handledLabel: 'Thu, Oct 22, 10:17 AM',
          result: 'reverted',
        },
      ],
    });
    expect(body.undo).toEqual([]);

    db.tableRows.team_cleanup_runs = [db.tableRows.team_cleanup_runs[1]];
    expect((await (await GET()).json()).previous).toBeNull();
  });

  it('still shows the cards when the undo requests cannot be read', async () => {
    db.failing.team_cleanup_requests = {
      code: 'PGRST205',
      message: "Could not find the table 'public.team_cleanup_requests'",
    };

    const res = await GET();
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body.undo).toEqual([]);
    expect(body.stages[0].cards).toHaveLength(2);
  });

  it('still shows a run past review, so its page reads as locked rather than missing', async () => {
    db.tableRows.team_cleanup_runs[1].status = 'applying';

    const body = await (await GET()).json();

    expect([body.run.runId, body.run.status]).toEqual([RUN, 'applying']);
  });

  it('reads past the first thousand card rows, where the newest build sorts', async () => {
    const old = '20261021T170000Z-a1b2c3';
    const newest = '20261021T190000Z-a1b2c3';
    db.tableRows.team_cleanup_cards = [
      ...Array.from({ length: 1000 }, (_, n) =>
        makeCleanupCardRow({
          page_run: old,
          card_id: `${old}_${String(n).padStart(16, '0')}`,
          created_at: '2026-10-21T17:01:00+00:00',
        })
      ),
      makeCleanupCardRow({ page_run: newest, card_id: `${newest}_0000000000000001` }),
    ];

    const body = await (await GET()).json();

    expect(body.stages[0].pageRun).toBe(newest);
    expect(body.stages[0].cards).toHaveLength(1);
  });
});
