/**
 * Match Prediction Engine
 *
 * Enhanced prediction model using multiple features with adaptive weighting:
 * - Power Score Differential (50-75% adaptive based on skill gap)
 * - SOS Differential (18-10% adaptive)
 * - Recent Form (28-12% adaptive)
 * - Matchup Asymmetry (4-3% adaptive)
 *
 * For large skill gaps (>15 percentile points), power score dominates.
 * For close matchups (<10 percentile points), recent form and SOS matter more.
 *
 * Validated at 74.7% direction accuracy
 */

import type { TeamWithRanking } from './types';
import type { Game } from './types';

// Base feature weights (optimized for close matchups - 74.7% accuracy)
const BASE_WEIGHTS = {
  POWER_SCORE: 0.50,  // Base strength
  SOS: 0.18,          // Schedule strength
  RECENT_FORM: 0.28,  // Last 5 games momentum - KEY PREDICTOR for close games!
  MATCHUP: 0.04,      // Offense vs defense
};

// Adaptive weights for large skill gaps (>0.15 power diff = 15 percentile points)
const BLOWOUT_WEIGHTS = {
  POWER_SCORE: 0.75,  // Power dominates in mismatches
  SOS: 0.10,          // Schedule matters less
  RECENT_FORM: 0.12,  // Recent form matters less
  MATCHUP: 0.03,      // Matchup details matter less
};

// Thresholds for adaptive weighting
const SKILL_GAP_THRESHOLDS = {
  LARGE: 0.15,   // >15 percentile points = large gap, use blowout weights
  MEDIUM: 0.10,  // 10-15 percentile points = transition zone
};

// Prediction parameters
const SENSITIVITY = 4.5;
const MARGIN_COEFFICIENT = 8.0;
const RECENT_GAMES_COUNT = 5;

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
 * Based on empirical data from youth soccer:
 * - U10-U11: ~2.0 goals/team
 * - U12-U14: ~2.5 goals/team
 * - U15-U18: ~2.8 goals/team
 * - U19+: ~3.0 goals/team
 */
function getLeagueAverageGoals(age: number | null): number {
  if (!age) return 2.5; // Default to middle range if age unknown

  if (age <= 11) return 2.0;      // U10-U11
  if (age <= 14) return 2.5;      // U12-U14
  if (age <= 18) return 2.8;      // U15-U18
  return 3.0;                     // U19+
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

  // Component breakdowns
  components: {
    powerDiff: number;
    sosDiff: number;
    formDiffRaw: number;
    formDiffNorm: number;
    matchupAdvantage: number;
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

  // 6. Composite differential (weighted combination with adaptive weights)
  const compositeDiff =
    weights.POWER_SCORE * powerDiff +
    weights.SOS * sosDiff +
    weights.RECENT_FORM * formDiffNorm +
    weights.MATCHUP * matchupAdvantage;

  // 7. Win probability
  const winProbA = sigmoid(SENSITIVITY * compositeDiff);
  const winProbB = 1 - winProbA;

  // 8. Expected goal margin with non-linear amplification for blowouts
  // For close games: use base coefficient
  // For blowouts: amplify margin to reflect larger skill gaps
  const absCompositeDiff = Math.abs(compositeDiff);
  let marginMultiplier = 1.0;

  if (absCompositeDiff > 0.12) {
    // Large gap (>0.12): amplify margin by 2.5x for realistic blowouts
    marginMultiplier = 2.5;
  } else if (absCompositeDiff > 0.08) {
    // Medium gap (0.08-0.12): interpolate from 1.0x to 2.5x
    const transitionProgress = (absCompositeDiff - 0.08) / (0.12 - 0.08);
    marginMultiplier = 1.0 + (1.5 * transitionProgress);
  }

  const expectedMargin = compositeDiff * MARGIN_COEFFICIENT * marginMultiplier;

  // 9. Expected scores using age-adjusted league average
  // Use teamA's age (matchups are typically same-age groups)
  const leagueAvgGoals = getLeagueAverageGoals(teamA.age);
  const expectedScoreA = Math.max(0, leagueAvgGoals + (expectedMargin / 2));
  const expectedScoreB = Math.max(0, leagueAvgGoals - (expectedMargin / 2));

  // 10. Predicted winner
  let predictedWinner: 'team_a' | 'team_b' | 'draw';
  if (winProbA > 0.55) predictedWinner = 'team_a';
  else if (winProbA < 0.45) predictedWinner = 'team_b';
  else predictedWinner = 'draw';

  // 11. Confidence level
  let confidence: 'high' | 'medium' | 'low';
  const probDiff = Math.abs(winProbA - 0.5);
  if (probDiff >= (CONFIDENCE_THRESHOLDS.HIGH - 0.5)) {
    confidence = 'high';
  } else if (probDiff >= (CONFIDENCE_THRESHOLDS.MEDIUM - 0.5)) {
    confidence = 'medium';
  } else {
    confidence = 'low';
  }

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
    components: {
      powerDiff,
      sosDiff,
      formDiffRaw,
      formDiffNorm,
      matchupAdvantage,
      compositeDiff,
    },
    formA,
    formB,
  };
}
