// Momentum reads the newest played games: a fixture with no score yet must not shrink the sample.
import { describe, expect, it } from 'vitest';
import { calculateMomentum } from './MomentumMeter';
import type { GameWithTeams } from '@/lib/types';

const TEAM_ID = 'team-a';

/** Home games, newest first: a played win or loss, or null for a fixture with no score yet. */
function games(results: ('W' | 'L' | null)[]): GameWithTeams[] {
  return results.map((result, i) => ({
    game_date: `2026-09-${(28 - i).toString().padStart(2, '0')}`,
    home_team_master_id: TEAM_ID,
    away_team_master_id: 'opp',
    home_score: result === null ? null : result === 'W' ? 2 : 0,
    away_score: result === null ? null : result === 'W' ? 0 : 2,
    ml_overperformance: null,
  })) as unknown as GameWithTeams[];
}

describe('calculateMomentum', () => {
  it('reads the eight newest played games, past any unscored fixtures', () => {
    // A ninth, older win falls outside the window: reading the oldest eight instead would score 75.
    const result = calculateMomentum(TEAM_ID, games([null, null, null, 'L', 'W', 'W', 'W', 'W', 'W', 'W', 'W', 'W']));

    expect(result).toEqual({ score: 68.75, totalGames: 8 });
  });

  it('uses every played game when there are fewer than eight', () => {
    expect(calculateMomentum(TEAM_ID, games([null, 'W', 'L', 'W', 'W']))).toEqual({ score: 62.5, totalGames: 4 });
  });

  it('stays neutral with no played games', () => {
    expect(calculateMomentum(TEAM_ID, games([null, null]))).toEqual({ score: 50, totalGames: 0 });
  });
});
