/**
 * Team Persona Label Generator
 *
 * Determines team archetype based on performance against different opponent tiers:
 * - Giant Killer: Wins against higher-ranked teams
 * - Flat Track Bully: Dominates weak teams, struggles vs top teams
 * - Gatekeeper: Beats bottom teams, rarely beats top
 * - Wildcard: No clear pattern
 */

import type { InsightInputData, PersonaInsight } from "./types";

/**
 * Analyzes performance against opponents by tier
 */
function analyzePerformanceByTier(
  games: InsightInputData["games"],
  teamId: string,
  teamRank: number | null
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
    const oppRank = game.opponent_rank;

    if (teamScore === null || oppScore === null) continue;

    const won = teamScore > oppScore;
    const goalDiff = teamScore - oppScore;

    // Track big wins/losses (3+ goal margin)
    if (goalDiff >= 3) bigWins++;
    if (goalDiff <= -3) bigLosses++;

    if (oppRank === null || teamRank === null) {
      // If we don't have rank data, use power score
      const oppPower = game.opponent_power_score;
      if (oppPower !== null) {
        // We'll treat it as similar if we can't determine
        totalVsSimilar++;
        if (won) winsVsSimilar++;
      }
      continue;
    }

    // Categorize opponent by rank
    // Higher ranked = lower number
    // "Similar" is within 20 ranks
    const rankDiff = teamRank - oppRank;

    if (rankDiff > 20) {
      // Opponent is ranked higher (better)
      totalVsHigherRanked++;
      if (won) winsVsHigherRanked++;
    } else if (rankDiff < -20) {
      // Opponent is ranked lower (worse)
      totalVsLowerRanked++;
      if (won) winsVsLowerRanked++;
    } else {
      // Similar rank
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

  // Giant Killer: Strong performance against higher-ranked teams (40%+ win rate)
  if (hasEnoughTopGames && winRateVsTop >= 0.4 && winsVsHigherRanked >= 2) {
    return {
      label: "Giant Killer",
      explanation: `Won ${winsVsHigherRanked} of ${totalVsHigherRanked} games against higher-ranked opponents. This team rises to the occasion against elite competition and shouldn't be underestimated in big matchups.`,
    };
  }

  // Flat Track Bully: Dominates lower teams but struggles against top
  if (
    hasEnoughTopGames &&
    hasEnoughBottomGames &&
    winRateVsTop < 0.25 &&
    winRateVsBottom > 0.8
  ) {
    return {
      label: "Flat Track Bully",
      explanation: `Dominant against weaker competition (${Math.round(winRateVsBottom * 100)}% win rate vs lower-ranked teams) but struggles against elite opponents (${Math.round(winRateVsTop * 100)}% vs top teams). Their record may be inflated by soft scheduling.`,
    };
  }

  // Gatekeeper: Beats bottom teams reliably, competitive but rarely beats top
  if (
    hasEnoughBottomGames &&
    winRateVsBottom > 0.65 &&
    (winRateVsTop < 0.3 || !hasEnoughTopGames)
  ) {
    return {
      label: "Gatekeeper",
      explanation: `A reliable gatekeeper who consistently handles lower-ranked opponents (${Math.round(winRateVsBottom * 100)}% win rate) but hasn't broken through against top-tier teams. They define the line between contenders and pretenders.`,
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
 * Generate the Persona insight
 */
export function generatePersonaInsight(data: InsightInputData): PersonaInsight {
  const { team, ranking, games } = data;

  const stats = analyzePerformanceByTier(
    games,
    team.team_id_master,
    ranking.rank_in_cohort_final
  );

  const { label, explanation } = determinePersona(stats);

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
    },
  };
}
