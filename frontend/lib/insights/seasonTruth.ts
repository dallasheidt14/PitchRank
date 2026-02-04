/**
 * Season Truth Summary Generator
 *
 * Computes a narrative evaluation of a team's season based on v53e metrics:
 * - Raw performance (off_norm + def_norm) vs SOS-adjusted power score
 * - Form signal from perf_centered (overperforming/underperforming)
 * - SOS percentile context
 * - Win/loss clustering patterns
 *
 * IMPORTANT: This version fixes the previous circular logic that compared
 * rank percentile to power percentile (which are nearly identical by design).
 * Instead, we now compare raw offensive/defensive performance to the
 * SOS-boosted final power score to identify true under/overranked teams.
 */

import type { InsightInputData, SeasonTruthInsight, FormSignal } from "./types";

/**
 * v53e Power Score formula reference:
 * power_score = (0.25 * off_norm + 0.25 * def_norm + 0.50 * sos_norm + 0.15 * perf_centered) / 1.075
 *
 * This means:
 * - Raw talent = off_norm + def_norm (50% of formula, equally weighted)
 * - Schedule boost = sos_norm (50% of formula)
 * - Momentum = perf_centered (15% blended)
 *
 * A team is "SOS-carried" if their raw talent << final power (hard schedule inflates rank)
 * A team is "SOS-deflated" if their raw talent >> final power (easy schedule deflates rank)
 */

/**
 * Determines if a team is underranked, overranked, or accurately ranked
 * by comparing raw performance (OFF+DEF) to SOS contribution
 */
function analyzeRankVsPowerScore(
  ranking: InsightInputData["ranking"]
): "underranked" | "overranked" | "accurate" {
  const { offense_norm, defense_norm, sos_norm, power_score_final } = ranking;

  // Need all v53e metrics for proper analysis
  if (
    offense_norm === null ||
    defense_norm === null ||
    sos_norm === null ||
    power_score_final === null
  ) {
    return "accurate";
  }

  // Raw talent = average of offense and defense (each is 0-1 percentile)
  const rawTalent = (offense_norm + defense_norm) / 2;

  // SOS contribution to power score
  // In v53e: power = 0.25*off + 0.25*def + 0.50*sos (normalized)
  // So SOS "boost" = how much higher power is vs what raw talent alone would give
  // If SOS > rawTalent, schedule is harder than avg and team gets boost
  // If SOS < rawTalent, schedule is easier than avg and team gets penalty

  const sosBoost = sos_norm - rawTalent;

  // Thresholds for determining if the SOS significantly affects perception
  // 0.10 = 10 percentile points difference
  const UNDERRANKED_THRESHOLD = 0.08; // Team playing hard schedule, raw talent high
  const OVERRANKED_THRESHOLD = -0.08; // Team playing easy schedule, raw talent low

  if (sosBoost > UNDERRANKED_THRESHOLD && rawTalent > 0.55) {
    // Team has good raw talent AND plays a hard schedule
    // Their rank might be lower than their true ability
    return "underranked";
  }

  if (sosBoost < OVERRANKED_THRESHOLD && rawTalent < 0.50) {
    // Team has below-average raw talent AND plays an easy schedule
    // Their rank might be higher than their true ability
    return "overranked";
  }

  return "accurate";
}

/**
 * Converts v53e perf_centered to a human-readable form signal
 * perf_centered range: [-0.5, +0.5]
 */
function getFormSignal(perfCentered: number | null): FormSignal {
  if (perfCentered === null) return "meeting_expectations";

  if (perfCentered >= 0.30) return "hot_streak";
  if (perfCentered >= 0.12) return "overperforming";
  if (perfCentered <= -0.30) return "cold_streak";
  if (perfCentered <= -0.12) return "underperforming";
  return "meeting_expectations";
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

  // v53e caps goal diff at +/- 6, we should too
  const GOAL_DIFF_CAP = 6;

  for (const game of games) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && oppScore !== null) {
      // Cap goal differential to match v53e
      const rawDiff = teamScore - oppScore;
      const cappedDiff = Math.max(-GOAL_DIFF_CAP, Math.min(GOAL_DIFF_CAP, rawDiff));
      goalDiffs.push(cappedDiff);

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
 * Generates form narrative based on perf_centered
 */
function getFormNarrative(formSignal: FormSignal, perfCentered: number | null): string {
  if (perfCentered === null) return "";

  switch (formSignal) {
    case "hot_streak":
      return "They're currently on a hot streak, significantly exceeding performance expectations in recent games.";
    case "overperforming":
      return "Recent form shows them overperforming expectations, winning games by larger margins than predicted.";
    case "cold_streak":
      return "They're in a cold stretch, underperforming their talent level in recent matchups.";
    case "underperforming":
      return "Recent results suggest they're leaving points on the table, performing below their expected level.";
    default:
      return "";
  }
}

/**
 * Generates the Season Truth insight
 */
export function generateSeasonTruth(data: InsightInputData): SeasonTruthInsight {
  const { team, ranking, games, cohortStats } = data;

  const rankVsPowerScore = analyzeRankVsPowerScore(ranking);
  const sosPercentile = ranking.sos_norm ? Math.round(ranking.sos_norm * 100) : 50;
  const consistencyNote = analyzeConsistencyPattern(games, team.team_id_master);
  const formSignal = getFormSignal(ranking.perf_centered);

  // Generate narrative text
  let narrative = "";
  const rank = ranking.rank_in_cohort_final;

  if (rank !== null) {
    narrative = `This team is ranked #${rank} nationally`;

    // Explain rank assessment using v53e logic
    if (rankVsPowerScore === "underranked") {
      narrative += `. Their raw offensive/defensive metrics suggest they're better than their current ranking`;
      if (sosPercentile >= 70) {
        narrative += ` - a brutal ${sosPercentile}th percentile strength of schedule has suppressed their position`;
      }
    } else if (rankVsPowerScore === "overranked") {
      narrative += `, though their underlying talent metrics suggest the ranking may be inflated`;
      if (sosPercentile <= 35) {
        narrative += ` by a softer-than-average schedule (${sosPercentile}th percentile SOS)`;
      }
    } else {
      narrative += `, which aligns well with their underlying performance metrics`;
    }

    narrative += ".";

    // Add form/momentum signal (the key new insight from perf_centered)
    const formNarrative = getFormNarrative(formSignal, ranking.perf_centered);
    if (formNarrative) {
      narrative += ` ${formNarrative}`;
    }

    // Add SOS context if not already mentioned
    if (rankVsPowerScore === "accurate") {
      if (sosPercentile >= 75) {
        narrative += ` They've faced one of the toughest schedules in their cohort (top ${100 - sosPercentile}% SOS).`;
      } else if (sosPercentile <= 25) {
        narrative += ` Their schedule has been relatively soft (bottom ${sosPercentile}% SOS).`;
      }
    }

    // Add consistency note
    if (
      consistencyNote !== "limited game data" &&
      consistencyNote !== "limited data available"
    ) {
      const isNegative =
        consistencyNote.includes("inconsistency") ||
        consistencyNote.includes("struggles");
      narrative += ` Their biggest ${isNegative ? "vulnerability" : "strength"} this season has been ${consistencyNote}.`;
    }
  } else {
    narrative = `This team has limited ranking data available. `;
    if (ranking.games_played > 0) {
      narrative += `With a ${ranking.wins}-${ranking.losses}${ranking.draws > 0 ? `-${ranking.draws}` : ""} record across ${ranking.games_played} games, `;
      narrative +=
        consistencyNote !== "limited game data"
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
      formSignal,
      perfCentered: ranking.perf_centered,
      offenseNorm: ranking.offense_norm,
      defenseNorm: ranking.defense_norm,
    },
  };
}
