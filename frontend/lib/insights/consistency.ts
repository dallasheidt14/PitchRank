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

import type { InsightInputData, ConsistencyInsight } from "./types";

/**
 * v53e GOAL_DIFF_CAP constant - blowout games beyond ±6 goals
 * are capped to prevent single games from distorting metrics
 */
const GOAL_DIFF_CAP = 6;

/**
 * Calculate standard deviation of goal differentials
 * Caps goal differential at ±6 to match v53e engine
 */
function calculateGoalDiffStdDev(
  games: InsightInputData["games"],
  teamId: string
): number {
  const goalDiffs: number[] = [];

  for (const game of games) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && oppScore !== null) {
      // Cap goal differential to match v53e Layer 2
      const rawDiff = teamScore - oppScore;
      const cappedDiff = Math.max(-GOAL_DIFF_CAP, Math.min(GOAL_DIFF_CAP, rawDiff));
      goalDiffs.push(cappedDiff);
    }
  }

  if (goalDiffs.length < 2) return 0;

  const mean = goalDiffs.reduce((a, b) => a + b, 0) / goalDiffs.length;
  const variance =
    goalDiffs.reduce((sum, gd) => sum + Math.pow(gd - mean, 2), 0) /
    goalDiffs.length;

  return Math.sqrt(variance);
}

/**
 * Calculate streak fragmentation
 * Higher value = more fragmented (more result changes)
 * Returns value between 0 and 1
 */
function calculateStreakFragmentation(
  games: InsightInputData["games"],
  teamId: string
): number {
  const results: ("W" | "L" | "D")[] = [];

  for (const game of games) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && oppScore !== null) {
      if (teamScore > oppScore) results.push("W");
      else if (teamScore < oppScore) results.push("L");
      else results.push("D");
    }
  }

  if (results.length < 2) return 0;

  // Count transitions between different results
  let transitions = 0;
  for (let i = 1; i < results.length; i++) {
    if (results[i] !== results[i - 1]) {
      transitions++;
    }
  }

  // Normalize: max transitions = results.length - 1
  return transitions / (results.length - 1);
}

/**
 * Calculate PowerScore volatility from ranking history
 * Returns coefficient of variation (std dev / mean)
 */
function calculatePowerScoreVolatility(
  rankingHistory: InsightInputData["rankingHistory"]
): number {
  const scores = rankingHistory
    .map((h) => h.power_score_final)
    .filter((s): s is number => s !== null);

  if (scores.length < 2) return 0;

  const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
  if (mean === 0) return 0;

  const variance =
    scores.reduce((sum, s) => sum + Math.pow(s - mean, 2), 0) / scores.length;
  const stdDev = Math.sqrt(variance);

  // Return coefficient of variation (CV)
  return stdDev / mean;
}

/**
 * Convert raw metrics to a 0-100 consistency score
 * Higher score = more consistent
 *
 * Weights aligned with v53e philosophy:
 * - Goal differential variance: 50% (primary performance signal)
 * - Streak fragmentation: 30% (result predictability)
 * - Power score volatility: 20% (rank stability)
 */
function calculateConsistencyScore(
  goalDiffStdDev: number,
  streakFragmentation: number,
  powerScoreVolatility: number
): number {
  // Ideal values for a consistent team:
  // - Low goal differential std dev (< 1.5 is very consistent)
  //   With ±6 cap, max possible stdDev is ~6 (all games at extremes)
  //   Typical range: 1.0 - 3.5
  // - Low streak fragmentation (< 0.3 is consistent, long streaks)
  // - Low power score volatility (< 0.1 is stable)

  // Convert each metric to a 0-100 score (higher = more consistent)

  // Goal diff std dev: 0 -> 100, 4+ -> 0
  // Adjusted for capped goal diffs (max realistic stdDev ~4)
  const gdScore = Math.max(0, 100 - goalDiffStdDev * 25);

  // Streak fragmentation: 0 -> 100, 1 -> 0
  const sfScore = (1 - streakFragmentation) * 100;

  // Power score volatility: 0 -> 100, 0.2+ -> 0
  const pvScore = Math.max(0, 100 - powerScoreVolatility * 500);

  // Weighted average
  const weightedScore = gdScore * 0.5 + sfScore * 0.3 + pvScore * 0.2;

  return Math.round(Math.min(100, Math.max(0, weightedScore)));
}

/**
 * Determine consistency label based on score
 */
function getConsistencyLabel(
  score: number
): ConsistencyInsight["label"] {
  if (score >= 75) return "very reliable";
  if (score >= 55) return "moderately reliable";
  if (score >= 35) return "unpredictable";
  return "highly volatile";
}

/**
 * Generate the Consistency Score insight
 */
export function generateConsistencyScore(
  data: InsightInputData
): ConsistencyInsight {
  const { team, games, rankingHistory } = data;

  const goalDifferentialStdDev = calculateGoalDiffStdDev(games, team.team_id_master);
  const streakFragmentation = calculateStreakFragmentation(games, team.team_id_master);
  const powerScoreVolatility = calculatePowerScoreVolatility(rankingHistory);

  const score = calculateConsistencyScore(
    goalDifferentialStdDev,
    streakFragmentation,
    powerScoreVolatility
  );

  const label = getConsistencyLabel(score);

  return {
    type: "consistency_score",
    score,
    label,
    details: {
      goalDifferentialStdDev: Math.round(goalDifferentialStdDev * 100) / 100,
      streakFragmentation: Math.round(streakFragmentation * 100) / 100,
      powerScoreVolatility: Math.round(powerScoreVolatility * 1000) / 1000,
    },
  };
}
