import type { RankingRow } from '@/types/RankingRow';

export type MoversWindow = '7d' | '30d';

/**
 * Movers must start and end inside this band: past it, power scores are dense
 * enough that ordinary results swing teams thousands of places, which reads as
 * noise.
 */
export const RANK_BAND = 500;
const DAY_MS = 86_400_000;

function startOfUtcDay(ms: number): number {
  return ms - (ms % DAY_MS);
}

/**
 * Select the teams with the biggest absolute rank change for a time window.
 *
 * Requires a game inside the window: rankings recompute over a rolling 365-day
 * game window, so a team can move thousands of spots purely from old games
 * aging out.
 */
export function selectTopMovers(rankings: RankingRow[], timeWindow: MoversWindow, maxItems: number): RankingRow[] {
  const field = timeWindow === '7d' ? 'rank_change_7d' : 'rank_change_30d';
  const windowDays = timeWindow === '7d' ? 7 : 30;
  // One reference for the whole dataset, anchored to when the changes were
  // computed, so the pick is stable all week and identical across rows.
  // Truncated to the UTC day because game dates are date-only (midnight UTC).
  const newestCalculated = rankings.reduce((newest, team) => {
    const parsed = team.last_calculated ? Date.parse(team.last_calculated) : NaN;
    return Number.isFinite(parsed) && parsed > newest ? parsed : newest;
  }, -Infinity);
  const reference = startOfUtcDay(Number.isFinite(newestCalculated) ? newestCalculated : Date.now());
  const cutoff = reference - windowDays * DAY_MS;
  return rankings
    .filter((team) => {
      const change = team[field];
      if (change === null || change === undefined || change === 0) return false;
      if ((team.total_games_played ?? 0) < 8) return false;
      if (team.status === 'Not Enough Ranked Games') return false;
      const currentRank = team.rank_in_cohort_final;
      if (currentRank == null || currentRank > RANK_BAND) return false;
      // change = prior - current, so the team's prior rank is current + change.
      if (currentRank + change > RANK_BAND) return false;
      const lastGame = team.last_game ? Date.parse(team.last_game) : NaN;
      if (Number.isNaN(lastGame) || lastGame < cutoff) return false;
      return true;
    })
    .sort((a, b) => Math.abs(b[field] ?? 0) - Math.abs(a[field] ?? 0))
    .slice(0, maxItems);
}
