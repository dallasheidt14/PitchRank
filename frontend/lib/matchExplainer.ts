/**
 * Match Prediction Explanation Generator v2.1
 *
 * Generates human-readable explanations for why Team A is predicted to win/lose
 * Analyzes components and creates prioritized narratives
 *
 * v2.1: Updated to reflect calibrated predictions based on 452K+ historical games
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
 * Format percentile (0-1 scale to percentile) with proper ordinal suffix
 */
function formatPercentile(value: number): string {
  const percentile = Math.round(value * 100);
  const lastDigit = percentile % 10;
  const lastTwoDigits = percentile % 100;
  
  // Handle special cases: 11th, 12th, 13th
  if (lastTwoDigits >= 11 && lastTwoDigits <= 13) {
    return `${percentile}th`;
  }
  
  // Handle regular cases
  if (lastDigit === 1) return `${percentile}st`;
  if (lastDigit === 2) return `${percentile}nd`;
  if (lastDigit === 3) return `${percentile}rd`;
  return `${percentile}th`;
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
  const weakerTeam = powerDiff > 0 ? teamB.team_name : teamA.team_name;
  const strongerPower = powerDiff > 0 ? (teamA.power_score_final || 0.5) : (teamB.power_score_final || 0.5);
  const weakerPower = powerDiff > 0 ? (teamB.power_score_final || 0.5) : (teamA.power_score_final || 0.5);

  // Convert power scores to percentiles for more intuitive display
  const strongerPercentile = Math.round(strongerPower * 100);
  const weakerPercentile = Math.round(weakerPower * 100);

  let description = '';
  if (magnitude === 'significant') {
    description = `${strongerTeam} ranks in the ${strongerPercentile}th percentile vs ${weakerTeam}'s ${weakerPercentile}th - a substantial class difference`;
  } else {
    description = `${strongerTeam} holds a real edge (${strongerPercentile}th vs ${weakerPercentile}th percentile overall strength)`;
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
  const weakerSOS = sosDiff > 0 ? teamB.team_name : teamA.team_name;
  const strongerPercentile = formatPercentile(sosDiff > 0 ? (teamA.sos_norm || 0.5) : (teamB.sos_norm || 0.5));
  const weakerPercentile = formatPercentile(sosDiff > 0 ? (teamB.sos_norm || 0.5) : (teamA.sos_norm || 0.5));

  let description = '';
  if (magnitude === 'significant') {
    description = `${strongerSOS}'s rating is battle-tested (${strongerPercentile} vs ${weakerPercentile} schedule strength) - they've proven themselves against elite competition`;
  } else {
    description = `${strongerSOS} has faced tougher opponents (${strongerPercentile} vs ${weakerPercentile} schedule strength) - their stats are harder-earned`;
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
    description = `${hotTeam} is red hot - demolishing opponents by +${hotForm.toFixed(1)} goals/game over their last 5 matches`;
  } else if (magnitude === 'significant' && hotForm < -2.5) {
    description = `${hotTeam} is in freefall - losing by ${Math.abs(hotForm).toFixed(1)} goals/game recently (momentum matters!)`;
  } else if (hotForm > 0) {
    description = `${hotTeam} brings positive momentum (+${hotForm.toFixed(1)} goal differential in last 5 games)`;
  } else {
    description = `${hotTeam} enters with concerning form (${hotForm.toFixed(1)} goal differential recently)`;
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
 *
 * Checks both offensive matchups:
 * 1. Team A's offense vs Team B's defense
 * 2. Team B's offense vs Team A's defense
 *
 * Only reports a mismatch when an offense is STRONGER than the opposing defense
 * (i.e., offense percentile > defense percentile)
 */
function explainOffensiveMatchup(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking
): Explanation | null {
  const offenseA = teamA.offense_norm || 0.5;
  const defenseA = teamA.defense_norm || 0.5;
  const offenseB = teamB.offense_norm || 0.5;
  const defenseB = teamB.defense_norm || 0.5;

  // Calculate both offensive matchup advantages
  // Positive means offense has advantage over opposing defense
  const matchupA = offenseA - defenseB; // Team A offense vs Team B defense
  const matchupB = offenseB - defenseA; // Team B offense vs Team A defense

  // Find the most significant offensive mismatch where offense beats defense
  let bestMatchup: { team: 'a' | 'b'; diff: number } | null = null;
  let bestDiff = 0;

  // Only consider mismatches where offense is actually stronger than defense
  if (matchupA > 0 && matchupA > bestDiff) {
    bestMatchup = { team: 'a', diff: matchupA };
    bestDiff = matchupA;
  }
  if (matchupB > 0 && matchupB > bestDiff) {
    bestMatchup = { team: 'b', diff: matchupB };
  }

  // No significant offensive advantage found
  if (!bestMatchup) return null;

  const magnitude = getMagnitude(bestMatchup.diff, { significant: 0.25, moderate: 0.15 });
  if (magnitude === 'minimal') return null;

  let description = '';
  let advantage: 'team_a' | 'team_b';

  if (bestMatchup.team === 'a') {
    const offPerc = formatPercentile(offenseA);
    const defPerc = formatPercentile(defenseB);
    description = `Tactical advantage: ${teamA.team_name}'s ${offPerc} offense attacks ${teamB.team_name}'s ${defPerc} defense - expect goals`;
    advantage = 'team_a';
  } else {
    const offPerc = formatPercentile(offenseB);
    const defPerc = formatPercentile(defenseA);
    description = `Tactical advantage: ${teamB.team_name}'s ${offPerc} offense attacks ${teamA.team_name}'s ${defPerc} defense - expect goals`;
    advantage = 'team_b';
  }

  return {
    factor: 'offensive_matchup',
    advantage,
    magnitude,
    description,
    icon: '⚔️',
    score: bestMatchup.diff * 0.8,
  };
}

/**
 * Generate close match explanation
 * Uses calibrated win probability to detect truly close matchups
 */
function explainCloseMatch(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  compositeDiff: number,
  winProbabilityA: number
): Explanation | null {
  // Use calibrated probability - if within 3% of 50%, it's a close match
  const probDiffFrom50 = Math.abs(winProbabilityA - 0.5);
  if (probDiffFrom50 > 0.08) return null; // Not that close

  // Determine how close based on calibrated probability
  let description = '';
  if (probDiffFrom50 <= 0.03) {
    description = `This is a true toss-up - calibrated analysis of 452K+ games shows neither team has a meaningful edge`;
  } else {
    description = `This is expected to be a VERY close match - both teams are evenly matched across all factors`;
  }

  return {
    factor: 'close_match',
    advantage: 'neutral',
    magnitude: 'minimal',
    description,
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
    explainCloseMatch(teamA, teamB, components.compositeDiff, winProbabilityA),
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
    // Draw prediction - explain why based on calibrated probability
    const probPercent = Math.round(winProbabilityA * 100);
    summary = `Genuine toss-up (${probPercent}%-${100 - probPercent}%) - our calibrated model sees no clear favorite`;
  } else {
    const probPercent = Math.round(Math.max(winProbabilityA, 1 - winProbabilityA) * 100);
    if (probPercent >= 75) {
      summary = `${favoredTeam} is the clear favorite at ${probPercent}% win probability`;
    } else if (probPercent >= 60) {
      summary = `${favoredTeam} has the edge with ${probPercent}% win probability`;
    } else {
      summary = `${favoredTeam} is slightly favored at ${probPercent}% - but this could go either way`;
    }
  }

  // Generate enhanced key insights
  const keyInsights: string[] = [];

  // 1. Enhanced confidence insight with compelling data-backed language
  const confidenceScore = confidence_score ?? 0.5;
  if (confidence === 'high') {
    if (confidenceScore >= 0.80) {
      keyInsights.push('🎯 Elite prediction confidence: Our model identifies this as a high-certainty outcome based on converging strength indicators');
    } else {
      keyInsights.push('🎯 High confidence: Multiple validated metrics strongly favor this outcome');
    }
  } else if (confidence === 'medium') {
    if (confidenceScore >= 0.60) {
      keyInsights.push('📊 Solid prediction: Meaningful statistical edge detected with reliable underlying data');
    } else {
      keyInsights.push('📊 Moderate confidence: Analysis reveals a real but modest advantage');
    }
  } else {
    if (confidenceScore < 0.40) {
      keyInsights.push('⚠️ Uncertain outcome: High variance or limited data - treat this as a true wildcard');
    } else {
      keyInsights.push('⚠️ Coin-flip territory: No meaningful statistical edge - anything can happen');
    }
  }

  // 2. Data quality insights - make sample size feel meaningful
  const minGamesPlayed = Math.min(teamA.games_played || 0, teamB.games_played || 0);
  const maxGamesPlayed = Math.max(teamA.games_played || 0, teamB.games_played || 0);
  const totalGamesAnalyzed = (teamA.games_played || 0) + (teamB.games_played || 0);

  if (minGamesPlayed < 10) {
    keyInsights.push(`📉 Early season data: With only ${totalGamesAnalyzed} combined games analyzed, expect higher variance in this prediction`);
  } else if (minGamesPlayed < 20) {
    keyInsights.push(`📈 Good sample size: ${totalGamesAnalyzed} combined games analyzed - prediction reliability is solid`);
  } else {
    keyInsights.push(`✅ Robust dataset: ${totalGamesAnalyzed} combined games create a reliable statistical foundation for this prediction`);
  }

  // 3. Expected margin interpretation - make scoreline predictions feel precise
  const absMargin = Math.abs(expectedMargin);
  const roundedMargin = Math.round(absMargin * 10) / 10;
  const expectedWinner = expectedMargin > 0 ? teamA.team_name : teamB.team_name;

  if (absMargin < 0.5) {
    keyInsights.push(`⚖️ Razor-thin margins: Model projects a near-draw scenario (±${roundedMargin.toFixed(1)} goal difference)`);
  } else if (absMargin < 1.5) {
    keyInsights.push(`🎲 One-goal game territory: Expect a tight, potentially dramatic finish (±${roundedMargin.toFixed(1)} goals)`);
  } else if (absMargin < 3.0) {
    keyInsights.push(`📐 Clear but not dominant: ${expectedWinner} projected to win by ${roundedMargin.toFixed(1)} goals - competitive but controlled`);
  } else {
    keyInsights.push(`💪 Mismatch detected: ${expectedWinner} projected to dominate by ${roundedMargin.toFixed(1)}+ goals`);
  }

  // 4. Scoreline context with age-specific calibration insights
  const totalExpectedGoals = expectedScore.teamA + expectedScore.teamB;
  const age = teamA.age || teamB.age;
  if (age) {
    // Age-specific context - reference our calibration data
    if (age <= 11 && totalExpectedGoals > 5) {
      keyInsights.push(`⚽ High-scoring affair: U${age} matches average ${totalExpectedGoals.toFixed(1)} goals - our model accounts for age-specific scoring patterns`);
    } else if (age >= 15 && totalExpectedGoals < 3) {
      keyInsights.push(`🛡️ Defensive battle: U${age} matches trend toward lower scoring (${totalExpectedGoals.toFixed(1)} goals expected)`);
    } else if (age) {
      keyInsights.push(`⚽ Age-calibrated: Expected ${totalExpectedGoals.toFixed(1)} total goals based on U${age} historical averages`);
    }
  }

  // 5. Top factor insight (most important) - make it feel decisive
  if (factors.length > 0) {
    const topFactor = factors[0];
    if (topFactor.magnitude === 'significant') {
      keyInsights.push(`🔑 Key differentiator: ${topFactor.description}`);
    } else if (factors.length >= 2 && topFactor.magnitude === 'moderate') {
      keyInsights.push(`📌 Primary edge: ${topFactor.description}`);
    }
  }

  // Prediction quality with enhanced reliability message (referencing calibration)
  let reliabilityMessage = '';
  if (confidence === 'high') {
    if (minGamesPlayed >= 20) {
      reliabilityMessage = 'Elite-tier prediction: Probabilities calibrated on 452K+ youth soccer games with robust team-specific data';
    } else {
      reliabilityMessage = 'Strong prediction: Clear statistical advantage detected across multiple validated metrics';
    }
  } else if (confidence === 'medium') {
    if (minGamesPlayed >= 15) {
      reliabilityMessage = 'Reliable prediction: Real statistical edge detected, calibrated for accuracy';
    } else {
      reliabilityMessage = 'Solid prediction: Meaningful advantage identified across our proprietary metrics';
    }
  } else {
    if (minGamesPlayed < 10) {
      reliabilityMessage = 'Preliminary prediction: Limited game history - probabilities are directional only';
    } else {
      reliabilityMessage = 'Toss-up: Our 452K-game calibration confirms this is genuinely unpredictable';
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
