import type { RankingRow } from '@/types/RankingRow';

/** Defaults describe an established, fully ranked team; override per test. */
export function makeRankingRow(overrides: Partial<RankingRow> = {}): RankingRow {
  return {
    team_id_master: '11111111-1111-1111-1111-111111111111',
    team_name: 'Test FC 2014',
    club_name: 'Test FC',
    league: null,
    distinction: null,
    state: 'AZ',
    age: 12,
    gender: 'M',
    power_score_final: 0.5,
    sos_norm: 0.5,
    offense_norm: 0.5,
    defense_norm: 0.5,
    rank_in_cohort_final: 100,
    wins: 5,
    losses: 2,
    draws: 1,
    games_played: 8,
    total_games_played: 12,
    total_wins: 5,
    total_losses: 2,
    total_draws: 1,
    win_percentage: 62.5,
    status: 'Active',
    rank_change_7d: 40,
    rank_change_30d: 40,
    last_calculated: '2026-08-24T12:00:00Z',
    last_game: '2026-08-22T00:00:00Z',
    ...overrides,
  };
}
