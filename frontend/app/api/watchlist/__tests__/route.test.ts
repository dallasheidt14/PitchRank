import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeGame } from '@/test/fixtures';
import { filteringClientMock, serviceClientMock } from '@/test/supabase-mock';

const { mockRequirePremium, mockResolveDefaultWatchlist } = vi.hoisted(() => ({
  mockRequirePremium: vi.fn(),
  mockResolveDefaultWatchlist: vi.fn(),
}));

vi.mock('@/lib/api/requirePremium', () => ({ requirePremium: mockRequirePremium }));
vi.mock('@/lib/api/watchlist', () => ({ resolveDefaultWatchlist: mockResolveDefaultWatchlist }));

import { GET } from '../route';

const FRESH = '11111111-1111-4111-8111-111111111111';
const QUIET = '22222222-2222-4222-8222-222222222222';

let db: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  db = serviceClientMock();
  mockRequirePremium.mockResolvedValue({ user: { id: 'user-1' }, supabase: db.client, error: null });
  mockResolveDefaultWatchlist.mockResolvedValue({
    watchlist: { id: 'wl-1', name: 'My teams', is_default: true, created_at: '', updated_at: '' },
    error: null,
  });
});

describe('GET /api/watchlist', () => {
  // Each card says "Not ranked yet" only for a team short of games, so the route must carry the status.
  it("carries each team's ranking status, and none for a team without a ranking row", async () => {
    db.queueFrom('watchlist_items', {
      data: [
        { team_id_master: FRESH, created_at: '2026-10-01T00:00:00Z' },
        { team_id_master: QUIET, created_at: '2026-10-02T00:00:00Z' },
      ],
      error: null,
    });
    db.queueFrom('team_merge_map', { data: [], error: null });
    db.queueFrom('teams', {
      data: [
        { team_id_master: FRESH, team_name: 'Fresh FC', club_name: null, state: 'AZ', age_group: 'u13', gender: 'M' },
        { team_id_master: QUIET, team_name: 'Quiet FC', club_name: null, state: 'AZ', age_group: 'u13', gender: 'M' },
      ],
      error: null,
    });
    db.queueFrom('rankings_view', {
      data: [{ team_id_master: FRESH, rank_in_cohort_final: null, status: 'Not Enough Ranked Games' }],
      error: null,
    });

    const body = await (await GET()).json();
    const statusOf = (id: string) => body.teams.find((t: { team_id_master: string }) => t.team_id_master === id).status;

    expect(statusOf(FRESH)).toBe('Not Enough Ranked Games');
    expect(statusOf(QUIET)).toBeNull();
  });
});

// Excluded games are not activity. Each of the four activity queries (this week's and the last game, home and
// away) gets its own excluded row, so dropping the filter from any one of them changes a count or a date.
describe('GET /api/watchlist activity', () => {
  const OPPONENT = '33333333-3333-4333-8333-333333333333';
  const filteringDb = filteringClientMock();
  const game = (home: string, away: string, game_date: string, is_excluded: boolean) =>
    makeGame({ home_team_master_id: home, away_team_master_id: away, game_date, is_excluded });

  beforeEach(() => {
    vi.useFakeTimers({ now: new Date('2026-10-14T12:00:00Z'), toFake: ['Date'] });
    filteringDb.reset();
    filteringDb.tableRows.watchlist_items = [
      { watchlist_id: 'wl-1', team_id_master: FRESH, created_at: '2026-10-01T00:00:00Z' },
      { watchlist_id: 'wl-1', team_id_master: QUIET, created_at: '2026-10-02T00:00:00Z' },
    ];
    filteringDb.tableRows.teams = [
      { team_id_master: FRESH, team_name: 'Fresh FC', club_name: null, state: 'AZ', age_group: 'u13', gender: 'M' },
      { team_id_master: QUIET, team_name: 'Quiet FC', club_name: null, state: 'AZ', age_group: 'u13', gender: 'M' },
    ];
    filteringDb.tableRows.games = [
      // Fresh FC played once this week; the two newer rows, home and away, are excluded.
      game(FRESH, OPPONENT, '2026-10-10', false),
      game(FRESH, OPPONENT, '2026-10-11', true),
      game(OPPONENT, FRESH, '2026-10-12', true),
      // Quiet FC has nothing this week. Its newest real game is away, after an older home one, and two newer
      // rows, home and away, are excluded.
      game(QUIET, OPPONENT, '2026-09-01', false),
      game(OPPONENT, QUIET, '2026-09-05', false),
      game(QUIET, OPPONENT, '2026-09-15', true),
      game(OPPONENT, QUIET, '2026-09-20', true),
    ];
    mockRequirePremium.mockResolvedValue({ user: { id: 'user-1' }, supabase: filteringDb.client, error: null });
  });

  afterEach(() => vi.useRealTimers());

  it('counts and dates only games that are not excluded', async () => {
    const body = await (await GET()).json();
    const team = (id: string) => body.teams.find((t: { team_id_master: string }) => t.team_id_master === id);

    expect(team(FRESH)).toMatchObject({ new_games_count: 1, last_game_date: '2026-10-10' });
    expect(team(QUIET)).toMatchObject({ new_games_count: 0, last_game_date: '2026-09-05' });
  });

  // Oldest first, each read from the team's own side: Quiet FC won at home, then lost away.
  it("builds each form strip from that team's own played games", async () => {
    const body = await (await GET()).json();
    const team = (id: string) => body.teams.find((t: { team_id_master: string }) => t.team_id_master === id);

    expect(team(FRESH).last_5_results).toEqual(['W']);
    expect(team(QUIET).last_5_results).toEqual(['W', 'L']);
  });

  it('caps each form strip at the five newest games, reading a game between two watched teams from both sides', async () => {
    const played = (home: string, away: string, game_date: string, home_score: number, away_score: number) =>
      makeGame({ home_team_master_id: home, away_team_master_id: away, game_date, home_score, away_score });
    filteringDb.tableRows.games = [
      played(FRESH, OPPONENT, '2026-10-01', 0, 1), // L, seventh newest: outside
      played(OPPONENT, FRESH, '2026-10-02', 0, 1), // W, sixth newest: outside the window
      played(FRESH, QUIET, '2026-10-03', 2, 1), // Fresh W, Quiet L
      played(FRESH, OPPONENT, '2026-10-04', 1, 1), // D
      played(OPPONENT, FRESH, '2026-10-05', 2, 0), // L
      played(FRESH, OPPONENT, '2026-10-06', 0, 3), // L
      played(OPPONENT, FRESH, '2026-10-07', 1, 2), // W
    ];

    const body = await (await GET()).json();
    const team = (id: string) => body.teams.find((t: { team_id_master: string }) => t.team_id_master === id);

    expect(team(FRESH).last_5_results).toEqual(['W', 'D', 'L', 'L', 'W']);
    expect(team(QUIET).last_5_results).toEqual(['L']);
  });
});
