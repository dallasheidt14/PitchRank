/**
 * Match Prediction Explanation Generator v3
 *
 * Generates human-readable explanations for why Team A is predicted to win/lose
 * Analyzes components and creates prioritized narratives
 *
 * v2.1: Updated to reflect calibrated predictions based on 452K+ historical games
 */

import type { TeamWithRanking } from './types';
import type { MatchPrediction } from './matchPredictor';
import { extractAgeFromTeamName } from './utils';

export type ExplanationMagnitude = 'significant' | 'moderate' | 'minimal';
export type ExplanationFactor =
  | 'overall_strength'
  | 'recent_form'
  | 'schedule_strength'
  | 'offensive_matchup'
  | 'defensive_matchup'
  | 'close_match'
  | 'common_opponents'
  | 'head_to_head';

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
 * Generate explanation for the primary strength edge
 */
function explainPowerScore(teamA: TeamWithRanking, teamB: TeamWithRanking, powerDiff: number): Explanation | null {
  const absDiff = Math.abs(powerDiff);
  const magnitude = getMagnitude(absDiff, { significant: 0.15, moderate: 0.08 });

  if (magnitude === 'minimal') return null; // Not worth mentioning if minimal

  const advantage = powerDiff > 0 ? 'team_a' : 'team_b';
  const strongerTeam = powerDiff > 0 ? teamA.team_name : teamB.team_name;
  const strongerPower = powerDiff > 0 ? teamA.power_score_final || 0.5 : teamB.power_score_final || 0.5;
  const weakerPower = powerDiff > 0 ? teamB.power_score_final || 0.5 : teamA.power_score_final || 0.5;
  const strongerRank = powerDiff > 0 ? teamA.rank_in_cohort_final : teamB.rank_in_cohort_final;
  const weakerRank = powerDiff > 0 ? teamB.rank_in_cohort_final : teamA.rank_in_cohort_final;

  let description = '';
  if (strongerRank != null && weakerRank != null) {
    if (magnitude === 'significant') {
      description = `${strongerTeam} brings the stronger overall profile, ranking #${strongerRank} versus #${weakerRank} in this age group`;
    } else {
      description = `${strongerTeam} enters with the better overall body of work and the higher standing in this age group`;
    }
  } else {
    const strongerRating = Math.round(strongerPower * 100);
    const weakerRating = Math.round(weakerPower * 100);

    if (magnitude === 'significant') {
      description = `${strongerTeam} carries a clear overall strength edge (${strongerRating} vs ${weakerRating})`;
    } else {
      description = `${strongerTeam} has the slightly stronger overall profile (${strongerRating} vs ${weakerRating})`;
    }
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
function explainSOS(teamA: TeamWithRanking, teamB: TeamWithRanking, sosDiff: number): Explanation | null {
  const absDiff = Math.abs(sosDiff);
  const magnitude = getMagnitude(absDiff, { significant: 0.2, moderate: 0.1 });

  if (magnitude === 'minimal') return null;

  const advantage = sosDiff > 0 ? 'team_a' : 'team_b';
  const strongerSOS = sosDiff > 0 ? teamA.team_name : teamB.team_name;
  const _weakerSOS = sosDiff > 0 ? teamB.team_name : teamA.team_name;
  const strongerPercentile = formatPercentile(sosDiff > 0 ? teamA.sos_norm || 0.5 : teamB.sos_norm || 0.5);
  const weakerPercentile = formatPercentile(sosDiff > 0 ? teamB.sos_norm || 0.5 : teamA.sos_norm || 0.5);

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
  const betterTeam = formDiffRaw > 0 ? teamA.team_name : teamB.team_name;
  const worseTeam = formDiffRaw > 0 ? teamB.team_name : teamA.team_name;
  const betterForm = formDiffRaw > 0 ? formA : formB;
  const worseForm = formDiffRaw > 0 ? formB : formA;

  let description = '';

  // Case 1: Better team is on fire (positive form, significant gap)
  if (magnitude === 'significant' && betterForm > 2.5) {
    description = `${betterTeam} is red hot - demolishing opponents by +${betterForm.toFixed(1)} goals/game over their last 5 matches`;
  }
  // Case 2: Worse team is struggling badly (the gap comes from their collapse)
  else if (magnitude === 'significant' && worseForm < -2.0) {
    description = `${worseTeam} is struggling badly (${worseForm.toFixed(1)} goal diff recently), giving ${betterTeam} a momentum edge`;
  }
  // Case 3: Better team has positive momentum
  else if (betterForm > 0.5) {
    description = `${betterTeam} brings positive momentum (+${betterForm.toFixed(1)} goal differential in last 5 games)`;
  }
  // Case 4: Both struggling but better team is less bad
  else if (betterForm <= 0.5 && worseForm < betterForm) {
    description = `${betterTeam} has better recent form (${betterForm > 0 ? '+' : ''}${betterForm.toFixed(1)} vs ${worseForm.toFixed(1)} goal diff) - less concerning trajectory`;
  }
  // Case 5: Generic form advantage
  else {
    description = `${betterTeam} has the form edge with a ${absDiff.toFixed(1)} goal differential advantage in recent matches`;
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
function explainOffensiveMatchup(teamA: TeamWithRanking, teamB: TeamWithRanking): Explanation | null {
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
  winProbabilityA: number,
  drawProbability?: number
): Explanation | null {
  if ((drawProbability ?? 0) >= 0.2) {
    return {
      factor: 'close_match',
      advantage: 'neutral',
      magnitude: 'minimal',
      description: `This looks like a real draw candidate because the teams profile very similarly`,
      icon: '⚖️',
      score: 1.6,
    };
  }

  // Use calibrated probability - if within 3% of 50%, it's a close match
  const probDiffFrom50 = Math.abs(winProbabilityA - 0.5);
  if (probDiffFrom50 > 0.08) return null; // Not that close

  // Determine how close based on calibrated probability
  let description = '';
  if (probDiffFrom50 <= 0.03) {
    description = `This is a true toss-up - neither side has built a meaningful edge on paper`;
  } else {
    description = `This is expected to stay tight because the teams are closely matched across the main indicators`;
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
 * Generate head-to-head explanation if H2H history exists
 * This is HIGHLY predictive - teams that consistently beat another have proven matchup advantages
 */
function explainHeadToHead(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  h2h?: { gamesPlayed: number; avgMargin: number }
): Explanation | null {
  if (!h2h || h2h.gamesPlayed === 0) return null;

  const absMargin = Math.abs(h2h.avgMargin);
  const favoredTeam = h2h.avgMargin > 0 ? teamA.team_name : teamB.team_name;
  const advantage: 'team_a' | 'team_b' = h2h.avgMargin > 0 ? 'team_a' : 'team_b';

  // Determine magnitude based on average margin and games played
  let magnitude: ExplanationMagnitude;
  if (h2h.gamesPlayed >= 3 && absMargin >= 2.0) {
    magnitude = 'significant';
  } else if (h2h.gamesPlayed >= 2 && absMargin >= 1.0) {
    magnitude = 'moderate';
  } else {
    magnitude = 'minimal';
  }

  if (magnitude === 'minimal' && h2h.gamesPlayed < 2) return null;

  let description = '';
  if (magnitude === 'significant') {
    description = `Historical dominance: ${favoredTeam} holds a +${absMargin.toFixed(1)} goal average across ${h2h.gamesPlayed} previous meetings`;
  } else if (h2h.gamesPlayed >= 2) {
    description = `Head-to-head edge: ${favoredTeam} has a +${absMargin.toFixed(1)} goal average in ${h2h.gamesPlayed} prior matchups`;
  } else {
    description = `Prior meeting: ${favoredTeam} won their last encounter by ${absMargin.toFixed(0)} goal(s)`;
  }

  // H2H gets high score because it's highly predictive
  const score = (absMargin * 0.5 + h2h.gamesPlayed * 0.3) * 1.5;

  return {
    factor: 'head_to_head',
    advantage,
    magnitude,
    description,
    icon: '🔄',
    score,
  };
}

function explainCommonOpponents(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  commonOpponents?: {
    sharedOpponents: number;
    comparedGames: number;
    avgMarginDiff: number;
    pointsPerGameDiff: number;
    reliability: number;
  },
  commonOpponentSignal?: number
): Explanation | null {
  if (!commonOpponents || commonOpponents.sharedOpponents < 2) return null;

  const signal = commonOpponentSignal ?? 0;
  if (Math.abs(signal) < 0.025) return null;

  const advantage: 'team_a' | 'team_b' = signal > 0 ? 'team_a' : 'team_b';
  const favoredTeam = signal > 0 ? teamA.team_name : teamB.team_name;
  const absMargin = Math.abs(commonOpponents.avgMarginDiff);
  const absPoints = Math.abs(commonOpponents.pointsPerGameDiff);

  let magnitude: ExplanationMagnitude;
  if (
    commonOpponents.sharedOpponents >= 4 &&
    commonOpponents.reliability >= 0.45 &&
    (absMargin >= 1.1 || absPoints >= 0.9)
  ) {
    magnitude = 'significant';
  } else if (absMargin >= 0.6 || absPoints >= 0.55) {
    magnitude = 'moderate';
  } else {
    magnitude = 'minimal';
  }

  if (magnitude === 'minimal') return null;

  let description = '';
  if (absPoints >= 0.8) {
    description = `Shared-opponent edge: against ${commonOpponents.sharedOpponents} common opponents, ${favoredTeam} has taken about ${absPoints.toFixed(1)} more points per game`;
  } else {
    description = `Shared-opponent edge: against ${commonOpponents.sharedOpponents} common opponents, ${favoredTeam} has been roughly ${absMargin.toFixed(1)} goals per game better`;
  }

  return {
    factor: 'common_opponents',
    advantage,
    magnitude,
    description,
    icon: 'vs',
    score: Math.abs(signal) * 12 + commonOpponents.sharedOpponents * 0.18 + commonOpponents.reliability * 0.6,
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
  const {
    components,
    formA,
    formB,
    winProbabilityA,
    winProbabilityB,
    drawProbability,
    confidence,
    confidence_score,
    expectedMargin,
    expectedScore,
    h2h,
    commonOpponents,
  } = prediction;

  // Generate all possible explanations
  const allExplanations: (Explanation | null)[] = [
    explainHeadToHead(teamA, teamB, h2h), // H2H first - highly predictive
    explainCommonOpponents(teamA, teamB, commonOpponents, components.commonOpponentSignal),
    explainPowerScore(teamA, teamB, components.powerDiff),
    explainSOS(teamA, teamB, components.sosDiff),
    explainRecentForm(teamA, teamB, formA, formB, components.formDiffRaw),
    explainOffensiveMatchup(teamA, teamB),
    explainCloseMatch(teamA, teamB, components.compositeDiff, winProbabilityA, drawProbability),
  ];

  // Filter out nulls
  const allFactors = allExplanations.filter((e): e is Explanation => e !== null);

  // Separate factors by who they favor
  const favoredSide =
    prediction.predictedWinner === 'team_a' ? 'team_a' : prediction.predictedWinner === 'team_b' ? 'team_b' : null;

  // For "Why X is Favored", only show factors that favor the predicted winner (or neutral)
  // This prevents confusing displays like "Why Excel is Favored: [Engilman has momentum]"
  const factors = allFactors
    .filter((f) => f.advantage === favoredSide || f.advantage === 'neutral')
    .sort((a, b) => b.score - a.score)
    .slice(0, 4);

  // If no factors favor the winner, fall back to showing top factors by score
  // (This can happen in very close matches)
  const displayFactors = factors.length > 0 ? factors : allFactors.sort((a, b) => b.score - a.score).slice(0, 4);

  // Generate summary
  const favoredTeam =
    prediction.predictedWinner === 'team_a'
      ? teamA.team_name
      : prediction.predictedWinner === 'team_b'
        ? teamB.team_name
        : 'Neither team';

  let summary = '';
  if (prediction.predictedWinner === 'draw') {
    const drawPercent = Math.round((drawProbability ?? 0.33) * 100);
    const teamAPercent = Math.round(winProbabilityA * 100);
    const teamBPercent = Math.round(winProbabilityB * 100);
    summary = `Genuine toss-up (${teamAPercent}% / ${drawPercent}% draw / ${teamBPercent}%) - our model sees no clear favorite`;
  } else {
    const probPercent = Math.round(
      prediction.predictedWinner === 'team_a' ? winProbabilityA * 100 : winProbabilityB * 100
    );
    if (probPercent >= 75) {
      summary = `${favoredTeam} is the clear favorite at ${probPercent}% win probability`;
    } else if (probPercent >= 60) {
      summary = `${favoredTeam} has the edge with ${probPercent}% win probability`;
    } else {
      summary = `${favoredTeam} is slightly favored at ${probPercent}% - but this could go either way`;
    }
  }

  // Generate user-facing key insights
  const keyInsights: string[] = [];

  // 1. Confidence framing
  const confidenceScore = confidence_score ?? 0.5;
  if (confidence === 'high') {
    if (confidenceScore >= 0.8) {
      keyInsights.push(
        'This is one of the clearer matchups on the board, with multiple indicators pointing the same way.'
      );
    } else {
      keyInsights.push('There is a strong edge here, even if this still looks more controlled than overwhelming.');
    }
  } else if (confidence === 'medium') {
    if (confidenceScore >= 0.6) {
      keyInsights.push('One team has a real edge, but this is still well within upset range if the game swings early.');
    } else {
      keyInsights.push('The model leans one way, but the advantage is modest rather than decisive.');
    }
  } else {
    if (confidenceScore < 0.4) {
      keyInsights.push(
        'This is a volatile matchup with enough uncertainty that a result either way would not be surprising.'
      );
    } else {
      keyInsights.push('This grades out as coin-flip territory, with no durable edge separating the teams.');
    }
  }

  // 2. Data quality
  const gamesA = teamA.games_played || 0;
  const gamesB = teamB.games_played || 0;
  const minGamesPlayed = Math.min(gamesA, gamesB);
  const maxGamesPlayed = Math.max(gamesA, gamesB);

  if (minGamesPlayed < 5) {
    const limitedTeam = gamesA < gamesB ? teamA.team_name : teamB.team_name;
    keyInsights.push(
      `${limitedTeam} has only ${minGamesPlayed} recent results on file, so this projection is less stable than usual.`
    );
  } else if (minGamesPlayed < 10) {
    keyInsights.push(
      `Both teams still have fairly light recent samples (${minGamesPlayed}-${maxGamesPlayed} games), which adds volatility.`
    );
  } else if (minGamesPlayed < 20) {
    keyInsights.push(`Each side has a usable sample of recent matches, giving this projection a solid dataset.`);
  } else {
    keyInsights.push(
      `Both teams have deep recent samples (${minGamesPlayed}+ matches), which makes the read more trustworthy.`
    );
  }

  if (
    commonOpponents &&
    commonOpponents.sharedOpponents >= 2 &&
    Math.abs(components.commonOpponentSignal ?? 0) >= 0.025
  ) {
    const commonOpponentTeam = (components.commonOpponentSignal ?? 0) > 0 ? teamA.team_name : teamB.team_name;
    const absCommonMargin = Math.abs(commonOpponents.avgMarginDiff);
    const absCommonPoints = Math.abs(commonOpponents.pointsPerGameDiff);

    if (absCommonPoints >= 0.8) {
      keyInsights.push(
        `${commonOpponentTeam} has done better against ${commonOpponents.sharedOpponents} shared opponents, taking about ${absCommonPoints.toFixed(1)} more points per game in those matchups.`
      );
    } else {
      keyInsights.push(
        `${commonOpponentTeam} has been stronger against ${commonOpponents.sharedOpponents} shared opponents, running about ${absCommonMargin.toFixed(1)} goals per game better in that shared sample.`
      );
    }
  }

  // 3. Margin interpretation
  const absMargin = Math.abs(expectedMargin);
  const roundedMargin = Math.round(absMargin * 10) / 10;
  const expectedWinner = expectedMargin > 0 ? teamA.team_name : teamB.team_name;

  if (absMargin < 0.5) {
    keyInsights.push(
      `The projected margin is almost flat (${roundedMargin.toFixed(1)} goals), so a draw-like game script is very plausible.`
    );
  } else if (absMargin < 1.5) {
    keyInsights.push(
      `This profiles more like a one-goal game than a comfortable win, with only ${roundedMargin.toFixed(1)} goals separating the sides.`
    );
  } else if (absMargin < 3.0) {
    keyInsights.push(
      `${expectedWinner} is projected to win by about ${roundedMargin.toFixed(1)} goals, which suggests control without total dominance.`
    );
  } else {
    keyInsights.push(
      `The projection points to a lopsided game if form holds, with a margin of roughly ${roundedMargin.toFixed(1)} goals.`
    );
  }

  // 4. Expected scoring environment
  const totalExpectedGoals = expectedScore.teamA + expectedScore.teamB;
  const dbAge = teamA.age || teamB.age;
  const nameAge = extractAgeFromTeamName(teamA.team_name) || extractAgeFromTeamName(teamB.team_name);
  const age = nameAge || dbAge;
  if (age) {
    if (age <= 11 && totalExpectedGoals > 5) {
      keyInsights.push(
        `Expect an open U${age} game script here, with roughly ${totalExpectedGoals.toFixed(1)} total goals projected.`
      );
    } else if (age >= 15 && totalExpectedGoals < 3) {
      keyInsights.push(
        `The scoring outlook is fairly muted for this age group, with only ${totalExpectedGoals.toFixed(1)} total goals projected.`
      );
    } else if (age) {
      keyInsights.push(
        `The scoring projection fits a typical U${age} match, with about ${totalExpectedGoals.toFixed(1)} total goals expected.`
      );
    }
  }

  // 5. Primary edge
  if (displayFactors.length > 0) {
    const topFactor = displayFactors[0];
    if (topFactor.advantage !== 'neutral') {
      if (topFactor.magnitude === 'significant') {
        keyInsights.push(`The biggest separator in this matchup is simple: ${topFactor.description}.`);
      } else if (displayFactors.length >= 2 && topFactor.magnitude === 'moderate') {
        keyInsights.push(`The clearest edge is: ${topFactor.description}.`);
      }
    }
  }

  // Reliability footer
  let reliabilityMessage = '';
  if (confidence === 'high') {
    if (minGamesPlayed >= 20) {
      reliabilityMessage =
        'High-confidence read: strong recent data and multiple matchup indicators all support the same side.';
    } else {
      reliabilityMessage = 'High-confidence read: the edge is clear, even if the dataset is not at its deepest.';
    }
  } else if (confidence === 'medium') {
    if (minGamesPlayed >= 15) {
      reliabilityMessage =
        'Balanced projection: there is a real edge here, but still enough uncertainty for the match to swing.';
    } else {
      reliabilityMessage =
        'Moderate-confidence read: enough signal to lean one way, but not enough to call it decisive.';
    }
  } else {
    if (minGamesPlayed < 10) {
      reliabilityMessage =
        'Lower-confidence read: limited recent data makes this projection more directional than definitive.';
    } else {
      reliabilityMessage =
        'Lower-confidence read: the teams are close enough on paper that the result could break either way.';
    }
  }

  const predictionQuality = {
    confidence,
    reliability: reliabilityMessage,
  };

  return {
    summary,
    factors: displayFactors,
    keyInsights,
    predictionQuality,
  };
}
