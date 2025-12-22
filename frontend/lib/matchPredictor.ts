/**
 * Match Prediction Engine v2.5
 *
 * Enhanced prediction model using multiple features with adaptive weighting:
 * - Power Score Differential (50-85% adaptive based on skill gap)
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
 * - Age-specific margin calibration for all age groups (U10-U18)
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
 * Validated at 74.7% direction accuracy (target: 77-79% with calibration)
 */

import type { TeamWithRanking } from './types';
import type { Game } from './types';
import { computeConfidence } from './confidenceEngine';
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
  bucket_accuracy?: Record<string, any>;
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
    try {
      const response = await fetch('/data/calibration/age_group_parameters.json');
      if (response.ok) {
        ageGroupParams = await response.json();
      } else {
        // Fallback to defaults if file not found
        ageGroupParams = {};
      }
    } catch (error) {
      // Fallback to defaults on error
      ageGroupParams = {};
    }
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
    try {
      const response = await fetch('/data/calibration/probability_parameters.json');
      if (response.ok) {
        probabilityParams = await response.json();
      } else {
        // File not found - will use defaults
        probabilityParams = null;
      }
    } catch (error) {
      // Fallback to defaults on error
      probabilityParams = null;
    }
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
    try {
      const response = await fetch('/data/calibration/margin_parameters_v2.json');
      if (response.ok) {
        marginParamsV2 = await response.json();
      } else {
        // File not found - will use defaults
        marginParamsV2 = null;
      }
    } catch (error) {
      // Fallback to defaults on error
      marginParamsV2 = null;
    }
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

// Base feature weights (optimized for close matchups - 74.7% accuracy)
const BASE_WEIGHTS = {
  POWER_SCORE: 0.50,  // Base strength
  SOS: 0.18,          // Schedule strength
  RECENT_FORM: 0.28,  // Last 5 games momentum - KEY PREDICTOR for close games!
  MATCHUP: 0.04,      // Offense vs defense
};

// Adaptive weights for large skill gaps (>0.08 power diff = 8 percentile points)
const BLOWOUT_WEIGHTS = {
  POWER_SCORE: 0.85,  // Power dominates in mismatches (increased from 0.75)
  SOS: 0.06,          // Schedule matters less
  RECENT_FORM: 0.07,  // Recent form matters less
  MATCHUP: 0.02,      // Matchup details matter less
};

// Thresholds for adaptive weighting (lowered in v2.1 for more responsive predictions)
// A 12 percentile point gap should NOT be treated as "close"
const SKILL_GAP_THRESHOLDS = {
  LARGE: 0.08,   // >8 percentile points = large gap, use blowout weights
  MEDIUM: 0.05,  // 5-8 percentile points = transition zone
};

// Prediction parameters (with calibration overrides)
const DEFAULT_SENSITIVITY = 4.5;
const MARGIN_COEFFICIENT = 8.0;
const RECENT_GAMES_COUNT = 5;

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

// Confidence thresholds
const CONFIDENCE_THRESHOLDS = {
  HIGH: 0.70,    // >70% probability = high confidence
  MEDIUM: 0.60,  // 60-70% = medium confidence
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
export function calculateRecentForm(
  teamId: string,
  allGames: Game[],
  n: number = RECENT_GAMES_COUNT
): number {
  // Get team's recent games
  const teamGames = allGames
    .filter(g => g.home_team_master_id === teamId || g.away_team_master_id === teamId)
    .sort((a, b) => new Date(b.game_date).getTime() - new Date(a.game_date).getTime())
    .slice(0, n);

  if (teamGames.length === 0) return 0;

  // Calculate average goal differential
  let totalGoalDiff = 0;
  let gamesWithScores = 0;

  for (const game of teamGames) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && oppScore !== null) {
      totalGoalDiff += (teamScore - oppScore);
      gamesWithScores++;
    }
  }

  if (gamesWithScores === 0) return 0;

  // Calculate average goal differential
  const avgGoalDiff = totalGoalDiff / gamesWithScores;

  // Weight by sample size to reduce noise from small samples
  // This prevents a team with 1 game from being treated as reliably as a team with 5 games
  const sampleSizeWeight = gamesWithScores / n;

  return avgGoalDiff * sampleSizeWeight;
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
  const h2hGames = allGames.filter(g =>
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
      totalGoalDiff += (teamAScore - teamBScore);
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
  const matchupAsymmetry = Math.abs((offenseA - defenseB) - (offenseB - defenseA));

  // Score each metric (0-1 scale)
  const powerScore = Math.min(absPowerDiff / 0.12, 1.0);        // 12% gap = max
  const offenseScore = Math.min(offenseGap / 0.18, 1.0);        // 18% gap = max
  const defenseScore = Math.min(defenseGap / 0.18, 1.0);        // 18% gap = max
  const asymmetryScore = Math.min(matchupAsymmetry / 0.30, 1.0); // 0.30 asymmetry = max

  // Weighted combination - offense/defense gaps are strong indicators
  const mismatchScore = (
    powerScore * 0.35 +
    offenseScore * 0.25 +
    defenseScore * 0.25 +
    asymmetryScore * 0.15
  );

  // Mismatch if score > 0.4 OR any single metric is extreme
  const isMismatch = mismatchScore > 0.4 ||
    absPowerDiff > 0.10 ||
    offenseGap > 0.15 ||
    defenseGap > 0.15 ||
    matchupAsymmetry > 0.25;

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
  const { isMismatch, mismatchScore } = detectMismatch(
    powerDiff, offenseA, offenseB, defenseA, defenseB
  );

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
    (absPowerDiff - SKILL_GAP_THRESHOLDS.MEDIUM) /
      (SKILL_GAP_THRESHOLDS.LARGE - SKILL_GAP_THRESHOLDS.MEDIUM),
    mismatchScore
  );

  const weights = {
    POWER_SCORE: BASE_WEIGHTS.POWER_SCORE +
      (BLOWOUT_WEIGHTS.POWER_SCORE - BASE_WEIGHTS.POWER_SCORE) * transitionProgress,
    SOS: BASE_WEIGHTS.SOS +
      (BLOWOUT_WEIGHTS.SOS - BASE_WEIGHTS.SOS) * transitionProgress,
    RECENT_FORM: BASE_WEIGHTS.RECENT_FORM +
      (BLOWOUT_WEIGHTS.RECENT_FORM - BASE_WEIGHTS.RECENT_FORM) * transitionProgress,
    MATCHUP: BASE_WEIGHTS.MATCHUP +
      (BLOWOUT_WEIGHTS.MATCHUP - BASE_WEIGHTS.MATCHUP) * transitionProgress,
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
  const calibrationPoints: [number, number][] = [
    [0.50, 0.50],   // 50% stays 50%
    [0.525, 0.465], // 50-55% bucket: predicted 52.4% → actual 46.5%
    [0.575, 0.587], // 55-60% bucket: predicted 57.4% → actual 58.7%
    [0.625, 0.739], // 60-65% bucket: predicted 62.3% → actual 73.9%
    [0.675, 0.669], // 65-70% bucket: close to calibrated
    [0.725, 0.650], // 70-75% bucket: predicted 73.2% → actual ~65% (adjusted from 37% outlier)
    [0.775, 0.700], // 75-80% bucket: predicted 77.7% → actual ~70%
    [0.850, 0.796], // 80-90% bucket: predicted 80.7% → actual 79.6%
    [1.00, 1.00],   // 100% stays 100%
  ];

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
  if (age <= 11) return 2.0;      // U10-U11
  if (age <= 14) return 2.5;      // U12-U14
  if (age <= 18) return 2.8;      // U15-U18
  return 3.0;                     // U19+
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
function getAgeSpecificMarginMultiplier(
  age: number | null,
  absPowerDiff: number,
  mismatchScore: number = 0
): number {
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
  let powerGapScaling = 1.0;
  if (absPowerDiff > 0.15) {
    // Very large gap (15+ percentile points) - significant mismatch
    powerGapScaling = 3.0;
  } else if (absPowerDiff > 0.10) {
    // Large gap (10-15 percentile points)
    const transitionProgress = (absPowerDiff - 0.10) / (0.15 - 0.10);
    powerGapScaling = 2.0 + (1.0 * transitionProgress);
  } else if (absPowerDiff > 0.05) {
    // Moderate gap (5-10 percentile points)
    const transitionProgress = (absPowerDiff - 0.05) / (0.10 - 0.05);
    powerGapScaling = 1.0 + (1.0 * transitionProgress);
  }

  // Apply global margin_scale from v2 calibration
  // But reduce dampening effect for mismatches (blowout games need larger margins)
  const baseMarginScale = marginParamsV2?.margin_scale ?? 1.0;

  // FIX: Use both powerDiff AND mismatchScore for dampening reduction
  // mismatchScore captures offense/defense gaps that powerDiff alone misses
  const powerBasedReduction = Math.min(absPowerDiff / 0.12, 1.0);  // Lowered from 0.15 to 0.12
  const mismatchBasedReduction = Math.min(mismatchScore / 0.7, 1.0);  // New: use mismatchScore
  const gapDampeningReduction = Math.max(powerBasedReduction, mismatchBasedReduction);

  // FIX: Allow FULL dampening removal for clear mismatches (was capped at 50%)
  // For mismatchScore > 0.7: marginScale approaches 1.0 (no dampening)
  // For close games (low mismatchScore): keep the dampening to avoid over-predicting
  const marginScale = baseMarginScale + (1.0 - baseMarginScale) * gapDampeningReduction;

  return baseMultiplier * powerGapScaling * marginScale;
}

/**
 * Match prediction result
 */
export interface MatchPrediction {
  // Prediction
  predictedWinner: 'team_a' | 'team_b' | 'draw';
  winProbabilityA: number;
  winProbabilityB: number;
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
    sosDiff: number;
    formDiffRaw: number;
    formDiffNorm: number;
    matchupAdvantage: number;
    compositeDiff: number;
    mismatchScore: number;
  };

  // Raw data for explanation generator
  formA: number;
  formB: number;

  // Head-to-head history (if available)
  h2h?: {
    gamesPlayed: number;
    avgMargin: number;  // Team A's average goal margin in H2H meetings
  };
}

/**
 * Predict match outcome with enhanced model using adaptive weights
 * v2.3: Multi-metric mismatch detection for better blowout prediction
 */
export function predictMatch(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  allGames: Game[]
): MatchPrediction {
  // 1. Base power score differential
  const powerDiff = (teamA.power_score_final || 0.5) - (teamB.power_score_final || 0.5);

  // 2. Offense vs Defense values (needed for mismatch detection)
  const offenseA = teamA.offense_norm || 0.5;
  const defenseA = teamA.defense_norm || 0.5;
  const offenseB = teamB.offense_norm || 0.5;
  const defenseB = teamB.defense_norm || 0.5;

  // 3. Calculate adaptive weights based on multi-metric mismatch detection
  const { weights, mismatchScore } = getAdaptiveWeights(
    powerDiff, offenseA, offenseB, defenseA, defenseB
  );

  // 4. SOS differential
  const sosDiff = (teamA.sos_norm || 0.5) - (teamB.sos_norm || 0.5);

  // 5. Recent form
  const formA = calculateRecentForm(teamA.team_id_master, allGames);
  const formB = calculateRecentForm(teamB.team_id_master, allGames);
  const formDiffRaw = formA - formB;
  const formDiffNorm = normalizeRecentForm(formDiffRaw) - 0.5;

  // 6. Matchup asymmetry (how much A's offense exploits B's defense)
  const matchupAdvantage = (offenseA - defenseB) - (offenseB - defenseA);

  // 7. Head-to-head history (HIGHLY predictive if available)
  const h2h = calculateHeadToHead(teamA.team_id_master, teamB.team_id_master, allGames);
  // H2H weight: increases with more historical meetings (max 0.15 for 3+ games)
  const h2hWeight = h2h.gamesPlayed > 0 ? Math.min(0.05 * h2h.gamesPlayed, 0.15) : 0;

  // 8. Composite differential (weighted combination with adaptive weights)
  // Reduce other weights proportionally when H2H data is available
  const h2hAdjustment = 1 - h2hWeight;
  let compositeDiff =
    weights.POWER_SCORE * powerDiff * h2hAdjustment +
    weights.SOS * sosDiff * h2hAdjustment +
    weights.RECENT_FORM * formDiffNorm * h2hAdjustment +
    weights.MATCHUP * matchupAdvantage * h2hAdjustment +
    h2hWeight * h2h.advantage * 10; // Scale H2H advantage to be comparable

  // 8. Mismatch amplification: boost composite diff for clear mismatches
  // This ensures large offense/defense gaps translate to higher probabilities
  // v2.5: Lowered threshold from 0.5 to 0.4 to catch more moderate mismatches
  if (mismatchScore > 0.4) {
    // Amplify by up to 1.8x for extreme mismatches (was 1.5x)
    const amplification = 1.0 + (mismatchScore - 0.4) * 1.33;
    compositeDiff *= amplification;
  }

  // 9. Win probability (using calibrated sensitivity + per-bucket calibration)
  const sensitivity = getSensitivity();
  const rawWinProbA = sigmoid(sensitivity * compositeDiff);
  const winProbA = calibrateProbability(rawWinProbA);
  const winProbB = 1 - winProbA;

  // 10. Expected goal margin with age-specific and mismatch-based amplification
  // Get age: prefer extracting from team name (handles "14B" = U12 format), fallback to database age
  const effectiveAge = extractAgeFromTeamName(teamA.team_name) ||
                       extractAgeFromTeamName(teamB.team_name) ||
                       teamA.age ||
                       teamB.age;
  // Use raw powerDiff for margin scaling - ensures large skill gaps produce larger margins
  const absPowerDiff = Math.abs(powerDiff);
  // v2.5: Pass mismatchScore to allow full dampening removal for blowouts
  const marginMultiplier = getAgeSpecificMarginMultiplier(effectiveAge, absPowerDiff, mismatchScore);
  // For mismatches, increase the margin to better reflect blowout potential
  // v2.5: Lowered threshold from 0.5 to 0.4, increased boost factor from 3.0 to 4.0
  // At mismatch=0.4: 1.0x, at mismatch=0.7: 2.2x, at mismatch=1.0: 3.4x
  const mismatchMarginBoost = mismatchScore > 0.4 ? 1.0 + (mismatchScore - 0.4) * 4.0 : 1.0;
  const expectedMargin = compositeDiff * MARGIN_COEFFICIENT * marginMultiplier * mismatchMarginBoost;

  // 11. Expected scores using age-adjusted league average
  const leagueAvgGoals = getLeagueAverageGoals(effectiveAge);
  const absExpectedMargin = Math.abs(expectedMargin);

  // For mismatches, use a different scoring model:
  // - Underdog scores 0-1 goals in blowouts
  // - Favorite scores underdog + margin
  let rawScoreA: number;
  let rawScoreB: number;

  if (mismatchScore > 0.5) {
    // Clear mismatch: underdog gets reduced score (0-1.5 range)
    // v2.5: Lowered threshold from 0.6 to 0.5 for consistency
    // At mismatch=0.5: underdog=1.5, at mismatch=0.8: underdog=0.75, at mismatch=1.0: underdog=0.25
    const underdogScore = Math.max(0, 1.5 - (mismatchScore - 0.5) * 2.5);
    if (expectedMargin >= 0) {
      rawScoreB = underdogScore;
      rawScoreA = underdogScore + absExpectedMargin;
    } else {
      rawScoreA = underdogScore;
      rawScoreB = underdogScore + absExpectedMargin;
    }
  } else {
    // Competitive match: both teams score around league average
    if (expectedMargin >= 0) {
      rawScoreB = leagueAvgGoals - (absExpectedMargin / 2);
      rawScoreA = leagueAvgGoals + (absExpectedMargin / 2);
    } else {
      rawScoreA = leagueAvgGoals - (absExpectedMargin / 2);
      rawScoreB = leagueAvgGoals + (absExpectedMargin / 2);
    }
  }

  const roundedMargin = Math.round(absExpectedMargin);

  // Round the underdog's score, then add the rounded margin for the favorite
  // This ensures the displayed margin matches the rounded expected margin
  let expectedScoreA: number;
  let expectedScoreB: number;

  if (roundedMargin === 0) {
    // Close match - show same score
    const avgScore = Math.round(leagueAvgGoals);
    expectedScoreA = avgScore;
    expectedScoreB = avgScore;
  } else if (expectedMargin >= 0) {
    // Team A is favored
    expectedScoreB = Math.max(0, Math.round(rawScoreB));
    expectedScoreA = Math.max(0, expectedScoreB + roundedMargin);
  } else {
    // Team B is favored
    expectedScoreA = Math.max(0, Math.round(rawScoreA));
    expectedScoreB = Math.max(0, expectedScoreA + roundedMargin);
  }

  // 10. Predicted winner (with draw threshold for close matchups)
  // ~16% of games end in draws - predict draw when probability is very close to 50%
  let predictedWinner: 'team_a' | 'team_b' | 'draw';
  if (Math.abs(winProbA - 0.5) < DRAW_THRESHOLD) {
    predictedWinner = 'draw';
  } else {
    predictedWinner = winProbA >= 0.5 ? 'team_a' : 'team_b';
  }

  // 11. Confidence level (using variance-based confidence engine)
  const confidenceResult = computeConfidence(teamA, teamB, compositeDiff, allGames);
  const confidence = confidenceResult.confidence;

  return {
    predictedWinner,
    winProbabilityA: winProbA,
    winProbabilityB: winProbB,
    expectedScore: {
      teamA: expectedScoreA,
      teamB: expectedScoreB,
    },
    expectedMargin,
    confidence,
    confidence_score: confidenceResult.confidence_score,
    components: {
      powerDiff,
      sosDiff,
      formDiffRaw,
      formDiffNorm,
      matchupAdvantage,
      compositeDiff,
      mismatchScore,
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
