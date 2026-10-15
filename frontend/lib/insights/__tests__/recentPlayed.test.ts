import { describe, expect, it } from 'vitest';
import { newestPlayedResults } from '../recentPlayed';

const TEAM = 'team-a';

/** One game as [team goals, opponent goals] from the team's side; null for unscored. */
function game(score: [number, number] | null, away = false) {
  const [team, opp] = score ?? [null, null];
  return away
    ? { home_team_master_id: 'opp', away_team_master_id: TEAM, home_score: opp, away_score: team }
    : { home_team_master_id: TEAM, away_team_master_id: 'opp', home_score: team, away_score: opp };
}

describe('newestPlayedResults', () => {
  it('collects the newest played games up to the limit, skipping unscored ones without counting them', () => {
    const games = [game(null), game([2, 0]), game(null), game([1, 1]), game([0, 3]), game([4, 1])];

    expect(newestPlayedResults(games, TEAM, 3).map(({ result }) => result)).toEqual(['W', 'D', 'L']);
  });

  it("reads an away game from the team's side", () => {
    expect(newestPlayedResults([game([3, 1], true)], TEAM, 1)).toEqual([
      expect.objectContaining({ isHome: false, teamScore: 3, oppScore: 1, result: 'W' }),
    ]);
  });

  it('returns what there is when fewer games than the limit were played', () => {
    expect(newestPlayedResults([game(null), game([0, 1])], TEAM, 5)).toHaveLength(1);
  });

  it('skips a game whose score is missing altogether', () => {
    const unscored = { home_team_master_id: TEAM, home_score: undefined, away_score: undefined };

    expect(newestPlayedResults([unscored, game([2, 1])], TEAM, 2)).toHaveLength(1);
  });

  it('skips a game missing either score on its own', () => {
    const teamScoreOnly = { home_team_master_id: TEAM, home_score: 2, away_score: null };
    const oppScoreOnly = { home_team_master_id: TEAM, home_score: null, away_score: 2 };

    expect(
      newestPlayedResults([teamScoreOnly, oppScoreOnly, game([1, 0])], TEAM, 3).map(({ result }) => result)
    ).toEqual(['W']);
  });
});
