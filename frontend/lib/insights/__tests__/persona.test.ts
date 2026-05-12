import { describe, it, expect } from 'vitest';
import { findSignatureWins, buildPersonaTrait } from '../persona';
import type { InsightInputData } from '../types';

const TEAM_ID = 'team-a';

function game(opts: { opp_rank: number | null; team_score: number; opp_score: number; team_is_home?: boolean }) {
  const isHome = opts.team_is_home ?? true;
  return {
    game_date: '2026-05-01',
    home_team_master_id: isHome ? TEAM_ID : 'opp',
    away_team_master_id: isHome ? 'opp' : TEAM_ID,
    home_score: isHome ? opts.team_score : opts.opp_score,
    away_score: isHome ? opts.opp_score : opts.team_score,
    opponent_rank: opts.opp_rank,
    opponent_power_score: null,
  };
}

describe('findSignatureWins', () => {
  it('returns up to 3 wins sorted by lowest opponent_rank, tie-break by margin', () => {
    const games = [
      game({ opp_rank: 50, team_score: 5, opp_score: 0 }), // rank too high, ignored unless ≤25
      game({ opp_rank: 11, team_score: 2, opp_score: 0 }),
      game({ opp_rank: 4, team_score: 3, opp_score: 1 }),
      game({ opp_rank: 4, team_score: 4, opp_score: 0 }), // same rank, bigger margin — wins tiebreak
      game({ opp_rank: 18, team_score: 1, opp_score: 0 }),
      game({ opp_rank: 7, team_score: 0, opp_score: 2 }), // a loss, ignored
    ];

    const result = findSignatureWins(games, TEAM_ID, 3);

    expect(result).toEqual([
      { opponent_rank: 4, teamScore: 4, oppScore: 0 },
      { opponent_rank: 4, teamScore: 3, oppScore: 1 },
      { opponent_rank: 11, teamScore: 2, oppScore: 0 },
    ]);
  });

  it('skips games with null opponent_rank or null scores', () => {
    const games = [
      game({ opp_rank: null, team_score: 5, opp_score: 0 }),
      { ...game({ opp_rank: 3, team_score: 0, opp_score: 0 }), home_score: null },
      game({ opp_rank: 8, team_score: 2, opp_score: 0 }),
    ];

    const result = findSignatureWins(games, TEAM_ID, 3);

    expect(result).toEqual([{ opponent_rank: 8, teamScore: 2, oppScore: 0 }]);
  });

  it('returns empty array when no wins exist', () => {
    const games = [game({ opp_rank: 5, team_score: 0, opp_score: 1 })];
    expect(findSignatureWins(games, TEAM_ID, 3)).toEqual([]);
  });
});

function buildInput(overrides: Partial<InsightInputData> = {}): InsightInputData {
  return {
    team: {
      team_id_master: TEAM_ID,
      team_name: 'Test FC',
      state: 'WI',
      age: 14,
      gender: 'F',
    },
    ranking: {
      rank_in_cohort_final: null,
      power_score_final: null,
      sos_norm: null,
      wins: 0,
      losses: 0,
      draws: 0,
      games_played: 0,
      rank_change_7d: null,
      rank_change_30d: null,
      offense_norm: null,
      defense_norm: null,
      perf_centered: null,
    },
    games: [],
    rankingHistory: [],
    cohortStats: { totalTeams: 100, medianPowerScore: 50, percentile: 50 },
    stateCohort: null,
    ...overrides,
  };
}

describe('buildPersonaTrait', () => {
  it('returns signature-wins trait when ≥2 top-25 wins exist', () => {
    const data = buildInput({
      games: [
        game({ opp_rank: 3, team_score: 2, opp_score: 1 }),
        game({ opp_rank: 7, team_score: 4, opp_score: 0 }),
        game({ opp_rank: 12, team_score: 1, opp_score: 0 }),
      ],
    });
    expect(buildPersonaTrait(data)).toBe('Beat #3, #7, and #12 this season');
  });

  it('uses "and" for exactly two signature wins', () => {
    const data = buildInput({
      games: [game({ opp_rank: 5, team_score: 2, opp_score: 1 }), game({ opp_rank: 9, team_score: 3, opp_score: 0 })],
    });
    expect(buildPersonaTrait(data)).toBe('Beat #5 and #9 this season');
  });

  it('falls through to big-game record when fewer than 2 top-25 wins but ≥3 top-10 games', () => {
    const data = buildInput({
      games: [
        game({ opp_rank: 5, team_score: 2, opp_score: 1 }), // win vs top-10 (and top-25)
        game({ opp_rank: 8, team_score: 0, opp_score: 2 }), // loss vs top-10
        game({ opp_rank: 9, team_score: 1, opp_score: 1 }), // draw vs top-10
      ],
    });
    // Only 1 top-25 win → signature-wins requires ≥2 → falls through to big-game record.
    expect(buildPersonaTrait(data)).toBe('1-1-1 vs top-10 opponents');
  });

  it('falls through to state leaderboard when in top 5 of state cohort', () => {
    const data = buildInput({
      games: [],
      stateCohort: { rank: 3, totalTeams: 42 },
    });
    expect(buildPersonaTrait(data)).toBe('#3 in WI U14 Girls');
  });

  it('falls through to national percentile when in top 5% nationally', () => {
    const data = buildInput({
      games: [],
      stateCohort: null,
      cohortStats: { totalTeams: 500, medianPowerScore: 50, percentile: 97 },
    });
    expect(buildPersonaTrait(data)).toBe('Top 3% nationally');
  });

  it('falls through to margin profile when ≥6 wins played', () => {
    const games = Array.from({ length: 6 }, () => game({ opp_rank: 80, team_score: 4, opp_score: 1 }));
    const data = buildInput({ games });
    expect(buildPersonaTrait(data)).toBe('Wins by 3.0 goals on average');
  });

  it('returns null when nothing qualifies', () => {
    const data = buildInput({ games: [game({ opp_rank: 80, team_score: 1, opp_score: 0 })] });
    expect(buildPersonaTrait(data)).toBeNull();
  });

  it('skips state-leaderboard when state cohort is too small', () => {
    const data = buildInput({ stateCohort: { rank: 1, totalTeams: 3 } });
    expect(buildPersonaTrait(data)).toBeNull();
  });
});
