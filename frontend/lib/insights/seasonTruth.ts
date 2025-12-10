/**
 * Season Truth Summary Generator
 *
 * Computes a narrative evaluation of a team's season based on:
 * - PowerScore vs actual rank
 * - SOS percentile
 * - Goal differential variance
 * - Win/loss clustering
 */

import type { InsightInputData, SeasonTruthInsight } from "./types";

/**
 * Determines if a team is underranked, overranked, or accurately ranked
 */
function analyzeRankVsPowerScore(
  rank: number | null,
  powerScore: number | null,
  cohortStats: { totalTeams: number; percentile: number }
): "underranked" | "overranked" | "accurate" {
  if (rank === null || powerScore === null) return "accurate";

  const rankPercentile = ((cohortStats.totalTeams - rank) / cohortStats.totalTeams) * 100;
  const powerPercentile = cohortStats.percentile;

  // If power percentile is much higher than rank percentile, team is underranked
  const diff = powerPercentile - rankPercentile;

  if (diff > 15) return "underranked";
  if (diff < -15) return "overranked";
  return "accurate";
}

/**
 * Analyzes consistency patterns from game results
 */
function analyzeConsistencyPattern(
  games: InsightInputData["games"],
  teamId: string
): string {
  if (games.length < 3) return "limited data available";

  const results: ("W" | "L" | "D")[] = [];
  const goalDiffs: number[] = [];

  for (const game of games) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && oppScore !== null) {
      goalDiffs.push(teamScore - oppScore);
      if (teamScore > oppScore) results.push("W");
      else if (teamScore < oppScore) results.push("L");
      else results.push("D");
    }
  }

  if (results.length < 3) return "limited game data";

  // Calculate streaks
  let maxWinStreak = 0;
  let maxLossStreak = 0;
  let currentWinStreak = 0;
  let currentLossStreak = 0;

  for (const result of results) {
    if (result === "W") {
      currentWinStreak++;
      currentLossStreak = 0;
      maxWinStreak = Math.max(maxWinStreak, currentWinStreak);
    } else if (result === "L") {
      currentLossStreak++;
      currentWinStreak = 0;
      maxLossStreak = Math.max(maxLossStreak, currentLossStreak);
    } else {
      currentWinStreak = 0;
      currentLossStreak = 0;
    }
  }

  // Calculate goal differential standard deviation
  const avgGD = goalDiffs.reduce((a, b) => a + b, 0) / goalDiffs.length;
  const variance =
    goalDiffs.reduce((sum, gd) => sum + Math.pow(gd - avgGD, 2), 0) /
    goalDiffs.length;
  const stdDev = Math.sqrt(variance);

  if (stdDev < 1.5 && maxLossStreak <= 2) {
    return "consistent performer with minimal variance";
  } else if (stdDev > 3 || maxLossStreak >= 4) {
    return "inconsistency against mid-tier opponents";
  } else if (maxWinStreak >= 5) {
    return "strong momentum with extended winning runs";
  } else if (maxLossStreak >= 3) {
    return "struggles to recover from defeats";
  }

  return "balanced performance with typical variance";
}

/**
 * Generates the Season Truth insight
 */
export function generateSeasonTruth(data: InsightInputData): SeasonTruthInsight {
  const { team, ranking, games, cohortStats } = data;

  const rankVsPowerScore = analyzeRankVsPowerScore(
    ranking.rank_in_cohort_final,
    ranking.power_score_final,
    cohortStats
  );

  const sosPercentile = ranking.sos_norm ? Math.round(ranking.sos_norm * 100) : 50;
  const consistencyNote = analyzeConsistencyPattern(games, team.team_id_master);

  // Generate narrative text
  let narrative = "";
  const rank = ranking.rank_in_cohort_final;
  const powerPercentile = cohortStats.percentile;

  if (rank !== null) {
    narrative = `This team is ranked #${rank} nationally`;

    if (rankVsPowerScore === "underranked") {
      const projectedRank = Math.max(
        1,
        Math.round(cohortStats.totalTeams * (1 - powerPercentile / 100))
      );
      narrative += `, but based on strength-of-schedule and power metrics, they project closer to a Top ${Math.ceil(projectedRank / 5) * 5} team`;
    } else if (rankVsPowerScore === "overranked") {
      narrative += `, though their underlying metrics suggest they may be slightly overperforming their talent level`;
    } else {
      narrative += `, which aligns well with their underlying performance metrics`;
    }

    narrative += ".";

    // Add SOS context
    if (sosPercentile >= 75) {
      narrative += ` They've faced one of the toughest schedules in their cohort (top ${100 - sosPercentile}% SOS).`;
    } else if (sosPercentile <= 25) {
      narrative += ` Their schedule has been relatively soft (bottom ${sosPercentile}% SOS), which may inflate their record.`;
    }

    // Add consistency note
    if (consistencyNote !== "limited game data" && consistencyNote !== "limited data available") {
      narrative += ` Their biggest ${consistencyNote.includes("inconsistency") || consistencyNote.includes("struggles") ? "vulnerability" : "strength"} this season has been ${consistencyNote}.`;
    }
  } else {
    narrative = `This team has limited ranking data available. `;
    if (ranking.games_played > 0) {
      narrative += `With a ${ranking.wins}-${ranking.losses}${ranking.draws > 0 ? `-${ranking.draws}` : ""} record across ${ranking.games_played} games, `;
      narrative += consistencyNote !== "limited game data"
        ? `they've shown ${consistencyNote}.`
        : "more games will reveal their true standing.";
    }
  }

  return {
    type: "season_truth",
    text: narrative,
    details: {
      rankVsPowerScore,
      sosPercentile,
      consistencyNote,
    },
  };
}
