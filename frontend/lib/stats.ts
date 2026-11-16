import { cache } from 'react';
import { api } from './api';

export interface PublicStats {
  totalTeams: number;
  totalGames: number;
}

/**
 * Conservative floors shown when the live counts are unavailable or not yet loaded.
 * Kept at or below the true live counts so marketing copy never overstates.
 */
export const FALLBACK_STATS: PublicStats = { totalTeams: 58_000, totalGames: 1_700_000 };

/**
 * Live site-wide counts (teams ranked, games analyzed) from the daily
 * homepage_stats cache, via the shared api.getDbStats() — the same source the
 * homepage counter reads, so on-page marketing numbers stay in sync with it.
 *
 * Wraps that fetch with request-scoped dedup (React cache) and a fail-soft
 * fallback so pages calling it stay statically cacheable; pages should set
 * `revalidate` to refresh the value periodically.
 */
export const getPublicStats = cache(async (): Promise<PublicStats> => {
  try {
    const { totalTeams, totalGames } = await api.getDbStats();
    return {
      totalTeams: totalTeams || FALLBACK_STATS.totalTeams,
      totalGames: totalGames || FALLBACK_STATS.totalGames,
    };
  } catch {
    return FALLBACK_STATS;
  }
});
