import { beforeEach, describe, expect, it, vi } from 'vitest';
import { filteringClientMock } from '@/test/supabase-mock';
import { makeGame } from '@/test/fixtures';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';
const OPPONENT_ID = '22222222-2222-2222-2222-222222222222';

const supabaseMock = filteringClientMock();

vi.mock('@/lib/api/requirePremium', () => ({
  requirePremium: vi.fn(async () => ({ error: null, user: { id: 'user-1' }, supabase: supabaseMock.client })),
}));

vi.mock('@/lib/team-merge', () => ({
  resolveMergedTeamIds: vi.fn(async (_client: unknown, id: string) => ({
    canonicalTeamId: id,
    teamIdsToQuery: new Set([id]),
    teamIdList: [id],
  })),
}));

const { GET } = await import('../route');

const GAME_WINDOW = 50;
const PLAYED_COUNT = 55;
const SCHEDULED_COUNT = 20;

const dayAfter = (start: string, offset: number) => {
  const date = new Date(`${start}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
};

/** Every fifth game is away, so dropping either half of the OR filter is visible. */
const sides = (index: number) =>
  index % 5 === 0
    ? { home_team_master_id: OPPONENT_ID, away_team_master_id: TEAM_ID }
    : { home_team_master_id: TEAM_ID, away_team_master_id: OPPONENT_ID };

const callRoute = () =>
  GET(new Request(`http://localhost/api/insights/${TEAM_ID}`), { params: Promise.resolve({ teamId: TEAM_ID }) });

describe('GET /api/insights/[teamId]', () => {
  beforeEach(() => {
    supabaseMock.reset();
    supabaseMock.tableRows.teams = [
      { team_id_master: TEAM_ID, team_name: 'U13 Lightning', state_code: null, gender: 'Female' },
    ];
    supabaseMock.tableRows.rankings_view = [];
    supabaseMock.tableRows.ranking_history = [];
    supabaseMock.tableRows.games = [
      // More results than the window holds, with varied margins.
      ...Array.from({ length: PLAYED_COUNT }, (_, i) =>
        makeGame({ game_date: dayAfter('2026-01-01', i), home_score: (i % 4) + 1, away_score: i % 3, ...sides(i) })
      ),
      // Newer than every result, so anything that leaks past a guard lands inside
      // the window rather than below it. One row per score guard, then fixtures.
      makeGame({ game_date: '2026-03-01', home_score: 3, away_score: null, ...sides(1) }),
      makeGame({ game_date: '2026-03-02', home_score: null, away_score: 2, ...sides(1) }),
      ...Array.from({ length: SCHEDULED_COUNT }, (_, i) =>
        makeGame({ game_date: dayAfter('2026-03-10', i), home_score: null, away_score: null, ...sides(i) })
      ),
    ];
  });

  it('spends the whole window on results rather than on scheduled fixtures', async () => {
    await callRoute();

    const [gameRows] = supabaseMock.queriesFor('games');
    expect(gameRows).toHaveLength(GAME_WINDOW);
    expect(gameRows.every((row) => row.home_score !== null && row.away_score !== null)).toBe(true);
  });

  it('returns insights computed from those results', async () => {
    const response = await callRoute();
    expect(response.status).toBe(200);

    const body = await response.json();
    const consistency = body.insights.find((insight: { type: string }) => insight.type === 'consistency_score');
    // The <3-games fallback reports a flat 0 here, so a non-zero spread is only
    // reachable if real results reached the generator.
    expect(consistency.details.goalDifferentialStdDev).toBeGreaterThan(0);
  });
});
