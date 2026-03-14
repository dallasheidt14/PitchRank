/**
 * Team Persona Label Generator
 *
 * Determines team archetype based on performance against different opponent tiers:
 * - Giant Killer: Wins against higher-ranked teams
 * - Flat Track Bully: Dominates weak teams, struggles vs top teams
 * - Gatekeeper: Beats bottom teams, rarely beats top
 * - Wildcard: No clear pattern
 *
 * ALIGNED WITH v53e:
 * - Uses power score difference (0-1 scale) instead of fixed rank thresholds
 * - This is cohort-size independent (works for 50 or 500 team cohorts)
 * - Power score is the normalized metric v53e uses for team strength
 */

import type { InsightInputData, PersonaInsight } from "./types";

/**
 * Base power score difference threshold for opponent categorization (in powerscore_adj space, [0-1])
 *
 * 0.08 ≈ meaningful strength gap in the pre-anchor [0,1] range.
 * For context: In a 100-team cohort, this is roughly 8 percentile points.
 *
 * IMPORTANT: power_score_final is anchor-scaled by age (U10 max=0.40, U18 max=1.00).
 * A fixed threshold in final space would be too coarse for younger age groups.
 * We scale this by the team's age anchor so the threshold represents the same
 * relative strength gap regardless of age group.
 */
const BASE_POWER_DIFF_THRESHOLD = 0.08;

/**
 * Age-to-anchor mapping matching v53e Layer 11
 * Younger age groups have compressed power_score_final ranges
 */
const AGE_TO_ANCHOR: Record<number, number> = {
  10: 0.40,
  11: 0.475,
  12: 0.55,
  13: 0.625,
  14: 0.70,
  15: 0.775,
  16: 0.85,
  17: 0.925,
  18: 1.0,
  19: 1.0,
};

/**
 * Big win/loss threshold - goal differential that indicates dominant/dominated result
 * Matches v53e's treatment of decisive margins
 */
const BIG_MARGIN_THRESHOLD = 3;

/**
 * Analyzes performance against opponents by tier using power score
 * Threshold is scaled by age anchor to maintain consistent sensitivity across age groups
 */
function analyzePerformanceByTier(
  games: InsightInputData["games"],
  teamId: string,
  teamPower: number | null,
  powerDiffThreshold: number
): {
  winsVsHigherRanked: number;
  totalVsHigherRanked: number;
  winsVsLowerRanked: number;
  totalVsLowerRanked: number;
  winsVsSimilar: number;
  totalVsSimilar: number;
  bigWins: number;
  bigLosses: number;
} {
  let winsVsHigherRanked = 0;
  let totalVsHigherRanked = 0;
  let winsVsLowerRanked = 0;
  let totalVsLowerRanked = 0;
  let winsVsSimilar = 0;
  let totalVsSimilar = 0;
  let bigWins = 0;
  let bigLosses = 0;

  for (const game of games) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;
    const oppPower = game.opponent_power_score;

    if (teamScore === null || oppScore === null) continue;

    const won = teamScore > oppScore;
    const goalDiff = teamScore - oppScore;

    // Track big wins/losses (3+ goal margin)
    if (goalDiff >= BIG_MARGIN_THRESHOLD) bigWins++;
    if (goalDiff <= -BIG_MARGIN_THRESHOLD) bigLosses++;

    // Categorize opponent by power score difference (cohort-size independent)
    if (teamPower === null || oppPower === null) {
      // Fall back to similar if we can't determine power difference
      totalVsSimilar++;
      if (won) winsVsSimilar++;
      continue;
    }

    // Power difference: negative = opponent stronger, positive = opponent weaker
    const powerDiff = teamPower - oppPower;

    if (powerDiff < -powerDiffThreshold) {
      // Opponent has meaningfully higher power score (stronger)
      totalVsHigherRanked++;
      if (won) winsVsHigherRanked++;
    } else if (powerDiff > powerDiffThreshold) {
      // Opponent has meaningfully lower power score (weaker)
      totalVsLowerRanked++;
      if (won) winsVsLowerRanked++;
    } else {
      // Similar power level (within threshold)
      totalVsSimilar++;
      if (won) winsVsSimilar++;
    }
  }

  return {
    winsVsHigherRanked,
    totalVsHigherRanked,
    winsVsLowerRanked,
    totalVsLowerRanked,
    winsVsSimilar,
    totalVsSimilar,
    bigWins,
    bigLosses,
  };
}

/**
 * Determine persona based on performance patterns
 */
function determinePersona(stats: ReturnType<typeof analyzePerformanceByTier>): {
  label: PersonaInsight["label"];
  explanation: string;
} {
  const {
    winsVsHigherRanked,
    totalVsHigherRanked,
    winsVsLowerRanked,
    totalVsLowerRanked,
    bigWins,
    bigLosses,
  } = stats;

  // Calculate win rates
  const winRateVsTop =
    totalVsHigherRanked > 0 ? winsVsHigherRanked / totalVsHigherRanked : 0;
  const winRateVsBottom =
    totalVsLowerRanked > 0 ? winsVsLowerRanked / totalVsLowerRanked : 0;

  // Minimum games threshold for reliable patterns
  const hasEnoughTopGames = totalVsHigherRanked >= 2;
  const hasEnoughBottomGames = totalVsLowerRanked >= 2;

  // Giant Killer: Strong performance against stronger teams (40%+ win rate)
  if (hasEnoughTopGames && winRateVsTop >= 0.4 && winsVsHigherRanked >= 2) {
    return {
      label: "Giant Killer",
      explanation: `Won ${winsVsHigherRanked} of ${totalVsHigherRanked} games against stronger opponents (by power score). This team rises to the occasion against elite competition and shouldn't be underestimated in big matchups.`,
    };
  }

  // Flat Track Bully: Dominates weaker teams but struggles against stronger
  if (
    hasEnoughTopGames &&
    hasEnoughBottomGames &&
    winRateVsTop < 0.25 &&
    winRateVsBottom > 0.8
  ) {
    return {
      label: "Flat Track Bully",
      explanation: `Dominant against weaker competition (${Math.round(winRateVsBottom * 100)}% win rate vs lower-powered teams) but struggles against elite opponents (${Math.round(winRateVsTop * 100)}% vs stronger teams). Their record may be inflated by favorable scheduling.`,
    };
  }

  // Gatekeeper: Beats weaker teams reliably, competitive but rarely beats stronger
  if (
    hasEnoughBottomGames &&
    winRateVsBottom > 0.65 &&
    (winRateVsTop < 0.3 || !hasEnoughTopGames)
  ) {
    return {
      label: "Gatekeeper",
      explanation: `A reliable gatekeeper who consistently handles weaker opponents (${Math.round(winRateVsBottom * 100)}% win rate) but hasn't broken through against top-tier teams. They define the line between contenders and pretenders.`,
    };
  }

  // Wildcard: No clear pattern or mixed results
  // Check for volatility indicators
  const totalGames = totalVsHigherRanked + totalVsLowerRanked;
  const hasVolatileResults = bigWins >= 2 && bigLosses >= 2;

  if (hasVolatileResults) {
    return {
      label: "Wildcard",
      explanation: `Unpredictable results with ${bigWins} blowout wins and ${bigLosses} heavy defeats. On any given day, this team can beat anyone or lose to anyone. Their floor-to-ceiling range makes them dangerous but unreliable.`,
    };
  }

  // Default Wildcard for insufficient data or genuinely mixed patterns
  if (totalGames < 4) {
    return {
      label: "Wildcard",
      explanation: `With limited games against varied competition, it's difficult to establish a clear pattern. This team's true identity is still emerging.`,
    };
  }

  return {
    label: "Wildcard",
    explanation: `This team defies easy categorization with mixed results across different opponent tiers. They're neither consistently dominant nor consistently vulnerable, making them a true wildcard in any matchup.`,
  };
}

/**
 * Finds the most impressive win: highest-ranked opponent beaten by the largest margin.
 * Returns a string like "Beat #3 opponent 4-1" or null if no notable wins.
 */
function findSignatureResult(
  games: InsightInputData["games"],
  teamId: string
): string | null {
  let bestScore = -Infinity;
  let bestResult: string | null = null;

  for (const game of games) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;
    const oppRank = game.opponent_rank;

    if (teamScore === null || oppScore === null) continue;
    if (teamScore <= oppScore) continue; // Only wins
    if (oppRank === null) continue;

    // Score: prioritize beating high-ranked opponents, tie-break by margin
    // Lower opponent rank = more impressive, so invert it
    const margin = teamScore - oppScore;
    const impressiveness = (1 / oppRank) * 1000 + margin;

    if (impressiveness > bestScore) {
      bestScore = impressiveness;
      bestResult = `Beat #${oppRank} opponent ${teamScore}-${oppScore}`;
    }
  }

  return bestResult;
}

/**
 * Generate the Persona insight
 */
export function generatePersonaInsight(data: InsightInputData): PersonaInsight {
  const { team, ranking, games } = data;

  // Scale power diff threshold by age anchor to maintain consistent sensitivity
  // across age groups. power_score_final range varies: U10=[0,0.40], U18=[0,1.0]
  // Without scaling, U10 teams almost always get "Wildcard" because 0.08 is 20%
  // of their entire range vs only 8% for U18.
  const anchor = (team.age !== null ? AGE_TO_ANCHOR[team.age] : null) ?? 1.0;
  const scaledThreshold = BASE_POWER_DIFF_THRESHOLD * anchor;

  // Use power score for tier analysis (cohort-size independent)
  const stats = analyzePerformanceByTier(
    games,
    team.team_id_master,
    ranking.power_score_final,
    scaledThreshold
  );

  const { label, explanation } = determinePersona(stats);
  const signatureResult = findSignatureResult(games, team.team_id_master);

  const winRateVsTop =
    stats.totalVsHigherRanked > 0
      ? Math.round((stats.winsVsHigherRanked / stats.totalVsHigherRanked) * 100)
      : 0;
  const winRateVsBottom =
    stats.totalVsLowerRanked > 0
      ? Math.round((stats.winsVsLowerRanked / stats.totalVsLowerRanked) * 100)
      : 0;

  return {
    type: "persona",
    label,
    explanation,
    details: {
      winsVsHigherRanked: stats.winsVsHigherRanked,
      totalVsHigherRanked: stats.totalVsHigherRanked,
      winsVsLowerRanked: stats.winsVsLowerRanked,
      totalVsLowerRanked: stats.totalVsLowerRanked,
      winRateVsTop,
      winRateVsBottom,
      signatureResult,
    },
  };
}
