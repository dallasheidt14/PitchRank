export type GameResult = 'W' | 'L' | 'D';

/** One played game, read from the team's side. */
export interface PlayedResult<G> {
  game: G;
  isHome: boolean;
  teamScore: number;
  oppScore: number;
  result: GameResult;
}

interface GameScores {
  home_team_master_id: string | null;
  home_score?: number | null;
  away_score?: number | null;
}

/**
 * The team's newest `limit` played games, newest first. `games` must already be newest-first, and every game must
 * involve `teamId` under that id: one whose home id is not `teamId` is read as its away game. An unscored game is
 * skipped rather than counted toward `limit`.
 */
export function newestPlayedResults<G extends GameScores>(
  games: readonly G[],
  teamId: string,
  limit: number
): PlayedResult<G>[] {
  const played: PlayedResult<G>[] = [];
  for (const game of games) {
    if (played.length >= limit) break;
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;
    if (teamScore == null || oppScore == null) continue;
    const result = teamScore > oppScore ? 'W' : teamScore < oppScore ? 'L' : 'D';
    played.push({ game, isHome, teamScore, oppScore, result });
  }
  return played;
}
