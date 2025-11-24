/**
 * Variance-Based Confidence Engine
 *
 * Computes prediction confidence based on:
 * - Composite differential magnitude (larger gap = higher confidence)
 * - Combined variance of both teams (higher variance = lower confidence)
 * - Sample size strength (more games = higher confidence)
 *
 * V1 Formula (simple, no SOS double-counting):
 * confidence_score = sigmoid(
 *   1.6 * |compositeDiff| -
 *   1.0 * combined_variance +
 *   0.6 * sample_strength
 * )
 *
 * V2: Uses fitted weights from logistic regression calibration
 */

import type { TeamWithRanking } from './types';
import type { Game } from './types';

// Confidence calibration v2 parameters
interface ConfidenceParametersV2 {
  weights: {
    composite_diff: number;
    variance: number;
    sample_strength: number;
  };
  intercept?: number;
  thresholds: {
    high: number;
    medium: number;
  };
  accuracy_improvement?: number;
}

let confidenceParamsV2: ConfidenceParametersV2 | null = null;
let confidenceParamsV2Loading: Promise<void> | null = null;

/**
 * Load confidence calibration v2 parameters from JSON file
 * Caches result after first load
 */
async function loadConfidenceParametersV2(): Promise<ConfidenceParametersV2 | null> {
  if (confidenceParamsV2) {
    return confidenceParamsV2;
  }

  if (confidenceParamsV2Loading) {
    await confidenceParamsV2Loading;
    return confidenceParamsV2;
  }

  confidenceParamsV2Loading = (async () => {
    try {
      const response = await fetch('/data/calibration/confidence_parameters_v2.json');
      if (response.ok) {
        confidenceParamsV2 = await response.json();
      } else {
        // File not found - will use defaults
        confidenceParamsV2 = null;
      }
    } catch (error) {
      // Fallback to defaults on error
      confidenceParamsV2 = null;
    }
  })();

  await confidenceParamsV2Loading;
  return confidenceParamsV2;
}

// Load parameters on module load (non-blocking)
loadConfidenceParametersV2().catch(() => {
  // Silently fail - will use defaults
});

/**
 * Calculate variance of goals for a team from game history
 */
function calculateTeamVariance(teamId: string, allGames: Game[]): number {
  // Filter games for this team
  const teamGames = allGames.filter(
    (g) => g.home_team_master_id === teamId || g.away_team_master_id === teamId
  );

  if (teamGames.length < 2) {
    // Not enough data for variance calculation
    return 1.0; // Default to high variance (low confidence)
  }

  // Collect goals_for and goals_against
  const goalsFor: number[] = [];
  const goalsAgainst: number[] = [];

  for (const game of teamGames) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && oppScore !== null) {
      goalsFor.push(teamScore);
      goalsAgainst.push(oppScore);
    }
  }

  if (goalsFor.length < 2 || goalsAgainst.length < 2) {
    return 1.0; // Not enough data
  }

  // Calculate variance
  const varianceFor = calculateVariance(goalsFor);
  const varianceAgainst = calculateVariance(goalsAgainst);

  // Combined variance (sum of both)
  return varianceFor + varianceAgainst;
}

/**
 * Calculate variance of an array of numbers
 */
function calculateVariance(values: number[]): number {
  if (values.length < 2) return 0;

  const mean = values.reduce((sum, val) => sum + val, 0) / values.length;
  const squaredDiffs = values.map((val) => Math.pow(val - mean, 2));
  const variance = squaredDiffs.reduce((sum, val) => sum + val, 0) / values.length;

  return variance;
}

/**
 * Sigmoid function
 */
function sigmoid(x: number): number {
  return 1 / (1 + Math.exp(-x));
}

/**
 * Confidence result
 */
export interface ConfidenceResult {
  confidence_score: number;
  confidence: 'high' | 'medium' | 'low';
}

/**
 * Compute confidence based on variance metrics
 *
 * V1 Formula (simple, no SOS double-counting):
 * confidence_score = sigmoid(
 *   1.6 * |compositeDiff| -
 *   1.0 * combined_variance +
 *   0.6 * sample_strength
 * )
 *
 * @param teamA Team A ranking data
 * @param teamB Team B ranking data
 * @param compositeDiff Composite differential from predictMatch
 * @param allGames All games for variance calculation
 * @returns Confidence result with score and label
 */
export function computeConfidence(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  compositeDiff: number,
  allGames: Game[]
): ConfidenceResult {
  // Calculate variance for both teams
  const varianceA = calculateTeamVariance(teamA.team_id_master, allGames);
  const varianceB = calculateTeamVariance(teamB.team_id_master, allGames);

  // Combined variance (sqrt of sum for proper scaling)
  const combined_variance = Math.sqrt(varianceA + varianceB);

  // Sample size strength (normalized to [0, 1])
  // Use minimum of both teams' games played
  const minGamesPlayed = Math.min(
    teamA.games_played || 0,
    teamB.games_played || 0
  );
  const sample_strength = Math.min(1.0, minGamesPlayed / 30.0);

  // Use V2 fitted weights if available, otherwise use V1 defaults
  // Note: params may not be loaded yet on first call - that's OK, will use defaults
  const weights = confidenceParamsV2?.weights;
  const intercept = confidenceParamsV2?.intercept ?? 0;
  
  let confidence_score: number;
  if (weights) {
    // V2 Formula: Use fitted weights from logistic regression
    const raw_score =
      weights.composite_diff * Math.abs(compositeDiff) +
      weights.variance * combined_variance +
      weights.sample_strength * sample_strength +
      intercept;
    confidence_score = sigmoid(raw_score);
  } else {
    // V1 Formula: compositeDiff + variance + sample size
    // No SOS term to avoid double-counting (compositeDiff already captures skill gap)
    confidence_score = sigmoid(
      1.6 * Math.abs(compositeDiff) -
      1.0 * combined_variance +
      0.6 * sample_strength
    );
  }

  // Map to labels (use calibrated thresholds if available)
  const thresholds = confidenceParamsV2?.thresholds;
  const highThreshold = thresholds?.high ?? 0.68;
  const mediumThreshold = thresholds?.medium ?? 0.52;
  
  let confidence: 'high' | 'medium' | 'low';
  if (confidence_score >= highThreshold) {
    confidence = 'high';
  } else if (confidence_score >= mediumThreshold) {
    confidence = 'medium';
  } else {
    confidence = 'low';
  }

  return {
    confidence_score,
    confidence,
  };
}

