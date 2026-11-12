import { BASE_URL, US_STATES } from '@/lib/constants';

export const LAST_GAMES_SHOWN = 5;

/** The premium offer the PDF and its delivery email both make. */
export const PREMIUM_BENEFITS = [
  'Compare your team side by side with any opponent',
  'See every game this season and which results moved your rank',
  'Follow your rank and PowerScore week by week',
];

export const TRIAL_TERMS = 'Free for 7 days, then $6.99/month or $69.99/year. Cancel anytime.';

/**
 * The upgrade page with the report's team carried through signup. The campaign tags let GA4
 * credit the visit to the report card; the upgrade page's own `source` still records `next`,
 * the same value a paywall tap on that team sends.
 */
export function reportCardUpgradeUrl(teamId: string, medium: 'pdf' | 'email'): string {
  return `${BASE_URL}/upgrade?next=/teams/${teamId}&utm_source=report-card&utm_medium=${medium}&utm_campaign=free-report-card`;
}

export function reportFooter(gamesLabel: string): string {
  return `PitchRank · ${gamesLabel} games analyzed · Rankings update every week`;
}

/** A state's name when it has a rankings board, otherwise its code (DC, a Canadian province). */
export function stateDisplayName(state: string | null): string | null {
  if (!state) return null;
  return US_STATES.find((st) => st.code === state.toLowerCase())?.name ?? state.toUpperCase();
}

/** The share of the cohort at or above this rank, rounded up to a whole percent (1–100) so a team is never placed above its rank. */
export function topPercent(rank: number, cohortTotal: number): number {
  // Multiplying first keeps exact percents exact: (7 / 100) * 100 is 7.000000000000001, which ceils to 8.
  return Math.min(100, Math.max(1, Math.ceil((rank * 100) / cohortTotal)));
}

/**
 * The W-L-D record over the games the ranking run counted, which the report labels as recent.
 * It is not the all-time record the team page shows.
 */
export function formatRecentRecord(ranking: {
  wins?: number | null;
  losses?: number | null;
  draws?: number | null;
}): string {
  return `${ranking.wins ?? 0}-${ranking.losses ?? 0}-${ranking.draws ?? 0}`;
}

/** "Up 12 spots in the last 30 days", or null when the rank did not move. A positive change is a climb. */
export function formatRankMovement(change: number | null): string | null {
  if (change == null || change === 0) return null;
  const spots = Math.abs(change);
  return `${change > 0 ? 'Up' : 'Down'} ${spots} ${spots === 1 ? 'spot' : 'spots'} in the last 30 days`;
}
