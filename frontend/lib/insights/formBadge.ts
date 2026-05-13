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

  // Walk newest-first, collect up to RECENT_GAME_WINDOW played results.
  let wins = 0,
    losses = 0,
    draws = 0;
  for (const game of games) {
    if (wins + losses + draws >= RECENT_GAME_WINDOW) break;
    const isHome = game.home_team_master_id === team.team_id_master;
    const ts = isHome ? game.home_score : game.away_score;
    const os = isHome ? game.away_score : game.home_score;
    if (ts === null || os === null) continue;
    if (ts > os) wins++;
    else if (ts < os) losses++;
    else draws++;
  }

  const total = wins + losses + draws;
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
