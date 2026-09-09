import { beforeEach, describe, expect, it, vi } from 'vitest';
import { filteringClientMock } from '@/test/supabase-mock';
import { makeGame } from '@/test/fixtures';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';
const OPPONENT_ID = '22222222-2222-2222-2222-222222222222';
const DEPRECATED_ID = '33333333-3333-3333-3333-333333333333';

const supabaseMock = filteringClientMock();

vi.mock('@supabase/supabase-js', () => ({
  createClient: () => supabaseMock.client,
  SupabaseClient: class {},
}));

const { api } = await import('./api');

const homeGame = (game_date: string, home_score: number | null, away_score: number | null) =>
  makeGame({ game_date, home_score, away_score, home_team_master_id: TEAM_ID, away_team_master_id: OPPONENT_ID });

const awayGame = (game_date: string, home_score: number | null, away_score: number | null) =>
  makeGame({ game_date, home_score, away_score, home_team_master_id: OPPONENT_ID, away_team_master_id: TEAM_ID });

describe('getTeamTrajectory', () => {
  beforeEach(() => {
    supabaseMock.reset();
    supabaseMock.tableRows.team_merge_map = [{ canonical_team_id: TEAM_ID, deprecated_team_id: DEPRECATED_ID }];
    supabaseMock.tableRows.games = [
      // Spring block: one home loss, one away win.
      homeGame('2026-04-12', 1, 4),
      awayGame('2026-04-18', 0, 2),
      // September block, the third game filed under a merged-away team id.
      homeGame('2026-09-06', 3, 1),
      awayGame('2026-09-08', 1, 2),
      makeGame({
        game_date: '2026-09-10',
        home_score: 4,
        away_score: 1,
        home_team_master_id: DEPRECATED_ID,
        away_team_master_id: OPPONENT_ID,
      }),
      // Each half-scored row leaks past exactly one of the two score guards, and
      // sits far enough out to open a period of its own when it does.
      homeGame('2026-10-20', 3, null),
      homeGame('2026-10-22', null, 2),
      homeGame('2026-11-01', null, null),
      makeGame({ game_date: '2026-12-01', home_score: 5, away_score: 0, is_excluded: true }),
    ];
  });

  it('builds one period per block of played games, merged ids included', async () => {
    const trajectory = await api.getTeamTrajectory(TEAM_ID);

    expect(trajectory.map((point) => point.period_start.slice(0, 10))).toEqual(['2026-04-12', '2026-09-06']);
    expect(trajectory.map((point) => point.games_played)).toEqual([2, 3]);
  });

  it('attributes goals to the side the team actually played on', async () => {
    const trajectory = await api.getTeamTrajectory(TEAM_ID);

    expect(trajectory[0].avg_goals_for).toBe(1.5);
    expect(trajectory[0].avg_goals_against).toBe(2);
    expect(trajectory[1].avg_goals_for).toBe(3);
    expect(trajectory[1].avg_goals_against).toBe(1);
  });

  it('returns no periods for a team whose games are all still scheduled', async () => {
    supabaseMock.tableRows.games = [homeGame('2026-10-04', null, null), awayGame('2026-10-18', null, null)];

    expect(await api.getTeamTrajectory(TEAM_ID)).toEqual([]);
  });
});

describe('getCommonOpponents', () => {
  const OTHER_TEAM_ID = '44444444-4444-4444-4444-444444444444';

  beforeEach(() => {
    supabaseMock.reset();
    supabaseMock.tableRows.teams = [{ team_id_master: OPPONENT_ID, team_name: 'Shared FC' }];
    supabaseMock.tableRows.games = [
      makeGame({
        game_date: '2026-05-01',
        home_score: 3,
        away_score: 1,
        home_team_master_id: TEAM_ID,
        away_team_master_id: OPPONENT_ID,
      }),
      // All three are newer than the result above and against the same opponent, so
      // each outranks it the moment the guard that excludes it goes. The half-scored
      // pair leaks past exactly one of the two score guards; the last needs both.
      makeGame({
        game_date: '2026-09-01',
        home_score: 3,
        away_score: null,
        home_team_master_id: TEAM_ID,
        away_team_master_id: OPPONENT_ID,
      }),
      makeGame({
        game_date: '2026-09-02',
        home_score: null,
        away_score: 2,
        home_team_master_id: TEAM_ID,
        away_team_master_id: OPPONENT_ID,
      }),
      makeGame({
        game_date: '2026-10-01',
        home_score: null,
        away_score: null,
        home_team_master_id: TEAM_ID,
        away_team_master_id: OPPONENT_ID,
      }),
      makeGame({
        game_date: '2026-05-02',
        home_score: 0,
        away_score: 2,
        home_team_master_id: OTHER_TEAM_ID,
        away_team_master_id: OPPONENT_ID,
      }),
    ];
  });

  it('reports the last played meeting, not a scheduled one that outranks it', async () => {
    const [common] = await api.getCommonOpponents(TEAM_ID, OTHER_TEAM_ID);

    expect(common.opponent_name).toBe('Shared FC');
    expect(common.game_date).toBe('2026-05-01');
    expect(common.team1_result).toBe('W');
    expect(common.team1_score).toBe(3);
  });
});
