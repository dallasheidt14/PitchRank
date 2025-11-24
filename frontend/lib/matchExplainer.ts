/**
 * Match Prediction Explanation Generator
 *
 * Generates human-readable explanations for why Team A is predicted to win/lose
 * Analyzes components and creates prioritized narratives
 */

import type { TeamWithRanking } from './types';
import type { MatchPrediction } from './matchPredictor';

export type ExplanationMagnitude = 'significant' | 'moderate' | 'minimal';
export type ExplanationFactor =
  | 'overall_strength'
  | 'recent_form'
  | 'schedule_strength'
  | 'offensive_matchup'
  | 'defensive_matchup'
  | 'close_match';

export interface Explanation {
  factor: ExplanationFactor;
  advantage: 'team_a' | 'team_b' | 'neutral';
  magnitude: ExplanationMagnitude;
  description: string;
  icon: string;
  score: number; // For sorting by importance
}

export interface MatchExplanation {
  // Summary
  summary: string;

  // Top factors (ranked by importance)
  factors: Explanation[];

  // Key insights (bullet points)
  keyInsights: string[];

  // Prediction quality indicator
  predictionQuality: {
    confidence: 'high' | 'medium' | 'low';
    reliability: string; // e.g., "Based on 1000+ similar matchups, 97% accurate"
  };
}

/**
 * Determine magnitude from differential value
 */
function getMagnitude(absDiff: number, thresholds = { significant: 0.15, moderate: 0.08 }): ExplanationMagnitude {
  if (absDiff >= thresholds.significant) return 'significant';
  if (absDiff >= thresholds.moderate) return 'moderate';
  return 'minimal';
}

/**
 * Format percentile (0-1 scale to percentile)
 */
function formatPercentile(value: number): number {
  return Math.round(value * 100);
}

/**
 * Generate explanation for overall power score differential
 */
function explainPowerScore(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  powerDiff: number
): Explanation | null {
  const absDiff = Math.abs(powerDiff);
  const magnitude = getMagnitude(absDiff, { significant: 0.15, moderate: 0.08 });

  if (magnitude === 'minimal') return null; // Not worth mentioning if minimal

  const advantage = powerDiff > 0 ? 'team_a' : 'team_b';
  const strongerTeam = powerDiff > 0 ? teamA.team_name : teamB.team_name;
  const powerA = teamA.power_score_final || 0.5;
  const powerB = teamB.power_score_final || 0.5;

  let description = '';
  if (magnitude === 'significant') {
    description = `${strongerTeam} is significantly stronger overall (power score: ${powerA.toFixed(2)} vs ${powerB.toFixed(2)})`;
  } else {
    description = `${strongerTeam} has a moderate edge in overall strength (power score: ${powerA.toFixed(2)} vs ${powerB.toFixed(2)})`;
  }

  return {
    factor: 'overall_strength',
    advantage,
    magnitude,
    description,
    icon: '⚡',
    score: absDiff * 2.0, // Weight heavily
  };
}

/**
 * Generate explanation for SOS differential
 */
function explainSOS(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  sosDiff: number
): Explanation | null {
  const absDiff = Math.abs(sosDiff);
  const magnitude = getMagnitude(absDiff, { significant: 0.20, moderate: 0.10 });

  if (magnitude === 'minimal') return null;

  const advantage = sosDiff > 0 ? 'team_a' : 'team_b';
  const strongerSOS = sosDiff > 0 ? teamA.team_name : teamB.team_name;
  const percentileA = formatPercentile(teamA.sos_norm || 0.5);
  const percentileB = formatPercentile(teamB.sos_norm || 0.5);

  let description = '';
  if (magnitude === 'significant') {
    description = `${strongerSOS} has played MUCH tougher competition (${percentileA}th vs ${percentileB}th percentile schedule strength). Their rating is more battle-tested.`;
  } else {
    description = `${strongerSOS} has faced tougher opponents (${percentileA}th vs ${percentileB}th percentile schedule strength)`;
  }

  return {
    factor: 'schedule_strength',
    advantage,
    magnitude,
    description,
    icon: '📅',
    score: absDiff * 1.5,
  };
}

/**
 * Generate explanation for recent form
 */
function explainRecentForm(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  formA: number,
  formB: number,
  formDiffRaw: number
): Explanation | null {
  const absDiff = Math.abs(formDiffRaw);

  // Form is in goal differential per game
  // Thresholds: >3.0 is significant, >1.5 is moderate
  let magnitude: ExplanationMagnitude;
  if (absDiff >= 3.0) magnitude = 'significant';
  else if (absDiff >= 1.5) magnitude = 'moderate';
  else return null; // Not worth mentioning

  const advantage = formDiffRaw > 0 ? 'team_a' : 'team_b';
  const hotTeam = formDiffRaw > 0 ? teamA.team_name : teamB.team_name;
  const hotForm = formDiffRaw > 0 ? formA : formB;

  let description = '';
  if (magnitude === 'significant' && hotForm > 2.5) {
    description = `${hotTeam} is on FIRE 🔥 - winning by an average of ${hotForm.toFixed(1)} goals in their last 5 games`;
  } else if (magnitude === 'significant' && hotForm < -2.5) {
    description = `${hotTeam} is struggling badly - losing by an average of ${Math.abs(hotForm).toFixed(1)} goals in their last 5 games`;
  } else if (hotForm > 0) {
    description = `${hotTeam} has strong recent form (avg goal differential: +${hotForm.toFixed(1)} in last 5 games)`;
  } else {
    description = `${hotTeam} has poor recent form (avg goal differential: ${hotForm.toFixed(1)} in last 5 games)`;
  }

  return {
    factor: 'recent_form',
    advantage,
    magnitude,
    description,
    icon: '📈',
    score: absDiff * 1.2,
  };
}

/**
 * Generate explanation for offensive matchup
 */
function explainOffensiveMatchup(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking
): Explanation | null {
  const offenseA = teamA.offense_norm || 0.5;
  const defenseB = teamB.defense_norm || 0.5;

  const matchupDiff = offenseA - defenseB;
  const absDiff = Math.abs(matchupDiff);

  const magnitude = getMagnitude(absDiff, { significant: 0.25, moderate: 0.15 });
  if (magnitude === 'minimal') return null;

  const advantage = matchupDiff > 0 ? 'team_a' : 'team_b';

  let description = '';
  if (matchupDiff > 0) {
    const offPerc = formatPercentile(offenseA);
    const defPerc = formatPercentile(defenseB);
    description = `${teamA.team_name}'s strong offense (${offPerc}th percentile) faces ${teamB.team_name}'s weaker defense (${defPerc}th percentile)`;
  } else {
    const offPerc = formatPercentile(teamB.offense_norm || 0.5);
    const defPerc = formatPercentile(teamA.defense_norm || 0.5);
    description = `${teamB.team_name}'s strong offense (${offPerc}th percentile) faces ${teamA.team_name}'s weaker defense (${defPerc}th percentile)`;
  }

  return {
    factor: 'offensive_matchup',
    advantage,
    magnitude,
    description,
    icon: '⚔️',
    score: absDiff * 0.8,
  };
}

/**
 * Generate close match explanation
 */
function explainCloseMatch(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  compositeDiff: number
): Explanation | null {
  if (Math.abs(compositeDiff) > 0.05) return null; // Not that close

  return {
    factor: 'close_match',
    advantage: 'neutral',
    magnitude: 'minimal',
    description: `This is expected to be a VERY close match - both teams are evenly matched across all factors`,
    icon: '⚖️',
    score: 1.5, // High priority for close matches
  };
}

/**
 * Generate complete match explanation
 */
export function explainMatch(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  prediction: MatchPrediction
): MatchExplanation {
  const { components, formA, formB, winProbabilityA, confidence, confidence_score, expectedMargin, expectedScore } = prediction;

  // Generate all possible explanations
  const allExplanations: (Explanation | null)[] = [
    explainPowerScore(teamA, teamB, components.powerDiff),
    explainSOS(teamA, teamB, components.sosDiff),
    explainRecentForm(teamA, teamB, formA, formB, components.formDiffRaw),
    explainOffensiveMatchup(teamA, teamB),
    explainCloseMatch(teamA, teamB, components.compositeDiff),
  ];

  // Filter out nulls and sort by importance (score)
  const factors = allExplanations
    .filter((e): e is Explanation => e !== null)
    .sort((a, b) => b.score - a.score)
    .slice(0, 4); // Top 4 factors

  // Generate summary
  const favoredTeam = prediction.predictedWinner === 'team_a' ? teamA.team_name :
                      prediction.predictedWinner === 'team_b' ? teamB.team_name :
                      'Neither team';

  let summary = '';
  if (prediction.predictedWinner === 'draw') {
    summary = `Too close to call - this should be a tight match`;
  } else {
    const probPercent = Math.round(Math.max(winProbabilityA, 1 - winProbabilityA) * 100);
    summary = `${favoredTeam} is favored with a ${probPercent}% win probability`;
  }

  // Generate enhanced key insights
  const keyInsights: string[] = [];

  // 1. Enhanced confidence insight with context
  const confidenceScore = confidence_score ?? 0.5;
  if (confidence === 'high') {
    if (confidenceScore >= 0.80) {
      keyInsights.push('Very high confidence: Multiple strong indicators align with clear advantage');
    } else {
      keyInsights.push('High confidence: Strong indicators favor this outcome');
    }
  } else if (confidence === 'medium') {
    if (confidenceScore >= 0.60) {
      keyInsights.push('Medium-high confidence: Meaningful advantage detected with good data quality');
    } else {
      keyInsights.push('Medium confidence: Moderate but meaningful advantage detected');
    }
  } else {
    if (confidenceScore < 0.40) {
      keyInsights.push('Low confidence: Limited data or high variance makes prediction uncertain');
    } else {
      keyInsights.push('Low confidence: Limited edge; result unpredictable');
    }
  }

  // 2. Data quality insights
  const minGamesPlayed = Math.min(teamA.games_played || 0, teamB.games_played || 0);
  const maxGamesPlayed = Math.max(teamA.games_played || 0, teamB.games_played || 0);
  
  if (minGamesPlayed < 10) {
    keyInsights.push(`Limited data: One or both teams have fewer than 10 recent games, reducing prediction reliability`);
  } else if (minGamesPlayed < 20) {
    keyInsights.push(`Moderate sample size: Both teams have ${minGamesPlayed}+ recent games, providing reasonable data quality`);
  } else {
    keyInsights.push(`Strong data foundation: Both teams have ${minGamesPlayed}+ recent games, enhancing prediction reliability`);
  }

  // 3. Expected margin interpretation
  const absMargin = Math.abs(expectedMargin);
  const roundedMargin = Math.round(absMargin * 10) / 10;
  
  if (absMargin < 0.5) {
    keyInsights.push(`Expected to be a very close match (predicted margin: ${roundedMargin.toFixed(1)} goals)`);
  } else if (absMargin < 1.5) {
    keyInsights.push(`Expected to be a tight contest (predicted margin: ${roundedMargin.toFixed(1)} goals)`);
  } else if (absMargin < 3.0) {
    keyInsights.push(`Expected to be a competitive match (predicted margin: ${roundedMargin.toFixed(1)} goals)`);
  } else {
    const expectedWinner = expectedMargin > 0 ? teamA.team_name : teamB.team_name;
    keyInsights.push(`Expected to be a decisive result (${expectedWinner} favored by ${roundedMargin.toFixed(1)} goals)`);
  }

  // 4. Scoreline context
  const totalExpectedGoals = expectedScore.teamA + expectedScore.teamB;
  const age = teamA.age || teamB.age;
  if (age) {
    // Age-specific context
    if (age <= 11 && totalExpectedGoals > 5) {
      keyInsights.push(`High-scoring match expected for U${age} (${totalExpectedGoals.toFixed(1)} total goals)`);
    } else if (age >= 15 && totalExpectedGoals < 3) {
      keyInsights.push(`Low-scoring defensive match expected for U${age} (${totalExpectedGoals.toFixed(1)} total goals)`);
    }
  }

  // 5. Top factor insight (most important)
  if (factors.length > 0) {
    const topFactor = factors[0];
    if (topFactor.magnitude === 'significant') {
      keyInsights.push(`Primary factor: ${topFactor.description}`);
    }
  }

  // Prediction quality with enhanced reliability message
  let reliabilityMessage = '';
  if (confidence === 'high') {
    if (minGamesPlayed >= 20) {
      reliabilityMessage = 'Prediction based on multiple strong factors with excellent data quality';
    } else {
      reliabilityMessage = 'Prediction based on multiple strong factors with clear advantage';
    }
  } else if (confidence === 'medium') {
    if (minGamesPlayed >= 15) {
      reliabilityMessage = 'Prediction based on moderate advantages with good data quality';
    } else {
      reliabilityMessage = 'Prediction based on moderate advantages across key metrics';
    }
  } else {
    if (minGamesPlayed < 10) {
      reliabilityMessage = 'Limited data available; prediction reliability reduced';
    } else {
      reliabilityMessage = 'Close matchup with minimal separation across all factors';
    }
  }

  const predictionQuality = {
    confidence,
    reliability: reliabilityMessage,
  };

  return {
    summary,
    factors,
    keyInsights,
    predictionQuality,
  };
}
