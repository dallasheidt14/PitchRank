import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NextRequest } from 'next/server';
import { filteringClientMock } from '@/test/supabase-mock';
import { makeGame } from '@/test/fixtures';
import type { ReportCardProps } from '@/lib/pdf';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';
const MERGED_ID = '99999999-9999-9999-9999-999999999999';
const PAST_OPP = '22222222-2222-2222-2222-222222222222';
const NEAR_OPP = '33333333-3333-3333-3333-333333333333';
const FAR_OPP = '44444444-4444-4444-4444-444444444444';
const OTHER_TEAM = '55555555-5555-5555-5555-555555555555';
const LATER_OPP = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const OLD_PAST_OPP = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';

const supabaseMock = filteringClientMock();
let stateRankRpcResult: { state_rank: number } | null = null;
let countFails = false;
// get_team_state_rank RETURNS TABLE: awaited directly PostgREST answers an array, and only
// .maybeSingle() unwraps it to one row.
const rpc = vi.fn((name: string, _args: Record<string, string>) => {
  if (name !== 'get_team_state_rank') throw new Error(`unexpected rpc ${name}`);
  const rows = stateRankRpcResult ? [stateRankRpcResult] : [];
  return {
    maybeSingle: async () => ({ data: rows[0] ?? null, error: null }),
    then: (onFulfilled: (v: unknown) => unknown, onRejected?: (e: unknown) => unknown) =>
      Promise.resolve({ data: rows, error: null }).then(onFulfilled, onRejected),
  };
});

const { renderToBuffer, sendReportCardEmail, getActiveRankingsCount } = vi.hoisted(() => ({
  renderToBuffer: vi.fn(async (_element: unknown) => Buffer.from('pdf')),
  sendReportCardEmail: vi.fn(async (..._args: unknown[]) => true),
  getActiveRankingsCount: vi.fn(),
}));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: vi.fn(async () => ({ from: supabaseMock.client.from, rpc })),
}));
vi.mock('@/lib/api/optionalAuth', () => ({ optionalAuth: vi.fn(async () => ({ user: null })) }));
vi.mock('@/lib/api/rateLimit', () => ({ checkRateLimit: () => true, getClientIp: () => '203.0.113.1' }));
vi.mock('@/lib/beehiiv', () => ({ subscribeFreeLead: vi.fn(async () => {}), enrollInAutomation: vi.fn() }));
vi.mock('@/lib/email', () => ({ sendReportCardEmail }));
vi.mock('@/lib/stats', () => ({ getPublicStats: vi.fn(async () => ({ totalGames: 1_100_000, totalTeams: 1 })) }));
vi.mock('@/lib/pdf', () => ({ TeamReportCard: () => null }));
vi.mock('@react-pdf/renderer', () => ({ renderToBuffer }));
vi.mock('@/lib/api', () => ({ api: { getActiveRankingsCount } }));

const { POST } = await import('../route');

const callRoute = (
  body: Record<string, unknown> = { teamId: TEAM_ID, email: 'parent@example.com' },
  contentType = 'application/json'
) =>
  POST(
    new Request('http://localhost/api/reports/team-card', {
      method: 'POST',
      headers: { 'content-type': contentType },
      body: JSON.stringify(body),
    }) as unknown as NextRequest
  );

const pdfProps = () => (renderToBuffer.mock.calls[0][0] as { props: ReportCardProps }).props;

const cohortRow = (id: string, state: string) => ({
  team_id_master: id,
  age: 13,
  gender: 'M',
  state,
  status: 'Active',
});

const fixture = (game_date: string, home: string, away: string, overrides: Record<string, unknown> = {}) =>
  makeGame({
    game_date,
    home_team_master_id: home,
    away_team_master_id: away,
    home_score: null,
    away_score: null,
    ...overrides,
  });

const result = (game_date: string, home: string, away: string, home_score: number, away_score: number) =>
  makeGame({ game_date, home_team_master_id: home, away_team_master_id: away, home_score, away_score });

// West of UTC, so a date read as UTC midnight would print the day before.
const ORIGINAL_TZ = process.env.TZ;
beforeAll(() => {
  process.env.TZ = 'America/Los_Angeles';
});
afterAll(() => {
  if (ORIGINAL_TZ === undefined) delete process.env.TZ;
  else process.env.TZ = ORIGINAL_TZ;
});

describe('POST /api/reports/team-card', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-11T18:00:00Z'));
    vi.clearAllMocks();
    supabaseMock.reset();
    stateRankRpcResult = null;
    countFails = false;
    // The boards' count, answered from the mock's rankings_view rows by the arguments it is given.
    getActiveRankingsCount.mockImplementation(async (region: string | null, ageGroup: string, gender: string) =>
      countFails
        ? null
        : (supabaseMock.tableRows.rankings_view ?? []).filter(
            (row) =>
              row.status === 'Active' &&
              `u${row.age}` === ageGroup &&
              row.gender === gender &&
              (region === null || row.state === region)
          ).length
    );

    supabaseMock.tableRows.teams = [
      {
        team_id_master: TEAM_ID,
        team_name: 'SCSA Eleven U13B Red',
        club_name: 'SCSA',
        state_code: 'IN',
        age_group: 'u13',
        gender: 'Male',
      },
      { team_id_master: PAST_OPP, team_name: 'Boilers FC Gold' },
      { team_id_master: NEAR_OPP, team_name: 'FWSC Frankfurt' },
      { team_id_master: FAR_OPP, team_name: 'Union FC Teal' },
      { team_id_master: LATER_OPP, team_name: 'Indy Premier' },
      { team_id_master: OLD_PAST_OPP, team_name: 'Boilers 2013 (old record)' },
    ];
    // This team absorbed MERGED_ID; the opponent PAST_OPP absorbed OLD_PAST_OPP.
    supabaseMock.tableRows.team_merge_map = [
      { deprecated_team_id: MERGED_ID, canonical_team_id: TEAM_ID },
      { deprecated_team_id: OLD_PAST_OPP, canonical_team_id: PAST_OPP },
    ];
    // rankings_view carries no state rank column, as in production. National #2 differs from state #1.
    supabaseMock.tableRows.rankings_view = [
      {
        ...cohortRow(TEAM_ID, 'IN'),
        power_score_final: 0.48473,
        rank_in_cohort_final: 2,
        rank_change_30d: 293,
        wins: 25,
        losses: 4,
        draws: 1,
        games_played: 30,
        total_wins: 60,
        total_losses: 20,
        total_draws: 5,
        last_calculated: '2026-11-11T01:19:00Z',
      },
      cohortRow('66666666-6666-6666-6666-666666666666', 'IN'),
      cohortRow('77777777-7777-7777-7777-777777777777', 'IN'),
      cohortRow('88888888-8888-8888-8888-888888888888', 'OH'),
    ];
    supabaseMock.tableRows.state_rankings_view = [{ team_id_master: TEAM_ID, rank_in_state_final: 1 }];
    supabaseMock.tableRows.games = [
      // A hidden result newer than every shown one.
      { ...result('2026-11-01', TEAM_ID, PAST_OPP, 9, 0), is_excluded: true },
      // The newest shown result is stored under the id merged into this team, and again against the
      // opponent's old record, so the two copies name the opponent differently.
      result('2026-10-31', MERGED_ID, PAST_OPP, 3, 0),
      result('2026-10-31', OLD_PAST_OPP, TEAM_ID, 0, 3),
      // Stored only against the opponent's old record.
      result('2026-10-24', OLD_PAST_OPP, TEAM_ID, 1, 0),
      result('2026-10-17', TEAM_ID, PAST_OPP, 6, 0),
      // The same match stored again under the merged id.
      result('2026-10-17', MERGED_ID, PAST_OPP, 6, 0),
      // Two different games on one day.
      result('2026-10-10', TEAM_ID, PAST_OPP, 2, 2),
      result('2026-10-10', TEAM_ID, LATER_OPP, 1, 0),
      result('2026-10-03', TEAM_ID, PAST_OPP, 5, 0),
      result('2026-09-26', TEAM_ID, PAST_OPP, 3, 1),
      result('2026-09-19', TEAM_ID, PAST_OPP, 4, 0),
      // Already past, a later fixture listed first, a hidden earlier one, the next one (under the merged id),
      // one beyond the window, and another team's.
      fixture('2026-11-08', TEAM_ID, PAST_OPP),
      fixture('2026-11-29', TEAM_ID, LATER_OPP),
      fixture('2026-11-15', TEAM_ID, PAST_OPP, { is_excluded: true }),
      fixture('2026-11-20', NEAR_OPP, MERGED_ID),
      fixture('2026-12-25', TEAM_ID, FAR_OPP),
      fixture('2026-11-14', OTHER_TEAM, FAR_OPP),
    ];
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('hands the PDF the state rank from the state view, which rankings_view does not carry', async () => {
    const res = await callRoute();

    expect(res.status).toBe(201);
    expect(pdfProps().ranking.rank_in_state_final).toBe(1);
    expect(rpc).not.toHaveBeenCalledWith('get_team_state_rank', expect.anything());
  });

  it('counts the cohort the way the rankings boards do, nationally and in the state', async () => {
    await callRoute();

    expect(getActiveRankingsCount).toHaveBeenCalledWith(null, 'u13', 'M');
    expect(getActiveRankingsCount).toHaveBeenCalledWith('IN', 'u13', 'M');
    expect(pdfProps().cohortTotal).toBe(4);
    expect(pdfProps().stateCohortTotal).toBe(3);
  });

  it('leaves the totals out rather than printing a wrong one when a count fails', async () => {
    countFails = true;

    const res = await callRoute();

    expect(res.status).toBe(201);
    expect(pdfProps().cohortTotal).toBeNull();
    expect(pdfProps().stateCohortTotal).toBeNull();
    expect(sendReportCardEmail.mock.calls[0][0]).toMatchObject({ rankNational: 2, topPct: null });
  });

  it('falls back to the state rank RPC when the view returns no row', async () => {
    supabaseMock.tableRows.state_rankings_view = [];
    stateRankRpcResult = { state_rank: 7 };

    await callRoute();

    expect(rpc).toHaveBeenCalledWith('get_team_state_rank', { p_team_id: TEAM_ID });
    expect(pdfProps().ranking.rank_in_state_final).toBe(7);
  });

  it('lists the last 5 results across merged ids, newest first, once each, skipping hidden games', async () => {
    await callRoute();

    expect(pdfProps().games).toEqual([
      { game_date: 'Oct 31', opponent_name: 'Boilers FC Gold', score: '3-0', result: 'W' },
      { game_date: 'Oct 24', opponent_name: 'Boilers FC Gold', score: '0-1', result: 'L' },
      { game_date: 'Oct 17', opponent_name: 'Boilers FC Gold', score: '6-0', result: 'W' },
      { game_date: 'Oct 10', opponent_name: 'Boilers FC Gold', score: '2-2', result: 'D' },
      { game_date: 'Oct 10', opponent_name: 'Indy Premier', score: '1-0', result: 'W' },
    ]);
  });

  it('keeps two different opponents who share a name and a scoreline on one day', async () => {
    supabaseMock.tableRows.teams.push({ team_id_master: OTHER_TEAM, team_name: 'Boilers FC Gold' });
    supabaseMock.tableRows.games = [
      result('2026-10-10', TEAM_ID, PAST_OPP, 2, 0),
      result('2026-10-10', TEAM_ID, OTHER_TEAM, 2, 0),
    ];

    await callRoute();

    expect(pdfProps().games).toHaveLength(2);
  });

  it('passes a team with no state through without a state count, leaving the guards to the PDF and email', async () => {
    supabaseMock.tableRows.teams[0].state_code = null;
    // state_rankings_view has no row for a team with no state, and get_team_state_rank still ranks it
    // among the cohort's other stateless teams.
    supabaseMock.tableRows.state_rankings_view = [];
    stateRankRpcResult = { state_rank: 1 };

    await callRoute();

    expect(getActiveRankingsCount).toHaveBeenCalledTimes(1);
    expect(getActiveRankingsCount).toHaveBeenCalledWith(null, 'u13', 'M');
    expect(pdfProps().team.state).toBeNull();
    expect(pdfProps().stateCohortTotal).toBeNull();
    expect(sendReportCardEmail.mock.calls[0][0]).toMatchObject({ state: null, rankState: 1 });
  });

  it('names the next unscored fixture inside the window, under any merged id', async () => {
    // A scored row dated before the fixture, so a lost score filter would name it instead.
    supabaseMock.tableRows.games.push(result('2026-11-12', TEAM_ID, PAST_OPP, 2, 0));

    await callRoute();

    expect(pdfProps().nextGame).toEqual({ game_date: 'Nov 20', opponent_name: 'FWSC Frankfurt' });
  });

  it('names no opponent when the only fixture is beyond the window', async () => {
    supabaseMock.tableRows.games = supabaseMock.tableRows.games.filter(
      (g) => g.game_date !== '2026-11-20' && g.game_date !== '2026-11-29'
    );

    await callRoute();

    expect(pdfProps().nextGame).toBeNull();
  });

  it('names no opponent when the next fixture has no known opponent', async () => {
    supabaseMock.tableRows.teams = supabaseMock.tableRows.teams.filter((t) => t.team_id_master !== NEAR_OPP);

    await callRoute();

    expect(pdfProps().nextGame).toBeNull();
  });

  it('counts the window from the business calendar day, so an evening request still finds that day', async () => {
    // 8pm in Phoenix on Nov 11 is already Nov 12 in UTC.
    vi.setSystemTime(new Date('2026-11-12T03:00:00Z'));
    supabaseMock.tableRows.games.push(fixture('2026-11-11', TEAM_ID, LATER_OPP));

    await callRoute();

    expect(pdfProps().nextGame).toEqual({ game_date: 'Nov 11', opponent_name: 'Indy Premier' });
    expect(pdfProps().generatedDate).toBe('November 11, 2026');
  });

  it('dates the rankings by the run and the report by the request, in the business timezone', async () => {
    await callRoute();

    expect(pdfProps().rankingsAsOf).toBe('November 10, 2026');
    expect(pdfProps().generatedDate).toBe('November 11, 2026');
  });

  it('emails the same numbers the PDF shows: national and state rank, top percent, and the recent record', async () => {
    await callRoute();

    expect(sendReportCardEmail.mock.calls[0][0]).toEqual({
      email: 'parent@example.com',
      teamId: TEAM_ID,
      teamName: 'SCSA Eleven U13B Red',
      rankNational: 2,
      rankState: 1,
      state: 'IN',
      powerScore: 0.48473,
      topPct: 50,
      record: '25-4-1',
      rankChange30d: 293,
      gamesLabel: '1.1M+',
      pdfBuffer: Buffer.from('pdf'),
    });
  });

  it('refuses a body that is not sent as JSON, before reading it', async () => {
    const res = await callRoute({ teamId: TEAM_ID, email: 'parent@example.com' }, 'text/plain');

    expect(res.status).toBe(415);
    expect(sendReportCardEmail).not.toHaveBeenCalled();
  });

  it('refuses an email address longer than any real one, even when it is otherwise well formed', async () => {
    const res = await callRoute({ teamId: TEAM_ID, email: `${'a'.repeat(250)}@example.com` });

    expect(res.status).toBe(400);
    expect(renderToBuffer).not.toHaveBeenCalled();
  });
});
