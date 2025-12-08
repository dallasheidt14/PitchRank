/**
 * Match Prediction Engine
 *
 * Enhanced prediction model using multiple features with adaptive weighting:
 * - Power Score Differential (58-78% adaptive based on skill gap)
 * - SOS Differential (18-10% adaptive)
 * - Recent Form (20-8% adaptive, capped at 5% max contribution)
 * - Matchup Asymmetry (4% constant)
 * - Head-to-Head History (up to 3% boost based on past matchups)
 *
 * Key features:
 * - Opponent-adjusted recent form: Goals weighted by opponent strength
 * - Head-to-head history: Past matchups influence prediction (when 2+ games exist)
 * - Adaptive weights: Close games use different weights than mismatches
 * - Form cap: Prevents hot streaks from overriding large rank gaps
 *
 * Key changes (2025-12-08):
 * - Reduced form weight from 28% to 20% to prevent hot streaks flipping large rank gaps
 * - Lowered skill gap thresholds (MEDIUM: 0.10→0.05, LARGE: 0.15→0.10)
 * - Added MAX_FORM_CONTRIBUTION cap of 5% to prevent excessive form influence
 * - Increased power score weight from 50% to 58% for more reliable base predictions
 * - Added opponent-adjusted recent form (weights goals by opponent strength)
 * - Added head-to-head history boost (up to ±3% based on past matchups)
 * - CRITICAL FIX: Removed 45-55% "draw" zone - draws only occur ~16% of time,
 *   so always pick the favored team (this was causing 50-55% bucket to show 16% accuracy)
 *
 * For large skill gaps (>10 percentile points), power score dominates.
 * For close matchups (<5 percentile points), recent form and SOS matter more.
 */

import type { TeamWithRanking } from './types';
import type { Game } from './types';
import { computeConfidence } from './confidenceEngine';

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

// Base feature weights (rebalanced - reduced form influence to prevent upsets)
// Previous 28% form weight allowed hot streaks to flip large rank gaps
const BASE_WEIGHTS = {
  POWER_SCORE: 0.58,  // Increased from 0.50 - power score is more reliable
  SOS: 0.18,          // Schedule strength (unchanged)
  RECENT_FORM: 0.20,  // Reduced from 0.28 - prevents 5 games from overriding 30+ games
  MATCHUP: 0.04,      // Offense vs defense (unchanged)
};

// Adaptive weights for large skill gaps (>0.10 power diff = 10 percentile points)
const BLOWOUT_WEIGHTS = {
  POWER_SCORE: 0.78,  // Increased from 0.75 - power dominates in mismatches
  SOS: 0.10,          // Schedule matters less
  RECENT_FORM: 0.08,  // Reduced from 0.12 - form rarely matters in mismatches
  MATCHUP: 0.04,      // Matchup details
};

// Thresholds for adaptive weighting (lowered to trigger earlier)
// Previous thresholds treated 8-percentile gaps as "close games"
const SKILL_GAP_THRESHOLDS = {
  LARGE: 0.10,   // Lowered from 0.15 - 10 percentile points = large gap
  MEDIUM: 0.05,  // Lowered from 0.10 - start transitioning at 5 points
};

// Maximum contribution from recent form (prevents form from flipping large mismatches)
const MAX_FORM_CONTRIBUTION = 0.05;

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
 * and optionally adjusted by opponent strength.
 *
 * Sample size weighting prevents overconfidence from small samples:
 * - 1 game out of 5 needed = 20% weight
 * - 3 games out of 5 needed = 60% weight
 * - 5+ games out of 5 needed = 100% weight
 *
 * Opponent adjustment (when rankings provided):
 * - Beating a strong team (power > 0.6) = goal diff * 1.3
 * - Beating a weak team (power < 0.4) = goal diff * 0.7
 * - This makes +3 vs top-10 worth more than +3 vs bottom-100
 */
export function calculateRecentForm(
  teamId: string,
  allGames: Game[],
  n: number = RECENT_GAMES_COUNT,
  rankingsMap?: Map<string, number> // Optional: team_id -> power_score_final
): number {
  // Get team's recent games
  const teamGames = allGames
    .filter(g => g.home_team_master_id === teamId || g.away_team_master_id === teamId)
    .sort((a, b) => new Date(b.game_date).getTime() - new Date(a.game_date).getTime())
    .slice(0, n);

  if (teamGames.length === 0) return 0;

  // Calculate weighted goal differential
  let totalWeightedGoalDiff = 0;
  let totalWeight = 0;

  for (const game of teamGames) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;
    const oppId = isHome ? game.away_team_master_id : game.home_team_master_id;

    if (teamScore !== null && oppScore !== null) {
      const goalDiff = teamScore - oppScore;

      // Calculate opponent strength multiplier
      let oppMultiplier = 1.0;
      if (rankingsMap && oppId) {
        const oppPower = rankingsMap.get(oppId);
        if (oppPower !== undefined) {
          // Scale multiplier: strong opponent (0.7) = 1.4x, weak (0.3) = 0.6x
          // Formula: 0.6 + (oppPower * 1.0) => range 0.6 to 1.6
          oppMultiplier = 0.6 + (oppPower * 1.0);
        }
      }

      totalWeightedGoalDiff += goalDiff * oppMultiplier;
      totalWeight += oppMultiplier;
    }
  }

  if (totalWeight === 0) return 0;

  // Calculate weighted average goal differential
  const avgGoalDiff = totalWeightedGoalDiff / totalWeight;

  // Weight by sample size to reduce noise from small samples
  const gamesWithScores = teamGames.filter(g =>
    g.home_score !== null && g.away_score !== null
  ).length;
  const sampleSizeWeight = gamesWithScores / n;

  return avgGoalDiff * sampleSizeWeight;
}

/**
 * Calculate head-to-head record between two teams
 * Returns a boost/penalty based on historical matchups
 *
 * @returns number between -0.05 and +0.05 (capped to prevent over-reliance)
 */
export function calculateHeadToHeadBoost(
  teamAId: string,
  teamBId: string,
  allGames: Game[],
  minGames: number = 2 // Require at least 2 games for H2H to count
): number {
  // Find games between these two teams
  const h2hGames = allGames.filter(g =>
    (g.home_team_master_id === teamAId && g.away_team_master_id === teamBId) ||
    (g.home_team_master_id === teamBId && g.away_team_master_id === teamAId)
  );

  if (h2hGames.length < minGames) return 0;

  // Calculate Team A's win rate against Team B
  let teamAWins = 0;
  let teamBWins = 0;
  let gamesWithScores = 0;

  for (const game of h2hGames) {
    const aIsHome = game.home_team_master_id === teamAId;
    const aScore = aIsHome ? game.home_score : game.away_score;
    const bScore = aIsHome ? game.away_score : game.home_score;

    if (aScore !== null && bScore !== null) {
      if (aScore > bScore) teamAWins++;
      else if (bScore > aScore) teamBWins++;
      gamesWithScores++;
    }
  }

  if (gamesWithScores < minGames) return 0;

  // Calculate win rate differential
  const teamAWinRate = teamAWins / gamesWithScores;
  const expectedWinRate = 0.5;
  const winRateDiff = teamAWinRate - expectedWinRate;

  // Scale by number of games (more games = more confidence)
  // Max at 5 games to prevent over-reliance
  const gameConfidence = Math.min(gamesWithScores, 5) / 5;

  // Cap at +/- 0.03 composite differential boost
  const MAX_H2H_BOOST = 0.03;
  const rawBoost = winRateDiff * 0.1 * gameConfidence; // 0.1 scaling factor

  return Math.max(-MAX_H2H_BOOST, Math.min(MAX_H2H_BOOST, rawBoost));
}

/**
 * Normalize recent form to 0-1 scale using sigmoid
 */
function normalizeRecentForm(goalDiff: number): number {
  // Sigmoid normalization: goalDiff of +2 -> ~0.73, -2 -> ~0.27
  return 1 / (1 + Math.exp(-goalDiff * 0.5));
}

/**
 * Calculate adaptive weights based on power score differential
 * Large skill gaps → power score dominates
 * Close matchups → recent form and SOS matter more
 */
function getAdaptiveWeights(powerDiff: number): typeof BASE_WEIGHTS {
  const absPowerDiff = Math.abs(powerDiff);

  // Small gap (<10 percentile points): use base weights optimized for close games
  if (absPowerDiff < SKILL_GAP_THRESHOLDS.MEDIUM) {
    return BASE_WEIGHTS;
  }

  // Large gap (>15 percentile points): use blowout weights
  if (absPowerDiff >= SKILL_GAP_THRESHOLDS.LARGE) {
    return BLOWOUT_WEIGHTS;
  }

  // Transition zone (10-15 percentile points): interpolate between base and blowout
  const transitionProgress =
    (absPowerDiff - SKILL_GAP_THRESHOLDS.MEDIUM) /
    (SKILL_GAP_THRESHOLDS.LARGE - SKILL_GAP_THRESHOLDS.MEDIUM);

  return {
    POWER_SCORE: BASE_WEIGHTS.POWER_SCORE +
      (BLOWOUT_WEIGHTS.POWER_SCORE - BASE_WEIGHTS.POWER_SCORE) * transitionProgress,
    SOS: BASE_WEIGHTS.SOS +
      (BLOWOUT_WEIGHTS.SOS - BASE_WEIGHTS.SOS) * transitionProgress,
    RECENT_FORM: BASE_WEIGHTS.RECENT_FORM +
      (BLOWOUT_WEIGHTS.RECENT_FORM - BASE_WEIGHTS.RECENT_FORM) * transitionProgress,
    MATCHUP: BASE_WEIGHTS.MATCHUP +
      (BLOWOUT_WEIGHTS.MATCHUP - BASE_WEIGHTS.MATCHUP) * transitionProgress,
  };
}

/**
 * Sigmoid function for win probability
 */
function sigmoid(x: number): number {
  return 1 / (1 + Math.exp(-x));
}

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
 */
function getAgeSpecificMarginMultiplier(
  age: number | null,
  absCompositeDiff: number
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
  
  // Apply compositeDiff-based scaling on top of base multiplier
  let compositeScaling = 1.0;
  if (absCompositeDiff > 0.12) {
    compositeScaling = 2.5;
  } else if (absCompositeDiff > 0.08) {
    const transitionProgress = (absCompositeDiff - 0.08) / (0.12 - 0.08);
    compositeScaling = 1.0 + (1.5 * transitionProgress);
  }
  
  // Apply global margin_scale from v2 calibration if available
  const marginScale = marginParamsV2?.margin_scale ?? 1.0;
  
  return baseMultiplier * compositeScaling * marginScale;
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
    h2hBoost: number;
    compositeDiff: number;
  };

  // Raw data for explanation generator
  formA: number;
  formB: number;
}

/**
 * Predict match outcome with enhanced model using adaptive weights
 */
export function predictMatch(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  allGames: Game[]
): MatchPrediction {
  // 1. Base power score differential
  const powerDiff = (teamA.power_score_final || 0.5) - (teamB.power_score_final || 0.5);

  // 2. Calculate adaptive weights based on skill gap
  const weights = getAdaptiveWeights(powerDiff);

  // 3. SOS differential
  const sosDiff = (teamA.sos_norm || 0.5) - (teamB.sos_norm || 0.5);

  // 4. Recent form
  const formA = calculateRecentForm(teamA.team_id_master, allGames);
  const formB = calculateRecentForm(teamB.team_id_master, allGames);
  const formDiffRaw = formA - formB;
  const formDiffNorm = normalizeRecentForm(formDiffRaw) - 0.5;

  // 5. Offense vs Defense matchup asymmetry
  const offenseA = teamA.offense_norm || 0.5;
  const defenseA = teamA.defense_norm || 0.5;
  const offenseB = teamB.offense_norm || 0.5;
  const defenseB = teamB.defense_norm || 0.5;

  const matchupAdvantage = (offenseA - defenseB) - (offenseB - defenseA);

  // 5.5. Head-to-head history boost
  const h2hBoost = calculateHeadToHeadBoost(
    teamA.team_id_master,
    teamB.team_id_master,
    allGames
  );

  // 6. Composite differential (weighted combination with adaptive weights)
  // Cap form contribution to prevent hot streaks from flipping large mismatches
  const rawFormContribution = weights.RECENT_FORM * formDiffNorm;
  const cappedFormContribution = Math.max(
    -MAX_FORM_CONTRIBUTION,
    Math.min(MAX_FORM_CONTRIBUTION, rawFormContribution)
  );

  const compositeDiff =
    weights.POWER_SCORE * powerDiff +
    weights.SOS * sosDiff +
    cappedFormContribution +
    weights.MATCHUP * matchupAdvantage +
    h2hBoost; // Add head-to-head history boost

  // 7. Win probability (using calibrated sensitivity)
  const sensitivity = getSensitivity();
  const winProbA = sigmoid(sensitivity * compositeDiff);
  const winProbB = 1 - winProbA;

  // 8. Expected goal margin with age-specific and compositeDiff-based amplification
  const absCompositeDiff = Math.abs(compositeDiff);
  const marginMultiplier = getAgeSpecificMarginMultiplier(teamA.age, absCompositeDiff);
  const expectedMargin = compositeDiff * MARGIN_COEFFICIENT * marginMultiplier;

  // 9. Expected scores using age-adjusted league average
  // Use teamA's age (matchups are typically same-age groups)
  const leagueAvgGoals = getLeagueAverageGoals(teamA.age);
  const expectedScoreA = Math.max(0, leagueAvgGoals + (expectedMargin / 2));
  const expectedScoreB = Math.max(0, leagueAvgGoals - (expectedMargin / 2));

  // 10. Predicted winner - always pick the favored team
  // Previous logic used 45-55% as "draw" zone, but draws only happen ~16% of time
  // In the 50-55% bucket, actual team_a win rate was ~55-60%, not 50%
  // Predicting "draw" for those games caused terrible accuracy (16% vs expected 50%+)
  let predictedWinner: 'team_a' | 'team_b' | 'draw';
  predictedWinner = winProbA >= 0.5 ? 'team_a' : 'team_b';

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
      h2hBoost,
      compositeDiff,
    },
    formA,
    formB,
  };
}
