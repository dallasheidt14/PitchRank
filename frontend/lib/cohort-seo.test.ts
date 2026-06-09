import { describe, expect, it } from 'vitest';
import { computeCohortModules } from './cohort-seo';
import type { RankingRow } from '@/types/RankingRow';

function makeTeam(overrides: Partial<RankingRow> = {}): RankingRow {
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
    rank_in_cohort_final: 1,
    wins: 5,
    losses: 2,
    draws: 1,
    games_played: 8,
    total_games_played: 8,
    total_wins: 5,
    total_losses: 2,
    total_draws: 1,
    win_percentage: 62.5,
    status: 'Active',
    ...overrides,
  };
}

describe('computeCohortModules', () => {
  it('uses activeCount for totalTeams, not the capped teams-array length', () => {
    // The page only fetches the top 2,000; here a single team stands in for that
    // truncated slice while the true cohort has 6,170 Active teams.
    const result = computeCohortModules([makeTeam()], 6170, 'National', 'U12', 'Boys', true, 'national', 'male');

    expect(result.totalTeams).toBe(6170);
    expect(result.positioningHook).toBe('one of the deepest groups in the country');
  });

  it('falls back to teams.length when the active count is unavailable (0)', () => {
    const teams = [makeTeam({ team_id_master: 'a' }), makeTeam({ team_id_master: 'b' })];

    const result = computeCohortModules(teams, 0, 'Arizona', 'U12', 'Boys', false, 'az', 'male');

    expect(result.totalTeams).toBe(2);
  });
});
