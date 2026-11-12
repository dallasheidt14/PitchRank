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
import { MATCH_FORM_SAMPLE_SIZE } from './matchEvidence';
import { presentMatchup } from './matchupPresentation';

type ExplanationMagnitude = 'significant' | 'moderate' | 'minimal';
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
  counterFactors?: Explanation[];
  // Summary
  summary: string;

  // When neither team is favored, balance both sides before neutral context.
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
 * These are normalized rating scores, not ranks in a percentile distribution.
 */
function formatRatingScore(value: number): string {
  return String(Math.round(value * 100));
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
  const strongerPower = powerDiff > 0 ? (teamA.power_score_final ?? 0.5) : (teamB.power_score_final ?? 0.5);
  const weakerPower = powerDiff > 0 ? (teamB.power_score_final ?? 0.5) : (teamA.power_score_final ?? 0.5);
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
  const strongerScore = formatRatingScore(sosDiff > 0 ? (teamA.sos_norm ?? 0.5) : (teamB.sos_norm ?? 0.5));
  const weakerScore = formatRatingScore(sosDiff > 0 ? (teamB.sos_norm ?? 0.5) : (teamA.sos_norm ?? 0.5));
  const description = `${strongerSOS} has the higher schedule-strength score (${strongerScore} vs ${weakerScore} out of 100), reflecting tougher rated opposition`;

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
    description = `${betterTeam} has a +${betterForm.toFixed(1)} weighted goal differential across up to ${MATCH_FORM_SAMPLE_SIZE} latest results`;
  }
  // Case 2: Worse team is struggling badly (the gap comes from their collapse)
  else if (magnitude === 'significant' && worseForm < -2.0) {
    description = `${worseTeam} is struggling badly (${worseForm.toFixed(1)} goal diff recently), giving ${betterTeam} a momentum edge`;
  }
  // Case 3: Better team has positive momentum
  else if (betterForm > 0.5) {
    description = `${betterTeam} has positive recent form (+${betterForm.toFixed(1)} weighted goal differential across up to ${MATCH_FORM_SAMPLE_SIZE} latest results)`;
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
 * (i.e., normalized attack score > normalized defense score)
 */
function explainOffensiveMatchup(teamA: TeamWithRanking, teamB: TeamWithRanking): Explanation | null {
  const offenseA = teamA.offense_norm ?? 0.5;
  const defenseA = teamA.defense_norm ?? 0.5;
  const offenseB = teamB.offense_norm ?? 0.5;
  const defenseB = teamB.defense_norm ?? 0.5;

  // Calculate both offensive matchup advantages
  // Positive means offense has advantage over opposing defense
  const matchupA = offenseA - defenseB; // Team A offense vs Team B defense
  const matchupB = offenseB - defenseA; // Team B offense vs Team A defense
  // Equal attacking matchups do not favor whichever team was selected first.
  if (Math.abs(matchupA - matchupB) < 1e-9) return null;

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
    const offScore = formatRatingScore(offenseA);
    const defScore = formatRatingScore(defenseB);
    description = `${teamA.team_name}'s attack score (${offScore}/100) is above ${teamB.team_name}'s defense score (${defScore}/100)`;
    advantage = 'team_a';
  } else {
    const offScore = formatRatingScore(offenseB);
    const defScore = formatRatingScore(defenseA);
    description = `${teamB.team_name}'s attack score (${offScore}/100) is above ${teamA.team_name}'s defense score (${defScore}/100)`;
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
  prediction: MatchPrediction
): Explanation | null {
  const view = presentMatchup(prediction, teamA.team_name, teamB.team_name);
  if (!view.closelyMatched && !view.drawMostLikely) return null;
  return {
    factor: 'close_match',
    advantage: 'neutral',
    magnitude: 'minimal',
    description: view.drawMostLikely
      ? 'A draw has a higher estimated chance than either team winning'
      : 'The teams have similar estimated chances of winning',
    icon: '⚖️',
    score: view.drawMostLikely ? 1.6 : 1.5,
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
  if (absMargin < 0.05) return null;
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

type CommonOpponentObservation = {
  advantage: 'team_a' | 'team_b';
  metric: 'points' | 'margin';
  amount: number;
  description: string;
};

function commonOpponentObservation(
  teamA: TeamWithRanking,
  teamB: TeamWithRanking,
  commonOpponents?: MatchPrediction['commonOpponents'],
  commonOpponentSignal?: number
): CommonOpponentObservation | null {
  if (!commonOpponents || commonOpponents.sharedOpponents < 2) return null;
  const signal = commonOpponentSignal ?? 0;
  if (Math.abs(signal) < 0.025) return null;
  const advantage: 'team_a' | 'team_b' = signal > 0 ? 'team_a' : 'team_b';
  const favoredTeam = signal > 0 ? teamA.team_name : teamB.team_name;
  const direction = signal > 0 ? 1 : -1;
  const margin = commonOpponents.avgMarginDiff * direction;
  const points = commonOpponents.pointsPerGameDiff * direction;
  // The combined signal can favor points while goal difference favors the other team.
  // Cite only an aligned statistic that will not round to a zero advantage.
  const metric = points >= 0.8 || margin < 0.05 ? 'points' : 'margin';
  const amount = metric === 'points' ? points : margin;
  if (amount < 0.05) return null;
  const description =
    metric === 'points'
      ? `${favoredTeam} has taken about ${amount.toFixed(1)} more points per game against ${commonOpponents.sharedOpponents} shared opponents`
      : `${favoredTeam} has an average goal-difference advantage of ${amount.toFixed(1)} per game against ${commonOpponents.sharedOpponents} shared opponents`;
  return { advantage, metric, amount, description };
}

function explainCommonOpponents(
  commonOpponents: MatchPrediction['commonOpponents'],
  commonOpponentSignal: number | undefined,
  observation: CommonOpponentObservation | null
): Explanation | null {
  if (!commonOpponents || !observation) return null;
  const significant = observation.metric === 'points' ? observation.amount >= 0.9 : observation.amount >= 1.1;
  const moderate = observation.metric === 'points' ? observation.amount >= 0.55 : observation.amount >= 0.6;

  let magnitude: ExplanationMagnitude;
  if (commonOpponents.sharedOpponents >= 4 && commonOpponents.reliability >= 0.45 && significant) {
    magnitude = 'significant';
  } else if (moderate) {
    magnitude = 'moderate';
  } else {
    magnitude = 'minimal';
  }

  if (magnitude === 'minimal') return null;

  return {
    factor: 'common_opponents',
    advantage: observation.advantage,
    magnitude,
    description: `Shared-opponent results: ${observation.description}`,
    icon: 'vs',
    score:
      Math.abs(commonOpponentSignal ?? 0) * 12 +
      commonOpponents.sharedOpponents * 0.18 +
      commonOpponents.reliability * 0.6,
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
  const { components, formA, formB, confidence, expectedMargin, h2h, commonOpponents } = prediction;
  const sharedObservation = commonOpponentObservation(teamA, teamB, commonOpponents, components.commonOpponentSignal);

  // Generate all possible explanations
  const allExplanations: (Explanation | null)[] = [
    explainHeadToHead(teamA, teamB, h2h), // H2H first - highly predictive
    explainCommonOpponents(commonOpponents, components.commonOpponentSignal, sharedObservation),
    explainPowerScore(teamA, teamB, components.powerDiff),
    explainSOS(teamA, teamB, components.sosDiff),
    explainRecentForm(teamA, teamB, formA, formB, components.formDiffRaw),
    explainOffensiveMatchup(teamA, teamB),
    explainCloseMatch(teamA, teamB, prediction),
  ];

  // Filter out nulls
  const allFactors = allExplanations.filter((e): e is Explanation => e !== null);

  // Separate factors by who they favor
  const presentation = presentMatchup(prediction, teamA.team_name, teamB.team_name);
  const favoredSide = presentation.favorite;

  const factors = allFactors
    .filter((f) => f.advantage === favoredSide || f.advantage === 'neutral')
    .sort((a, b) => b.score - a.score)
    .slice(0, 4);

  const sorted = [...allFactors].sort((a, b) => b.score - a.score);
  const displayFactors = favoredSide
    ? factors
    : [
        ...(['team_a', 'team_b'] as const).flatMap((side) => sorted.filter((f) => f.advantage === side).slice(0, 1)),
        ...sorted.filter((f) => f.advantage === 'neutral').slice(0, 2),
      ];
  const counterFactors = favoredSide
    ? sorted.filter((f) => f.advantage !== favoredSide && f.advantage !== 'neutral').slice(0, 2)
    : [];

  // Generate summary
  const summary = presentation.summary;

  // Generate user-facing key insights
  const keyInsights: string[] = [];

  if (sharedObservation) keyInsights.push(`${sharedObservation.description}.`);

  // 3. Margin interpretation
  const absMargin = Math.abs(expectedMargin);
  const roundedMargin = Math.round(absMargin * 10) / 10;
  const expectedWinner = expectedMargin > 0 ? teamA.team_name : teamB.team_name;

  if (absMargin < 0.5) {
    keyInsights.push(
      `The projected margin is almost flat (${roundedMargin.toFixed(1)} goals), so the teams look closely matched.`
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
  const totalExpectedGoals = prediction.expectedGoals
    ? prediction.expectedGoals.teamA + prediction.expectedGoals.teamB
    : null;
  // teams.age_group first; the name is a fallback only. A name states a birth
  // year and therefore means a different cohort after every Aug 1 rollover,
  // whereas age_group is rolled deliberately. This insight is rendered as
  // "U${age}" to the reader, so a stale name here shows the wrong age group.
  const dbAge = teamA.age || teamB.age;
  const nameAge = extractAgeFromTeamName(teamA.team_name) || extractAgeFromTeamName(teamB.team_name);
  const age = dbAge || nameAge;
  if (age && totalExpectedGoals != null) {
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
        keyInsights.push(`One supporting indicator is: ${topFactor.description}.`);
      } else if (displayFactors.length >= 2 && topFactor.magnitude === 'moderate') {
        keyInsights.push(`Another supporting indicator is: ${topFactor.description}.`);
      }
    }
  }

  // Preserve the response contract without claiming calibrated reliability.
  const predictionQuality = {
    confidence,
    reliability: 'Outcome probabilities are model estimates. Evidence details are shown separately.',
  };

  return {
    summary,
    factors: displayFactors,
    counterFactors,
    keyInsights,
    predictionQuality,
  };
}
