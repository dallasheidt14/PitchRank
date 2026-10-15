/**
 * Form Badge — Surging / Slumping / null
 *
 * Combines two signals to avoid false positives:
 *   1. Sustained rank movement: >=10 spots over >=21 days in ranking_history
 *   2. Recent game results: last 5 played games (newest first)
 *
 * Surging = sustained rank improvement AND >=4 wins, 0 losses in last 5
 * Slumping = sustained rank drop AND >=3 losses in last 5
 * Otherwise = null (badge hidden)
 */

import type { InsightInputData, FormBadgeInsight } from './types';
import { newestPlayedResults } from './recentPlayed';

const RANK_MOVEMENT_THRESHOLD = 10;
const MIN_DAY_SPAN = 21;
const RECENT_GAME_WINDOW = 5;
const SURGING_MIN_WINS = 4;
const SLUMPING_MIN_LOSSES = 3;

export function generateFormBadge(data: InsightInputData): FormBadgeInsight | null {
  const { games, rankingHistory, team } = data;

  if (rankingHistory.length < 2) return null;

  // History is ordered most-recent-first by the API.
  const latest = rankingHistory[0];
  const oldest = rankingHistory[rankingHistory.length - 1];

  const getRank = (h: (typeof rankingHistory)[number]) =>
    h.rank_in_cohort_final ?? h.rank_in_cohort_ml ?? h.rank_in_cohort;

  const rankNow = getRank(latest);
  const rankThen = getRank(oldest);
  const rankDelta = rankNow - rankThen; // negative = improved

  const daySpan = Math.round(
    (new Date(latest.snapshot_date).getTime() - new Date(oldest.snapshot_date).getTime()) / (1000 * 60 * 60 * 24)
  );

  if (daySpan < MIN_DAY_SPAN) return null;

  const results = newestPlayedResults(games, team.team_id_master, RECENT_GAME_WINDOW).map(({ result }) => result);
  const wins = results.filter((result) => result === 'W').length;
  const losses = results.filter((result) => result === 'L').length;
  const draws = results.filter((result) => result === 'D').length;

  const total = results.length;
  const recentRecord = draws > 0 ? `${wins}-${losses}-${draws}` : `${wins}-${losses}`;

  if (total < RECENT_GAME_WINDOW) return null; // not enough recent games

  // Surging
  if (rankDelta <= -RANK_MOVEMENT_THRESHOLD && wins >= SURGING_MIN_WINS && losses === 0) {
    return {
      type: 'form_badge',
      label: 'Surging',
      rankDelta,
      daySpan,
      recentRecord,
    };
  }

  // Slumping
  if (rankDelta >= RANK_MOVEMENT_THRESHOLD && losses >= SLUMPING_MIN_LOSSES) {
    return {
      type: 'form_badge',
      label: 'Slumping',
      rankDelta,
      daySpan,
      recentRecord,
    };
  }

  return null;
}
