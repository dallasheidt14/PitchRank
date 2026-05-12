/**
 * Consistency Score Generator
 *
 * Computes a 0-100 score representing team reliability based on:
 * - Standard deviation of goal differential (capped at ±6 to match v53e)
 * - PowerScore volatility over time
 * - Streak fragmentation (how often results change)
 *
 * ALIGNED WITH v53e:
 * - Goal diff capped at ±6 (GOAL_DIFF_CAP in v53e Layer 2)
 * - Uses similar weighting philosophy to ranking components
 */

import type { InsightInputData, ConsistencyInsight } from './types';

/**
 * v53e GOAL_DIFF_CAP constant - blowout games beyond ±6 goals
 * are capped to prevent single games from distorting metrics
 */
const GOAL_DIFF_CAP = 6;

/** Window of most-recent played games used for consistency inputs */
const RECENCY_WINDOW = 15;

/**
 * Walk newest-first games and collect up to RECENCY_WINDOW played
 * results (those with both scores present), capping goal diff at ±6.
 */
function extractRecentPlayedResults(
  games: InsightInputData['games'],
  teamId: string
): Array<{ goalDiff: number; result: 'W' | 'L' | 'D' }> {
  const out: Array<{ goalDiff: number; result: 'W' | 'L' | 'D' }> = [];
  for (const game of games) {
    if (out.length >= RECENCY_WINDOW) break;
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;
    if (teamScore === null || oppScore === null) continue;
    const rawDiff = teamScore - oppScore;
    const goalDiff = Math.max(-GOAL_DIFF_CAP, Math.min(GOAL_DIFF_CAP, rawDiff));
    const result = teamScore > oppScore ? 'W' : teamScore < oppScore ? 'L' : 'D';
    out.push({ goalDiff, result });
  }
  return out;
}

/**
 * Calculate standard deviation of goal differentials over the pre-computed
 * recency window. Caller is responsible for capping goal diffs.
 */
function calculateGoalDiffStdDev(recent: Array<{ goalDiff: number }>): number {
  if (recent.length < 2) return 0;
  const goalDiffs = recent.map((r) => r.goalDiff);
  const mean = goalDiffs.reduce((a, b) => a + b, 0) / goalDiffs.length;
  const variance = goalDiffs.reduce((sum, gd) => sum + Math.pow(gd - mean, 2), 0) / goalDiffs.length;
  return Math.sqrt(variance);
}

/**
 * Calculate streak fragmentation over the pre-computed recency window.
 * Higher value = more fragmented (more result changes). Returns 0..1.
 * Transition count is order-invariant.
 */
function calculateStreakFragmentation(recent: Array<{ result: 'W' | 'L' | 'D' }>): number {
  if (recent.length < 2) return 0;
  let transitions = 0;
  for (let i = 1; i < recent.length; i++) {
    if (recent[i].result !== recent[i - 1].result) transitions++;
  }
  return transitions / (recent.length - 1);
}

/**
 * Calculate PowerScore volatility from ranking history.
 *
 * Returns stddev of residuals around the best-fit trend line, divided by
 * the mean — so a team climbing the ranks linearly is NOT penalized for
 * climbing. Only deviations from the trend count as volatility.
 */
function calculatePowerScoreVolatility(rankingHistory: InsightInputData['rankingHistory']): number {
  const scoresNewestFirst = rankingHistory.map((h) => h.power_score_final).filter((s): s is number => s !== null);

  if (scoresNewestFirst.length < 4) return 0;

  // Reverse to chronological order so x=0..n-1 is oldest..newest.
  const scores = scoresNewestFirst.slice().reverse();
  const n = scores.length;
  const xMean = (n - 1) / 2;
  const yMean = scores.reduce((s, v) => s + v, 0) / n;

  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - xMean) * (scores[i] - yMean);
    den += (i - xMean) ** 2;
  }
  const slope = den === 0 ? 0 : num / den;
  const intercept = yMean - slope * xMean;

  let sumSq = 0;
  for (let i = 0; i < n; i++) {
    const predicted = intercept + slope * i;
    sumSq += (scores[i] - predicted) ** 2;
  }
  const residualStdDev = Math.sqrt(sumSq / n);

  return residualStdDev / Math.max(yMean, 0.01);
}

/**
 * Convert raw metrics to a 0-100 consistency score
 * Higher score = more consistent
 *
 * Weights aligned with v53e philosophy:
 * - Goal differential variance: 50% (primary performance signal)
 * - Streak fragmentation: 30% (result predictability)
 * - Power score volatility: 20% (rank stability)
 *
 * Score distribution targets:
 * - Top 10% teams (very consistent): 75-100
 * - Average teams: 45-65
 * - Bottom 10% (highly volatile): 0-35
 */
function calculateConsistencyScore(
  goalDiffStdDev: number,
  streakFragmentation: number,
  powerScoreVolatility: number
): number {
  // With ±6 cap goal diffs:
  // - Very consistent teams: stdDev < 1.5 (tight margins)
  // - Average teams: stdDev 2.0-2.5
  // - Volatile teams: stdDev > 3.0 (blowouts and close losses)
  //
  // Score mapping (using shifted sigmoid-like curve for better spread):
  // stdDev 1.0 -> ~85, stdDev 2.0 -> ~55, stdDev 3.0 -> ~25
  const gdScore = Math.max(0, Math.min(100, 115 - goalDiffStdDev * 30));

  // Streak fragmentation (how often results change W/L/D):
  // - Long streaks (0.2): very predictable -> high score
  // - Alternating results (0.7+): unpredictable -> low score
  // Shifted to center around typical values (0.4-0.6)
  const sfScore = Math.max(0, Math.min(100, 130 - streakFragmentation * 150));

  // Power score volatility (residual stddev / mean):
  // - Stable ranking (< 0.05): very consistent -> high score
  // - Volatile ranking (> 0.15): jumping around -> low score
  // If no history data (volatility = 0), use neutral 60
  const pvScore = powerScoreVolatility === 0 ? 60 : Math.max(0, Math.min(100, 100 - powerScoreVolatility * 400));

  // Weighted average
  const weightedScore = gdScore * 0.5 + sfScore * 0.3 + pvScore * 0.2;

  return Math.round(Math.min(100, Math.max(0, weightedScore)));
}

/**
 * Determine consistency label based on score
 */
function getConsistencyLabel(score: number): ConsistencyInsight['label'] {
  if (score >= 75) return 'very reliable';
  if (score >= 55) return 'moderately reliable';
  if (score >= 35) return 'unpredictable';
  return 'highly volatile';
}

/** Minimum scored games required for a meaningful consistency score */
const MIN_GAMES_FOR_CONSISTENCY = 3;

/**
 * Generate the Consistency Score insight
 */
export function generateConsistencyScore(data: InsightInputData): ConsistencyInsight {
  const { team, games, rankingHistory } = data;

  const recent = extractRecentPlayedResults(games, team.team_id_master);

  // With fewer than 3 scored games, default to a neutral "unpredictable"
  // instead of inflating the score from near-zero variance
  if (recent.length < MIN_GAMES_FOR_CONSISTENCY) {
    return {
      type: 'consistency_score',
      score: 50,
      label: 'unpredictable',
      details: {
        goalDifferentialStdDev: 0,
        streakFragmentation: 0,
        powerScoreVolatility: 0,
      },
    };
  }

  const goalDifferentialStdDev = calculateGoalDiffStdDev(recent);
  const streakFragmentation = calculateStreakFragmentation(recent);
  const powerScoreVolatility = calculatePowerScoreVolatility(rankingHistory);

  const score = calculateConsistencyScore(goalDifferentialStdDev, streakFragmentation, powerScoreVolatility);

  const label = getConsistencyLabel(score);

  return {
    type: 'consistency_score',
    score,
    label,
    details: {
      goalDifferentialStdDev: Math.round(goalDifferentialStdDev * 100) / 100,
      streakFragmentation: Math.round(streakFragmentation * 100) / 100,
      powerScoreVolatility: Math.round(powerScoreVolatility * 1000) / 1000,
    },
  };
}
