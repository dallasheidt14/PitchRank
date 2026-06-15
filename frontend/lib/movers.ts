import type { RankingRow } from '@/types/RankingRow';

export type MoversWindow = '7d' | '30d';

/**
 * Select the teams with the biggest absolute rank change for a time window.
 *
 * Mirrors the prior client-side selection so server-computed movers match what
 * the homepage used to render. Excludes teams with too few games or that are not
 * yet fully ranked, then orders by the magnitude of the change.
 */
export function selectTopMovers(rankings: RankingRow[], timeWindow: MoversWindow, maxItems: number): RankingRow[] {
  const field = timeWindow === '7d' ? 'rank_change_7d' : 'rank_change_30d';
  return rankings
    .filter((team) => {
      const change = team[field];
      if (change === null || change === undefined || Math.abs(change) === 0) return false;
      if ((team.total_games_played ?? 0) < 8) return false;
      if (team.status === 'Not Enough Ranked Games') return false;
      return true;
    })
    .sort((a, b) => Math.abs(b[field] ?? 0) - Math.abs(a[field] ?? 0))
    .slice(0, maxItems);
}
