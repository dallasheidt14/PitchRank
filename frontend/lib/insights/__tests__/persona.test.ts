import { describe, it, expect } from 'vitest';
import { findSignatureWins } from '../persona';

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
