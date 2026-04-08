/**
 * Match Prediction Engine v3
 *
 * Enhanced prediction model using multiple features with adaptive weighting:
 * - Glicko rating edge when available (falls back to published score differential)
 * - SOS Differential (18-6% adaptive)
 * - Recent Form (28-7% adaptive)
 * - Matchup Asymmetry (4-2% adaptive)
 * - Head-to-Head History (0-15% based on sample size)
 *
 * For large skill gaps (>8 percentile points), power score dominates at 85%.
 * For close matchups (<5 percentile points), recent form and SOS matter more.
 *
 * v2.1 Improvements:
 * - Per-bucket probability calibration (fixes 50-55% and 60-65% bias)
 * - Draw threshold for close matchups (captures ~16% draw rate)
 * - Age-specific margin calibration for all age groups (U10-U19)
 *
 * v2.2 Improvements:
 * - Lowered skill gap thresholds: 8%/5% (was 15%/10%) - fixes "close match" misclassification
 * - Increased blowout power weight: 85% (was 75%) - power score now dominates for mismatches
 * - Fixed birth year age extraction: "14B" = 2014 birth year = U12 (turns 11 + 1), not U14
 *
 * v2.3 Improvements:
 * - Multi-metric mismatch detection: uses offense, defense, and matchup asymmetry gaps
 * - Teams with 15%+ offense/defense gaps now correctly identified as mismatches
 * - Mismatch amplification: boosts probability and margin for clear mismatches
 * - Fixes cases like Excel vs PRFC (7% power gap but 19% offense gap = mismatch, not close)
 *
 * v2.4 Improvements:
 * - Head-to-head history factor: incorporates past matchup results (highly predictive)
 * - Improved underdog score calculation: reduces inflated scores in blowouts
 * - Better score predictions: 5-1, 6-0 now possible instead of always 4-2, 3-2
 *
 * v2.5 Improvements (Blowout margin fix):
 * - Fixed blowout under-prediction (blowout MAE was 2x overall MAE)
 * - Dampening now uses mismatchScore, not just powerDiff - captures offense/defense gaps
 * - Removed 50% cap on dampening reduction - mismatches now get full margin
 * - Lowered mismatch thresholds: amplification at 0.4 (was 0.5), underdog score at 0.5 (was 0.6)
 * - Increased margin boost factor: 4.0 (was 3.0) for stronger blowout predictions
 *
 * Confidence is Glicko-aware when rating deviation is available.
 */

import type { TeamWithRanking } from './types';
import type { Game } from './types';
import { loadCalibrationJson } from './calibrationLoader';
import { computeConfidence, warmConfidenceCalibration } from './confidenceEngine';
import { extractAgeFromTeamName } from './utils';

// Age group parameters (loaded from JSON, fallback to defaults)
interface AgeGroupParameters {
  avg_goals: number;
  margin_mult: number;
  blowout_freq: number;
}

// Probability calibration parameters
interface ProbabilityParameters {
  sensitivity: number;
  calibration_error: number;
  bucket_accuracy?: Record<string, number>;
}

// Margin calibration v2 parameters
interface MarginParametersV2 {
  margin_scale: number;
  age_groups: Record<string, { margin_mult: number; mae: number }>;
  overall_mae: number;
}

let ageGroupParams: Record<string, AgeGroupParameters> | null = null;
let ageGroupParamsLoading: Promise<void> | null = null;
let probabilityParams: ProbabilityParameters | null = null;
let probabilityParamsLoading: Promise<void> | null = null;
let marginParamsV2: MarginParametersV2 | null = null;
let marginParamsV2Loading: Promise<void> | null = null;

interface RecentProfile {
  goalDiff: number;
  goalsFor: number;
  goalsAgainst: number;
  drawRate: number;
  totalGoals: number;
  mlTrend: number;
  volatility: number;
  sampleWeight: number;
}

/**
 * Load age group parameters from JSON file
 * Caches result after first load
 */
async function loadAgeGroupParameters(): Promise<Record<string, AgeGroupParameters>> {
  if (ageGroupParams) {
    return ageGroupParams;
  }

  if (ageGroupParamsLoading) {
    await ageGroupParamsLoading;
    return ageGroupParams!;
  }

  ageGroupParamsLoading = (async () => {
    ageGroupParams = (await loadCalibrationJson<Record<string, AgeGroupParameters>>('age_group_parameters.json')) ?? {};
  })();

  await ageGroupParamsLoading;
  return ageGroupParams!;
}

/**
 * Load probability calibration parameters from JSON file
 * Caches result after first load
 */
async function loadProbabilityParameters(): Promise<ProbabilityParameters | null> {
  if (probabilityParams) {
    return probabilityParams;
  }

  if (probabilityParamsLoading) {
    await probabilityParamsLoading;
    return probabilityParams;
  }

  probabilityParamsLoading = (async () => {
    probabilityParams = await loadCalibrationJson<ProbabilityParameters>('probability_parameters.json');
  })();

  await probabilityParamsLoading;
  return probabilityParams;
}

/**
 * Load margin calibration v2 parameters from JSON file
 * Caches result after first load
 */
async function loadMarginParametersV2(): Promise<MarginParametersV2 | null> {
  if (marginParamsV2) {
    return marginParamsV2;
  }

  if (marginParamsV2Loading) {
    await marginParamsV2Loading;
    return marginParamsV2;
  }

  marginParamsV2Loading = (async () => {
    marginParamsV2 = await loadCalibrationJson<MarginParametersV2>('margin_parameters_v2.json');
  })();

  await marginParamsV2Loading;
  return marginParamsV2;
}

// Load parameters on module load (non-blocking)
loadAgeGroupParameters().catch(() => {
  // Silently fail - will use defaults
});
loadProbabilityParameters().catch(() => {
  // Silently fail - will use defaults
});
loadMarginParametersV2().catch(() => {
  // Silently fail - will use defaults
});

export async function warmMatchPredictorCalibration(): Promise<void> {
  await Promise.all([
    loadAgeGroupParameters(),
    loadProbabilityParameters(),
    loadMarginParametersV2(),
    warmConfidenceCalibration(),
  ]);
}

// Base feature weights (optimized for close matchups - 74.7% accuracy)
const BASE_WEIGHTS = {
  POWER_SCORE: 0.5, // Base strength
  SOS: 0.18, // Schedule strength
  RECENT_FORM: 0.28, // Last 5 games momentum - KEY PREDICTOR for close games!
  MATCHUP: 0.04, // Offense vs defense
};

// Adaptive weights for large skill gaps (>0.08 power diff = 8 percentile points)
const BLOWOUT_WEIGHTS = {
  POWER_SCORE: 0.85, // Power dominates in mismatches (increased from 0.75)
  SOS: 0.06, // Schedule matters less
  RECENT_FORM: 0.07, // Recent form matters less
  MATCHUP: 0.02, // Matchup details matter less
};

// Thresholds for adaptive weighting (lowered in v2.1 for more responsive predictions)
// A 12 percentile point gap should NOT be treated as "close"
const SKILL_GAP_THRESHOLDS = {
  LARGE: 0.08, // >8 percentile points = large gap, use blowout weights
  MEDIUM: 0.05, // 5-8 percentile points = transition zone
};

// Prediction parameters (with calibration overrides)
const DEFAULT_SENSITIVITY = 4.5;
const RECENT_GAMES_COUNT = 5;
const GLICKO_ELO_DIVISOR = 400;
const POISSON_MAX_GOALS = 10;
const DEFAULT_DRAW_RATE = 0.13;

/**
 * Get calibrated SENSITIVITY value
 * Uses probability_parameters.json if available, otherwise defaults to 4.5
 */
function getSensitivity(): number {
  if (probabilityParams && probabilityParams.sensitivity) {
    return probabilityParams.sensitivity;
  }
  return DEFAULT_SENSITIVITY;
}

function calculateGlickoStrength(teamA: TeamWithRanking, teamB: TeamWithRanking) {
  if (teamA.glicko_rating == null || teamB.glicko_rating == null) {
    return null;
  }

  const ratingDiff = teamA.glicko_rating - teamB.glicko_rating;
  const winProbabilityA = 1 / (1 + Math.pow(10, -ratingDiff / GLICKO_ELO_DIVISOR));

  const rdA = teamA.glicko_rd ?? 350;
  const rdB = teamB.glicko_rd ?? 350;
  const normalizedRd = Math.min(1, Math.sqrt(rdA * rdA + rdB * rdB) / (Math.SQRT2 * 350));
  const reliability = 0.45 + 0.55 * (1 - normalizedRd);

  return {
    ratingDiff,
    winProbabilityA,
    reliability,
    signal: (winProbabilityA - 0.5) * reliability,
  };
}

// Confidence thresholds
const _CONFIDENCE_THRESHOLDS = {
  HIGH: 0.7, // >70% probability = high confidence
  MEDIUM: 0.6, // 60-70% = medium confidence
  // <60% = low confidence
};

/**
 * Calculate recent form from game history
 * Returns average goal differential in last N games, weighted by sample size
 *
 * Sample size weighting prevents overconfidence from small samples:
 * - 1 game out of 5 needed = 20% weight
 * - 3 games out of 5 needed = 60% weight
 * - 5+ games out of 5 needed = 100% weight
 */
export function calculateRecentForm(teamId: string, allGames: Game[], n: number = RECENT_GAMES_COUNT): number {
  return buildRecentProfile(teamId, allGames, n).goalDiff;
}

function buildRecentProfile(teamId: string, allGames: Game[], n: number = 8): RecentProfile {
  const teamGames = allGames
    .filter((g) => g.home_team_master_id === teamId || g.away_team_master_id === teamId)
    .sort((a, b) => new Date(b.game_date).getTime() - new Date(a.game_date).getTime())
    .slice(0, n);

  if (teamGames.length === 0) {
    return {
      goalDiff: 0,
      goalsFor: 0,
      goalsAgainst: 0,
      drawRate: DEFAULT_DRAW_RATE,
      totalGoals: 0,
      mlTrend: 0,
      volatility: 1,
      sampleWeight: 0,
    };
  }

  let weightedGoalsFor = 0;
  let weightedGoalsAgainst = 0;
  let weightedGoalDiff = 0;
  let weightedDraws = 0;
  let weightedMlTrend = 0;
  let weightedSquaredGoalDiff = 0;
  let totalWeight = 0;

  for (let index = 0; index < teamGames.length; index++) {
    const game = teamGames[index];
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore == null || oppScore == null) continue;

    const recencyWeight = Math.exp(-0.28 * index);
    const goalDiff = teamScore - oppScore;
    const drawIndicator = teamScore === oppScore ? 1 : 0;
    const mlOverperformance = (game.ml_overperformance ?? 0) * (isHome ? 1 : -1);

    weightedGoalsFor += teamScore * recencyWeight;
    weightedGoalsAgainst += oppScore * recencyWeight;
    weightedGoalDiff += goalDiff * recencyWeight;
    weightedDraws += drawIndicator * recencyWeight;
    weightedMlTrend += mlOverperformance * recencyWeight;
    weightedSquaredGoalDiff += goalDiff * goalDiff * recencyWeight;
    totalWeight += recencyWeight;
  }

  if (totalWeight <= 0) {
    return {
      goalDiff: 0,
      goalsFor: 0,
      goalsAgainst: 0,
      drawRate: DEFAULT_DRAW_RATE,
      totalGoals: 0,
      mlTrend: 0,
      volatility: 1,
      sampleWeight: 0,
    };
  }

  const goalsFor = weightedGoalsFor / totalWeight;
  const goalsAgainst = weightedGoalsAgainst / totalWeight;
  const goalDiff = weightedGoalDiff / totalWeight;
  const variance = Math.max(0, weightedSquaredGoalDiff / totalWeight - goalDiff * goalDiff);
  const sampleWeight = Math.min(1, teamGames.length / n);

  return {
    goalDiff: goalDiff * sampleWeight,
    goalsFor,
    goalsAgainst,
    drawRate: Math.max(0, Math.min(0.5, weightedDraws / totalWeight)),
    totalGoals: goalsFor + goalsAgainst,
    mlTrend: weightedMlTrend / totalWeight,
    volatility: Math.sqrt(variance + 1),
    sampleWeight,
  };
}

/**
 * Normalize recent form to 0-1 scale using sigmoid
 */
function normalizeRecentForm(goalDiff: number): number {
  // Sigmoid normalization: goalDiff of +2 -> ~0.73, -2 -> ~0.27
  return 1 / (1 + Math.exp(-goalDiff * 0.5));
}

/**
 * Calculate head-to-head history between two teams
 * Returns { advantage: number, gamesPlayed: number }
 * - advantage > 0 means team A has historical edge
 * - advantage < 0 means team B has historical edge
 * - gamesPlayed is number of H2H meetings found
 *
 * Head-to-head is HIGHLY predictive - a team that consistently beats
 * another has proven they match up well against that specific opponent.
 */
export function calculateHeadToHead(
  teamAId: string,
  teamBId: string,
  allGames: Game[]
): { advantage: number; gamesPlayed: number; avgMargin: number } {
  // Find all games between these two teams
  const h2hGames = allGames.filter(
    (g) =>
      (g.home_team_master_id === teamAId && g.away_team_master_id === teamBId) ||
      (g.home_team_master_id === teamBId && g.away_team_master_id === teamAId)
  );

  if (h2hGames.length === 0) {
    return { advantage: 0, gamesPlayed: 0, avgMargin: 0 };
  }

  // Calculate Team A's average goal differential in H2H meetings
  let totalGoalDiff = 0;
  let gamesWithScores = 0;

  for (const game of h2hGames) {
    const isTeamAHome = game.home_team_master_id === teamAId;
    const teamAScore = isTeamAHome ? game.home_score : game.away_score;
    const teamBScore = isTeamAHome ? game.away_score : game.home_score;

    if (teamAScore !== null && teamBScore !== null) {
      totalGoalDiff += teamAScore - teamBScore;
      gamesWithScores++;
    }
  }

  if (gamesWithScores === 0) {
    return { advantage: 0, gamesPlayed: 0, avgMargin: 0 };
  }

  const avgMargin = totalGoalDiff / gamesWithScores;

  // Convert to normalized advantage (scaled like other features)
  // Each goal of H2H advantage translates to ~0.05 advantage in normalized space
  // This is significant but not overwhelming - still leaves room for other factors
  const advantage = avgMargin * 0.04;

  return {
    advantage,
    gamesPlayed: gamesWithScores,
    avgMargin,
  };
}

/**
 * Detect if this is a mismatch based on multiple metrics
 * Returns a mismatch score from 0 (close game) to 1 (clear mismatch)
 *
 * A mismatch can be detected via:
 * - Power score gap (>6-8 percentile points)
 * - Offense gap (>12 percentile points)
 * - Defense gap (>12 percentile points)
 * - Matchup asymmetry (>0.20)
 */
function detectMismatch(
  powerDiff: number,
  offenseA: number,
  offenseB: number,
  defenseA: number,
  defenseB: number
): { isMismatch: boolean; mismatchScore: number } {
  const absPowerDiff = Math.abs(powerDiff);
  const offenseGap = Math.abs(offenseA - offenseB);
  const defenseGap = Math.abs(defenseA - defenseB);
  // Matchup asymmetry: how much does A's offense exploit B's defense vs reverse
  const matchupAsymmetry = Math.abs(offenseA - defenseB - (offenseB - defenseA));

  // Score each metric (0-1 scale)
  const powerScore = Math.min(absPowerDiff / 0.12, 1.0); // 12% gap = max
  const offenseScore = Math.min(offenseGap / 0.18, 1.0); // 18% gap = max
  const defenseScore = Math.min(defenseGap / 0.18, 1.0); // 18% gap = max
  const asymmetryScore = Math.min(matchupAsymmetry / 0.3, 1.0); // 0.30 asymmetry = max

  // Weighted combination - offense/defense gaps are strong indicators
  const mismatchScore = powerScore * 0.35 + offenseScore * 0.25 + defenseScore * 0.25 + asymmetryScore * 0.15;

  // Mismatch if score > 0.4 OR any single metric is extreme
  const isMismatch =
    mismatchScore > 0.4 || absPowerDiff > 0.1 || offenseGap > 0.15 || defenseGap > 0.15 || matchupAsymmetry > 0.25;

  return { isMismatch, mismatchScore };
}

/**
 * Calculate adaptive weights based on skill gap
 * Large skill gaps → power score dominates
 * Close matchups → recent form and SOS matter more
 *
 * v2.3: Now uses multi-metric mismatch detection, not just power score
 */
function getAdaptiveWeights(
  powerDiff: number,
  offenseA: number,
  offenseB: number,
  defenseA: number,
  defenseB: number
): { weights: typeof BASE_WEIGHTS; mismatchScore: number } {
  const { isMismatch, mismatchScore } = detectMismatch(powerDiff, offenseA, offenseB, defenseA, defenseB);

  const absPowerDiff = Math.abs(powerDiff);

  // Clear mismatch detected - use blowout weights
  if (isMismatch && mismatchScore > 0.6) {
    return { weights: BLOWOUT_WEIGHTS, mismatchScore };
  }

  // Large power gap alone also triggers blowout
  if (absPowerDiff >= SKILL_GAP_THRESHOLDS.LARGE) {
    return { weights: BLOWOUT_WEIGHTS, mismatchScore };
  }

  // Small gap and no mismatch signals: use base weights
  if (absPowerDiff < SKILL_GAP_THRESHOLDS.MEDIUM && !isMismatch) {
    return { weights: BASE_WEIGHTS, mismatchScore };
  }

  // Transition zone: interpolate based on mismatch score
  const transitionProgress = Math.max(
    (absPowerDiff - SKILL_GAP_THRESHOLDS.MEDIUM) / (SKILL_GAP_THRESHOLDS.LARGE - SKILL_GAP_THRESHOLDS.MEDIUM),
    mismatchScore
  );

  const weights = {
    POWER_SCORE:
      BASE_WEIGHTS.POWER_SCORE + (BLOWOUT_WEIGHTS.POWER_SCORE - BASE_WEIGHTS.POWER_SCORE) * transitionProgress,
    SOS: BASE_WEIGHTS.SOS + (BLOWOUT_WEIGHTS.SOS - BASE_WEIGHTS.SOS) * transitionProgress,
    RECENT_FORM:
      BASE_WEIGHTS.RECENT_FORM + (BLOWOUT_WEIGHTS.RECENT_FORM - BASE_WEIGHTS.RECENT_FORM) * transitionProgress,
    MATCHUP: BASE_WEIGHTS.MATCHUP + (BLOWOUT_WEIGHTS.MATCHUP - BASE_WEIGHTS.MATCHUP) * transitionProgress,
  };

  return { weights, mismatchScore };
}

/**
 * Sigmoid function for win probability
 */
function sigmoid(x: number): number {
  return 1 / (1 + Math.exp(-x));
}

/**
 * Per-bucket probability calibration based on empirical validation
 *
 * Adjusts raw sigmoid probabilities to match actual win rates observed
 * in historical data. Based on calibration_error from probability_parameters.json.
 *
 * This uses piecewise linear interpolation (isotonic-style calibration)
 * to correct systematic biases in each probability bucket.
 */
function calibrateProbability(rawProb: number): number {
  // Calibration points: [raw_prob, calibrated_prob]
  // Derived from bucket_accuracy in probability_parameters.json
  // Format: predicted_prob -> actual_win_rate
  // Raw calibration points from empirical data, enforced monotonic via PAV.
  // Original non-monotonic points: [0.525,0.465], [0.625,0.739], [0.675,0.669], [0.725,0.650]
  // PAV pools adjacent violators so calibrated values never decrease as raw increases.
  const calibrationPoints: [number, number][] = [
    [0.5, 0.5], // 50% stays 50%
    [0.525, 0.526], // PAV-adjusted: pooled with neighbors to enforce monotonicity
    [0.575, 0.587], // 55-60% bucket: close to calibrated
    [0.625, 0.686], // PAV-adjusted: pooled 0.739, 0.669, 0.650 → monotonic sequence
    [0.675, 0.686], // PAV-adjusted: same pool
    [0.725, 0.686], // PAV-adjusted: same pool
    [0.775, 0.7], // 75-80% bucket
    [0.85, 0.796], // 80-90% bucket
    [1.0, 1.0], // 100% stays 100%
  ];

  if (Math.abs(rawProb - 0.5) < 1e-9) {
    return 0.5;
  }

  // Handle edge cases
  if (rawProb <= 0.5) {
    // For probabilities below 50%, mirror the calibration
    const mirroredRaw = 1 - rawProb;
    const mirroredCalibrated = calibrateProbability(mirroredRaw);
    return 1 - mirroredCalibrated;
  }

  // Find the two calibration points to interpolate between
  let lowerPoint = calibrationPoints[0];
  let upperPoint = calibrationPoints[calibrationPoints.length - 1];

  for (let i = 0; i < calibrationPoints.length - 1; i++) {
    if (rawProb >= calibrationPoints[i][0] && rawProb < calibrationPoints[i + 1][0]) {
      lowerPoint = calibrationPoints[i];
      upperPoint = calibrationPoints[i + 1];
      break;
    }
  }

  // Linear interpolation between the two points
  const t = (rawProb - lowerPoint[0]) / (upperPoint[0] - lowerPoint[0]);
  const calibrated = lowerPoint[1] + t * (upperPoint[1] - lowerPoint[1]);

  // Clamp to valid probability range
  return Math.max(0.01, Math.min(0.99, calibrated));
}

// Draw threshold: if probability is within this range of 50%, predict draw
// ~16% of games end in draws, so this captures close matchups
const DRAW_THRESHOLD = 0.03; // |winProb - 0.5| < 3% → predict draw

/**
 * Get age-adjusted league average goals per team
 * Uses calibrated parameters from age_group_parameters.json if available,
 * otherwise falls back to empirical defaults
 */
function getLeagueAverageGoals(age: number | null): number {
  if (!age) return 2.5; // Default to middle range if age unknown

  // Try to use calibrated parameters
  const ageKey = `u${age}`;
  if (ageGroupParams && ageGroupParams[ageKey]?.avg_goals) {
    return ageGroupParams[ageKey].avg_goals;
  }

  // Fallback to empirical defaults
  if (age <= 11) return 2.0; // U10-U11
  if (age <= 14) return 2.5; // U12-U14
  if (age <= 18) return 2.8; // U15-U18
  return 3.0; // U19+
}

/**
 * Get age-specific margin multiplier
 * Uses calibrated parameters from margin_parameters_v2.json and age_group_parameters.json if available,
 * otherwise uses compositeDiff-based calculation
 *
 * v2.5: Fixed blowout under-prediction by:
 * - Using mismatchScore (not just powerDiff) for dampening reduction
 * - Allowing full dampening removal for clear mismatches (was capped at 50%)
 * - Blowout MAE was 2x overall MAE; this fix addresses that gap
 */
function getAgeSpecificMarginMultiplier(age: number | null, absPowerDiff: number, mismatchScore: number = 0): number {
  // Try to use margin calibration v2 parameters first
  const ageKey = age ? `u${age}` : null;
  let baseMultiplier = 1.0;

  if (ageKey && marginParamsV2 && marginParamsV2.age_groups[ageKey]?.margin_mult) {
    // Use refined margin_mult from v2 calibration
    baseMultiplier = marginParamsV2.age_groups[ageKey].margin_mult;
  } else if (ageKey && ageGroupParams && ageGroupParams[ageKey]?.margin_mult) {
    // Fallback to age_group_parameters.json
    baseMultiplier = ageGroupParams[ageKey].margin_mult;
  }

  // Apply power-gap-based scaling on top of base multiplier
  // Larger power gaps should produce larger margins
  // v2.5: Reduced max scaling from 3.0 to 2.0 to prevent stacking issues (28-1 predictions)
  let powerGapScaling = 1.0;
  if (absPowerDiff > 0.15) {
    // Very large gap (15+ percentile points) - significant mismatch
    powerGapScaling = 2.0; // Was 3.0
  } else if (absPowerDiff > 0.1) {
    // Large gap (10-15 percentile points)
    const transitionProgress = (absPowerDiff - 0.1) / (0.15 - 0.1);
    powerGapScaling = 1.5 + 0.5 * transitionProgress; // Was 2.0 + 1.0
  } else if (absPowerDiff > 0.05) {
    // Moderate gap (5-10 percentile points)
    const transitionProgress = (absPowerDiff - 0.05) / (0.1 - 0.05);
    powerGapScaling = 1.0 + 0.5 * transitionProgress; // Was 1.0 + 1.0
  }

  // Apply global margin_scale from v2 calibration
  // But reduce dampening effect for mismatches (blowout games need larger margins)
  const baseMarginScale = marginParamsV2?.margin_scale ?? 1.0;

  // FIX: Use both powerDiff AND mismatchScore for dampening reduction
  // mismatchScore captures offense/defense gaps that powerDiff alone misses
  const powerBasedReduction = Math.min(absPowerDiff / 0.12, 1.0); // Lowered from 0.15 to 0.12
  const mismatchBasedReduction = Math.min(mismatchScore / 0.7, 1.0); // New: use mismatchScore
  const gapDampeningReduction = Math.max(powerBasedReduction, mismatchBasedReduction);

  // FIX: Allow FULL dampening removal for clear mismatches (was capped at 50%)
  // For mismatchScore > 0.7: marginScale approaches 1.0 (no dampening)
  // For close games (low mismatchScore): keep the dampening to avoid over-predicting
  const marginScale = baseMarginScale + (1.0 - baseMarginScale) * gapDampeningReduction;

  return baseMultiplier * powerGapScaling * marginScale;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function deriveWinRate(team: TeamWithRanking): number {
  if (team.win_percentage != null) {
    return clamp(team.win_percentage / 100, 0, 1);
  }

  const gamesPlayed = Math.max(0, team.games_played || 0);
  if (gamesPlayed === 0) return 0.5;

  return clamp(((team.wins || 0) + (team.draws || 0) * 0.5) / gamesPlayed, 0, 1);
}

function hasPredictionEvidence(team: TeamWithRanking): boolean {
  return (
    team.same_age_games != null ||
    team.same_age_game_share != null ||
    team.same_age_unique_opponents != null ||
    team.same_age_top100_opp_count != null ||
    team.same_age_top500_opp_count != null ||
    team.same_age_avg_opp_power_adj != null ||
    team.repeat_opponent_share != null ||
    team.positive_ml_evidence_scale != null ||
    team.publication_cap_rank != null ||
    team.publication_cap_score != null
  );
}

function computeEvidenceReliability(team: TeamWithRanking): number {
  if (!hasPredictionEvidence(team)) {
    return 1;
  }

  let reliability = 1;
  const sameAgeGames = Math.max(0, team.same_age_games ?? 0);
  const sameAgeShare = clamp(team.same_age_game_share ?? 0, 0, 1);
  const sameAgeOpponents = Math.max(0, team.same_age_unique_opponents ?? 0);
  const top100Opponents = Math.max(0, team.same_age_top100_opp_count ?? 0);
  const top500Opponents = Math.max(0, team.same_age_top500_opp_count ?? 0);
  const avgOppPower = team.same_age_avg_opp_power_adj;
  const repeatShare = clamp(team.repeat_opponent_share ?? 0, 0, 1);
  const mlEvidenceScale = clamp(team.positive_ml_evidence_scale ?? 1, 0, 1.1);

  reliability += Math.min(sameAgeGames / 8, 1) * 0.03;
  reliability += sameAgeShare * 0.06;
  reliability += Math.min(sameAgeOpponents / 6, 1) * 0.05;
  reliability += Math.min(top100Opponents / 3, 1) * 0.06;
  reliability += Math.min(top500Opponents / 6, 1) * 0.04;
  if (avgOppPower != null) {
    reliability += clamp(avgOppPower - 0.5, -0.06, 0.06);
  }
  reliability -= repeatShare * 0.12;
  reliability *= clamp(0.82 + mlEvidenceScale * 0.18, 0.82, 1.02);

  if (team.power_score_final != null && team.publication_cap_score != null) {
    reliability -= clamp((team.power_score_final - team.publication_cap_score) * 1.2, 0, 0.1);
  }

  if (team.publication_cap_rank != null) {
    reliability -= team.publication_cap_rank <= 100 ? 0.06 : team.publication_cap_rank <= 200 ? 0.04 : 0.02;
  }

  return clamp(reliability, 0.72, 1.08);
}

function shrinkToNeutral(value: number, reliability: number): number {
  return 0.5 + (value - 0.5) * reliability;
}

function shrinkTowardZero(value: number, reliability: number): number {
  return value * reliability;
}

function blendOptional(left: number | null | undefined, right: number | null | undefined): number | null {
  if (left == null && right == null) return null;
  if (left == null) return right ?? null;
  if (right == null) return left;

  return Math.sqrt(Math.max(0.15, left) * Math.max(0.15, right));
}

function poissonMass(lambda: number, maxGoals: number = POISSON_MAX_GOALS): number[] {
  const safeLambda = Math.max(0.05, lambda);
  const probabilities = new Array(maxGoals + 1).fill(0);
  probabilities[0] = Math.exp(-safeLambda);

  for (let goals = 1; goals <= maxGoals; goals++) {
    probabilities[goals] = (probabilities[goals - 1] * safeLambda) / goals;
  }

  const probabilitySum = probabilities.reduce((sum, value) => sum + value, 0);
  probabilities[maxGoals] += Math.max(0, 1 - probabilitySum);
  return probabilities;
}

function buildOutcomeDistribution(lambdaA: number, lambdaB: number) {
  const probsA = poissonMass(lambdaA);
  const probsB = poissonMass(lambdaB);

  let winA = 0;
  let draw = 0;
  let winB = 0;
  let bestWinA = { teamA: 1, teamB: 0, probability: 0 };
  let bestDraw = { teamA: 1, teamB: 1, probability: 0 };
  let bestWinB = { teamA: 0, teamB: 1, probability: 0 };

  for (let scoreA = 0; scoreA <= POISSON_MAX_GOALS; scoreA++) {
    for (let scoreB = 0; scoreB <= POISSON_MAX_GOALS; scoreB++) {
      const probability = probsA[scoreA] * probsB[scoreB];

      if (scoreA > scoreB) {
        winA += probability;
        if (probability > bestWinA.probability) bestWinA = { teamA: scoreA, teamB: scoreB, probability };
      } else if (scoreA < scoreB) {
        winB += probability;
        if (probability > bestWinB.probability) bestWinB = { teamA: scoreA, teamB: scoreB, probability };
      } else {
        draw += probability;
        if (probability > bestDraw.probability) bestDraw = { teamA: scoreA, teamB: scoreB, probability };
      }
    }
  }

  const total = winA + draw + winB;
  return {
    winA: total > 0 ? winA / total : 0.5,
    draw: total > 0 ? draw / total : DEFAULT_DRAW_RATE,
    winB: total > 0 ? winB / total : 0.5,
    bestWinA,
    bestDraw,
    bestWinB,
  };
}

function normalizedEntropy(probabilities: number[]): number {
  const safe = probabilities.filter((value) => value > 0);
  if (safe.length === 0) return 1;

  const entropy = -safe.reduce((sum, probability) => sum + probability * Math.log(probability), 0);
  return entropy / Math.log(probabilities.length);
}

/**
 * Match prediction result
 */
export interface MatchPrediction {
  // Prediction
  predictedWinner: 'team_a' | 'team_b' | 'draw';
  winProbabilityA: number;
  winProbabilityB: number;
  drawProbability?: number;
  expectedScore: {
    teamA: number;
    teamB: number;
  };
  expectedMargin: number;
  confidence: 'high' | 'medium' | 'low';
  confidence_score?: number; // Optional: include confidence score for debugging

  // Component breakdowns
  components: {
    powerDiff: number;
    strengthSignal: number;
    sosDiff: number;
    formDiffRaw: number;
    formDiffNorm: number;
    matchupAdvantage: number;
    compositeDiff: number;
    mismatchScore: number;
    evidenceSignal?: number;
    evidenceReliabilityA?: number;
    evidenceReliabilityB?: number;
    glickoRatingDiff?: number;
    glickoWinProbabilityA?: number;
    glickoReliability?: number;
  };

  // Raw data for explanation generator
  formA: number;
  formB: number;

  // Head-to-head history (if available)
  h2h?: {
    gamesPlayed: number;
    avgMargin: number; // Team A's average goal margin in H2H meetings
  };
}

/**
 * Predict match outcome with enhanced model using adaptive weights
 * v2.3: Multi-metric mismatch detection for better blowout prediction
 */
export function predictMatch(teamA: TeamWithRanking, teamB: TeamWithRanking, allGames: Game[]): MatchPrediction {
  const evidenceReliabilityA = computeEvidenceReliability(teamA);
  const evidenceReliabilityB = computeEvidenceReliability(teamB);
  const powerDiff =
    shrinkToNeutral(teamA.power_score_final || 0.5, evidenceReliabilityA) -
    shrinkToNeutral(teamB.power_score_final || 0.5, evidenceReliabilityB);
  const glickoStrength = calculateGlickoStrength(teamA, teamB);
  const offenseA = teamA.offense_norm || 0.5;
  const defenseA = teamA.defense_norm || 0.5;
  const offenseB = teamB.offense_norm || 0.5;
  const defenseB = teamB.defense_norm || 0.5;
  const { weights, mismatchScore } = getAdaptiveWeights(powerDiff, offenseA, offenseB, defenseA, defenseB);
  const sosDiff = (teamA.sos_norm || 0.5) - (teamB.sos_norm || 0.5);
  const recentA = buildRecentProfile(teamA.team_id_master, allGames);
  const recentB = buildRecentProfile(teamB.team_id_master, allGames);
  const formA = recentA.goalDiff;
  const formB = recentB.goalDiff;
  const formDiffRaw = formA - formB;
  const formDiffNorm = normalizeRecentForm(formDiffRaw) - 0.5;
  const matchupAdvantage = offenseA - defenseB - (offenseB - defenseA);
  const h2h = calculateHeadToHead(teamA.team_id_master, teamB.team_id_master, allGames);
  const h2hWeight = h2h.gamesPlayed > 0 ? Math.min(0.05 * h2h.gamesPlayed, 0.15) : 0;

  const predictiveWinSignal =
    (shrinkToNeutral(teamA.exp_win_rate ?? 0.5, evidenceReliabilityA) -
      shrinkToNeutral(teamB.exp_win_rate ?? 0.5, evidenceReliabilityB)) *
    0.9;
  const predictiveMarginSignal = clamp(
    (shrinkTowardZero(teamA.exp_margin ?? 0, evidenceReliabilityA) -
      shrinkTowardZero(teamB.exp_margin ?? 0, evidenceReliabilityB)) /
      6,
    -0.35,
    0.35
  );
  const predictiveSignal = predictiveWinSignal + predictiveMarginSignal;
  const minGamesPlayed = Math.min(teamA.games_played || 0, teamB.games_played || 0);
  const recordDiff = (deriveWinRate(teamA) - deriveWinRate(teamB)) * Math.min(1, minGamesPlayed / 18);
  const residualSignal = clamp((recentA.mlTrend - recentB.mlTrend) / 3.5, -0.2, 0.2);
  const evidenceSignal = clamp(evidenceReliabilityA - evidenceReliabilityB, -0.2, 0.2);
  const h2hSignal = h2hWeight > 0 ? h2h.advantage * (1 + h2hWeight) : 0;
  const strengthSignal = glickoStrength
    ? glickoStrength.signal * 0.55 + powerDiff * 0.25 + predictiveSignal * 0.2
    : powerDiff * 0.5 + predictiveSignal * 0.25 + recordDiff * 0.25;

  let compositeDiff =
    weights.POWER_SCORE * strengthSignal +
    weights.SOS * sosDiff +
    weights.RECENT_FORM * formDiffNorm +
    weights.MATCHUP * matchupAdvantage +
    recordDiff * 0.08 +
    residualSignal * 0.06 +
    evidenceSignal * 0.07 +
    h2hSignal * 0.08;

  if (mismatchScore > 0.4) {
    const amplification = 1.0 + (mismatchScore - 0.4) * 0.9;
    compositeDiff *= amplification;
  }

  const effectiveAge =
    extractAgeFromTeamName(teamA.team_name) || extractAgeFromTeamName(teamB.team_name) || teamA.age || teamB.age;
  const leagueAvgGoals = getLeagueAverageGoals(effectiveAge);
  const baseTotalGoals = leagueAvgGoals * 2;
  const predictiveGoalsA = blendOptional(
    teamA.exp_goals_for != null ? shrinkTowardZero(teamA.exp_goals_for, evidenceReliabilityA) : null,
    teamB.exp_goals_against != null ? shrinkTowardZero(teamB.exp_goals_against, evidenceReliabilityB) : null
  );
  const predictiveGoalsB = blendOptional(
    teamB.exp_goals_for != null ? shrinkTowardZero(teamB.exp_goals_for, evidenceReliabilityB) : null,
    teamA.exp_goals_against != null ? shrinkTowardZero(teamA.exp_goals_against, evidenceReliabilityA) : null
  );
  const predictiveTotalGoals =
    predictiveGoalsA != null || predictiveGoalsB != null
      ? (predictiveGoalsA ?? leagueAvgGoals) + (predictiveGoalsB ?? leagueAvgGoals)
      : null;
  const combinedRecentWeight = recentA.sampleWeight + recentB.sampleWeight;
  const recentTotalGoals =
    combinedRecentWeight > 0
      ? (recentA.totalGoals * recentA.sampleWeight + recentB.totalGoals * recentB.sampleWeight) / combinedRecentWeight
      : null;
  const styleTotalFactor = clamp(
    0.95 +
      (offenseA + offenseB - 1) * 0.2 +
      (1 - defenseA + (1 - defenseB) - 1) * 0.16 +
      (Math.abs(recentA.mlTrend) + Math.abs(recentB.mlTrend)) * 0.03,
    0.72,
    1.35
  );

  let totalGoals = baseTotalGoals * styleTotalFactor;
  if (predictiveTotalGoals != null) {
    totalGoals = totalGoals * 0.68 + predictiveTotalGoals * 0.32;
  }
  if (recentTotalGoals != null && recentTotalGoals > 0) {
    totalGoals = totalGoals * 0.82 + recentTotalGoals * 0.18;
  }
  totalGoals = clamp(totalGoals, 1.4, 8.8);

  const predictiveShareBias =
    predictiveGoalsA != null && predictiveGoalsB != null
      ? clamp((predictiveGoalsA - predictiveGoalsB) / Math.max(1, predictiveGoalsA + predictiveGoalsB), -0.2, 0.2)
      : 0;
  const shareSignal = clamp(compositeDiff + predictiveShareBias * 0.45 + residualSignal * 0.15, -0.9, 0.9);
  const shareA = sigmoid(getSensitivity() * shareSignal);
  let lambdaA = totalGoals * shareA;
  let lambdaB = totalGoals * (1 - shareA);

  if (predictiveGoalsA != null) {
    lambdaA = lambdaA * 0.75 + predictiveGoalsA * 0.25;
  }
  if (predictiveGoalsB != null) {
    lambdaB = lambdaB * 0.75 + predictiveGoalsB * 0.25;
  }

  const absPowerDiff = Math.abs(powerDiff);
  const marginMultiplier = getAgeSpecificMarginMultiplier(effectiveAge, absPowerDiff, mismatchScore);
  const desiredMargin = (lambdaA - lambdaB) * clamp(marginMultiplier / 1.25, 0.85, 1.25);
  lambdaA = clamp((totalGoals + desiredMargin) / 2, 0.15, 7.5);
  lambdaB = clamp(totalGoals - lambdaA, 0.15, 7.5);

  const distribution = buildOutcomeDistribution(lambdaA, lambdaB);
  const decisiveMass = distribution.winA + distribution.winB;
  let winProbA = distribution.winA;
  let winProbB = distribution.winB;
  const drawProbability = distribution.draw;

  if (decisiveMass > 0) {
    const calibratedDecisiveWinA = calibrateProbability(distribution.winA / decisiveMass);
    winProbA = calibratedDecisiveWinA * decisiveMass;
    winProbB = (1 - calibratedDecisiveWinA) * decisiveMass;
  }

  let normalizedDrawProbability = drawProbability;
  const probabilityTotal = winProbA + normalizedDrawProbability + winProbB;
  if (probabilityTotal > 0) {
    winProbA /= probabilityTotal;
    normalizedDrawProbability /= probabilityTotal;
    winProbB /= probabilityTotal;
  }

  const closeDecisiveEdge = Math.abs(winProbA - winProbB) < 0.06;
  const sparseMatchup = Math.min(recentA.sampleWeight, recentB.sampleWeight) < 0.4 || minGamesPlayed < 4;
  if (closeDecisiveEdge && sparseMatchup) {
    const drawBoost = Math.min(0.05, 0.24 - normalizedDrawProbability);
    if (drawBoost > 0) {
      const decisiveScale = (1 - (normalizedDrawProbability + drawBoost)) / Math.max(0.0001, winProbA + winProbB);
      normalizedDrawProbability += drawBoost;
      winProbA *= decisiveScale;
      winProbB *= decisiveScale;
    }
  }

  const predictedWinner: 'team_a' | 'team_b' | 'draw' =
    (normalizedDrawProbability + DRAW_THRESHOLD >= Math.max(winProbA, winProbB) &&
      Math.abs(winProbA - winProbB) < 0.12) ||
    (closeDecisiveEdge && sparseMatchup && normalizedDrawProbability >= DEFAULT_DRAW_RATE * 0.9)
      ? 'draw'
      : winProbA >= winProbB
        ? 'team_a'
        : 'team_b';

  const expectedScore =
    predictedWinner === 'draw'
      ? distribution.bestDraw
      : predictedWinner === 'team_a'
        ? distribution.bestWinA
        : distribution.bestWinB;

  const expectedMargin = lambdaA - lambdaB;

  const baseConfidence = computeConfidence(teamA, teamB, compositeDiff, allGames);
  const outcomeEntropy = normalizedEntropy([winProbA, normalizedDrawProbability, winProbB]);
  const maxOutcomeProbability = Math.max(winProbA, normalizedDrawProbability, winProbB);
  let confidenceScore = clamp(
    (baseConfidence.confidence_score ?? 0.5) * 0.6 + maxOutcomeProbability * 0.25 + (1 - outcomeEntropy) * 0.15,
    0.05,
    0.98
  );

  if (normalizedDrawProbability > 0.22) {
    confidenceScore = clamp(confidenceScore - 0.05, 0.05, 0.98);
  }
  if (Math.min(recentA.sampleWeight, recentB.sampleWeight) < 0.4) {
    confidenceScore = clamp(confidenceScore - 0.04, 0.05, 0.98);
  }
  if (Math.min(evidenceReliabilityA, evidenceReliabilityB) < 0.9) {
    confidenceScore = clamp(
      confidenceScore - (0.9 - Math.min(evidenceReliabilityA, evidenceReliabilityB)) * 0.16,
      0.05,
      0.98
    );
  }

  const confidence: 'high' | 'medium' | 'low' =
    confidenceScore >= 0.66 ? 'high' : confidenceScore >= 0.53 ? 'medium' : 'low';

  return {
    predictedWinner,
    winProbabilityA: winProbA,
    winProbabilityB: winProbB,
    drawProbability: normalizedDrawProbability,
    expectedScore: {
      teamA: expectedScore.teamA,
      teamB: expectedScore.teamB,
    },
    expectedMargin,
    confidence,
    confidence_score: confidenceScore,
    components: {
      powerDiff,
      strengthSignal,
      sosDiff,
      formDiffRaw,
      formDiffNorm,
      matchupAdvantage,
      compositeDiff,
      mismatchScore,
      evidenceSignal,
      evidenceReliabilityA,
      evidenceReliabilityB,
      ...(glickoStrength
        ? {
            glickoRatingDiff: glickoStrength.ratingDiff,
            glickoWinProbabilityA: glickoStrength.winProbabilityA,
            glickoReliability: glickoStrength.reliability,
          }
        : {}),
    },
    formA,
    formB,
    // Include H2H if we have historical data
    ...(h2h.gamesPlayed > 0 && {
      h2h: {
        gamesPlayed: h2h.gamesPlayed,
        avgMargin: h2h.avgMargin,
      },
    }),
  };
}
