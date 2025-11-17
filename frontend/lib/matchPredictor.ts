/**
 * Match Prediction Engine
 *
 * Enhanced prediction model using multiple features:
 * - Power Score Differential (50%)
 * - SOS Differential (20%)
 * - Recent Form (20%)
 * - Matchup Asymmetry (10%)
 *
 * Validated at 66.2% direction accuracy
 */

import type { TeamWithRanking } from './types';
import type { Game } from './types';

// Feature weights (validated configuration)
const WEIGHTS = {
  POWER_SCORE: 0.50,
  SOS: 0.20,
  RECENT_FORM: 0.20,
  MATCHUP: 0.10,
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
 * Returns average goal differential in last N games
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

  return gamesWithScores > 0 ? totalGoalDiff / gamesWithScores : 0;
}

/**
 * Normalize recent form to 0-1 scale using sigmoid
 */
function normalizeRecentForm(goalDiff: number): number {
  // Sigmoid normalization: goalDiff of +2 -> ~0.73, -2 -> ~0.27
  return 1 / (1 + Math.exp(-goalDiff * 0.5));
}

/**
 * Sigmoid function for win probability
 */
function sigmoid(x: number): number {
  return 1 / (1 + Math.exp(-x));
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
 * Predict match outcome with enhanced model
 */
export function predictMatch(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  allGames: Game[]
): MatchPrediction {
  // 1. Base power score differential
  const powerDiff = (teamA.power_score_final || 0.5) - (teamB.power_score_final || 0.5);

  // 2. SOS differential
  const sosDiff = (teamA.sos_norm || 0.5) - (teamB.sos_norm || 0.5);

  // 3. Recent form
  const formA = calculateRecentForm(teamA.team_id_master, allGames);
  const formB = calculateRecentForm(teamB.team_id_master, allGames);
  const formDiffRaw = formA - formB;
  const formDiffNorm = normalizeRecentForm(formDiffRaw) - 0.5;

  // 4. Offense vs Defense matchup asymmetry
  const offenseA = teamA.offense_norm || 0.5;
  const defenseA = teamA.defense_norm || 0.5;
  const offenseB = teamB.offense_norm || 0.5;
  const defenseB = teamB.defense_norm || 0.5;

  const matchupAdvantage = (offenseA - defenseB) - (offenseB - defenseA);

  // 5. Composite differential (weighted combination)
  const compositeDiff =
    WEIGHTS.POWER_SCORE * powerDiff +
    WEIGHTS.SOS * sosDiff +
    WEIGHTS.RECENT_FORM * formDiffNorm +
    WEIGHTS.MATCHUP * matchupAdvantage;

  // 6. Win probability
  const winProbA = sigmoid(SENSITIVITY * compositeDiff);
  const winProbB = 1 - winProbA;

  // 7. Expected goal margin
  const expectedMargin = compositeDiff * MARGIN_COEFFICIENT;

  // 8. Expected scores (league average ~2.5 goals per team)
  const leagueAvgGoals = 2.5;
  const expectedScoreA = Math.max(0, leagueAvgGoals + (expectedMargin / 2));
  const expectedScoreB = Math.max(0, leagueAvgGoals - (expectedMargin / 2));

  // 9. Predicted winner
  let predictedWinner: 'team_a' | 'team_b' | 'draw';
  if (winProbA > 0.55) predictedWinner = 'team_a';
  else if (winProbA < 0.45) predictedWinner = 'team_b';
  else predictedWinner = 'draw';

  // 10. Confidence level
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
