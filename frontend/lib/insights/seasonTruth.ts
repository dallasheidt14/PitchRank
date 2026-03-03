/**
 * Season Truth Summary Generator
 *
 * Computes a narrative evaluation of a team's season based on v53e metrics:
 * - Rank trajectory from perf_centered (predicting rank movement)
 * - Form signal from perf_centered (overperforming/underperforming)
 * - Play style from offense_norm/defense_norm
 * - Cohort context (percentile within age/gender)
 * - Rank velocity from ranking history
 * - Current concrete W/L streak
 * - SOS percentile context (informational only)
 * - Win/loss clustering patterns
 *
 * IMPORTANT: v53e ALREADY incorporates SOS (50% of formula) into the final rank.
 * The rank v53e produces IS the "true rank" after adjusting for schedule.
 * We should NOT use SOS to question the rank - that would contradict v53e's purpose.
 *
 * Instead, we use perf_centered (recent form) to predict TRAJECTORY:
 * - High perf_centered = overperforming = rank likely to RISE
 * - Low perf_centered = underperforming = rank likely to FALL
 * - Neutral = rank is STABLE
 */

import type { InsightInputData, SeasonTruthInsight, FormSignal, RankTrajectory, PlayStyle } from "./types";

/**
 * Determines rank trajectory based on recent form (perf_centered)
 *
 * perf_centered range: [-0.5, +0.5]
 * - Positive values = team overperforming expectations = rank likely to rise
 * - Negative values = team underperforming expectations = rank likely to fall
 * - Near zero = performing as expected = rank stable
 *
 * This is the correct approach because:
 * - v53e already factored in SOS to calculate the current rank
 * - perf_centered reflects RECENT performance vs expectations
 * - If a team is consistently overperforming, their rank WILL improve
 * - If a team is consistently underperforming, their rank WILL drop
 */
function analyzeRankTrajectory(
  ranking: InsightInputData["ranking"]
): RankTrajectory {
  const { perf_centered } = ranking;

  // Without perf_centered data, we can't predict trajectory
  if (perf_centered === null) {
    return "stable";
  }

  // Thresholds based on perf_centered range [-0.5, +0.5]
  // 0.10 is a meaningful deviation from expectations
  const RISING_THRESHOLD = 0.10;
  const FALLING_THRESHOLD = -0.10;

  if (perf_centered >= RISING_THRESHOLD) {
    // Team overperforming → rank likely to improve
    return "rising";
  }

  if (perf_centered <= FALLING_THRESHOLD) {
    // Team underperforming → rank likely to drop
    return "falling";
  }

  return "stable";
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
 * Determines play style from offense_norm and defense_norm (both 0-1 percentile)
 */
function determinePlayStyle(
  offenseNorm: number | null,
  defenseNorm: number | null
): PlayStyle | null {
  if (offenseNorm === null || defenseNorm === null) return null;

  if (offenseNorm >= 0.70 && defenseNorm >= 0.70) return "Two-Way Powerhouse";
  if (offenseNorm >= 0.65 && defenseNorm < 0.45) return "High-Octane Attack";
  if (defenseNorm >= 0.65 && offenseNorm < 0.45) return "Defensive Wall";
  if (offenseNorm < 0.35 && defenseNorm < 0.35) return "Rebuilding";
  return "Balanced Squad";
}

/**
 * Computes the current W/L/D streak from most recent games
 * Games are ordered most-recent-first
 */
function getCurrentStreak(
  games: InsightInputData["games"],
  teamId: string
): string | null {
  if (games.length === 0) return null;

  let streakType: "W" | "L" | "D" | null = null;
  let streakCount = 0;

  for (const game of games) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore === null || oppScore === null) continue;

    let result: "W" | "L" | "D";
    if (teamScore > oppScore) result = "W";
    else if (teamScore < oppScore) result = "L";
    else result = "D";

    if (streakType === null) {
      streakType = result;
      streakCount = 1;
    } else if (result === streakType) {
      streakCount++;
    } else {
      break;
    }
  }

  if (streakType === null || streakCount < 2) return null;
  return `${streakType}${streakCount}`;
}

/**
 * Computes rank velocity from ranking history
 * Returns a human-readable string like "Climbed 42 spots in 8 weeks"
 */
function computeRankVelocity(
  rankingHistory: InsightInputData["rankingHistory"]
): string | null {
  if (rankingHistory.length < 4) return null;

  // History is ordered most-recent-first
  const latest = rankingHistory[0];
  const oldest = rankingHistory[rankingHistory.length - 1];

  const rankChange = oldest.rank_in_cohort - latest.rank_in_cohort; // positive = improved
  const daySpan = Math.round(
    (new Date(latest.snapshot_date).getTime() - new Date(oldest.snapshot_date).getTime()) /
    (1000 * 60 * 60 * 24)
  );

  if (daySpan < 14) return null;

  const weeks = Math.round(daySpan / 7);

  // Check for sustained top-10 hold
  if (latest.rank_in_cohort <= 10) {
    const allTopTen = rankingHistory.every(h => h.rank_in_cohort <= 10);
    if (allTopTen && rankingHistory.length >= 8) {
      return `Held a top-10 position for ${weeks}+ weeks`;
    }
  }

  // Meaningful movement threshold: at least 5 spots
  if (Math.abs(rankChange) < 5) return null;

  if (rankChange > 0) {
    return `Climbed ${rankChange} spots over the last ${weeks} weeks`;
  } else {
    return `Dropped ${Math.abs(rankChange)} spots over the last ${weeks} weeks`;
  }
}

/**
 * Builds a cohort context string like "12th of 347 Boys U14 teams (top 3%)"
 */
function buildCohortContext(
  ranking: InsightInputData["ranking"],
  team: InsightInputData["team"],
  cohortStats: InsightInputData["cohortStats"]
): string | null {
  const rank = ranking.rank_in_cohort_final;
  if (rank === null || cohortStats.totalTeams <= 1) return null;

  const genderLabel = team.gender === "M" || team.gender === "B" ? "Boys" : "Girls";
  const ageLabel = team.age ? `U${team.age}` : null;

  const cohortLabel = ageLabel ? `${genderLabel} ${ageLabel}` : genderLabel;
  const pct = cohortStats.percentile;

  return `#${rank} of ${cohortStats.totalTeams} ${cohortLabel} teams (top ${100 - pct}%)`;
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
 * Generates trajectory narrative based on perf_centered
 */
function getTrajectoryNarrative(trajectory: RankTrajectory, perfCentered: number | null): string {
  if (perfCentered === null) return "";

  switch (trajectory) {
    case "rising":
      return "Based on recent form, this team's rank is likely to improve in upcoming updates.";
    case "falling":
      return "Recent results suggest this team's rank may drop in upcoming updates.";
    default:
      return "";
  }
}

/**
 * Returns a play style narrative fragment
 */
function getPlayStyleNarrative(playStyle: PlayStyle | null): string {
  switch (playStyle) {
    case "Two-Way Powerhouse":
      return "They're a two-way powerhouse, elite on both sides of the ball.";
    case "High-Octane Attack":
      return "They win through a high-octane attack, outscoring opponents rather than shutting them down.";
    case "Defensive Wall":
      return "They grind out results with a defensive-first identity, conceding very little.";
    case "Rebuilding":
      return "Both their offensive and defensive metrics are below average, suggesting a team in transition.";
    default:
      return "";
  }
}

/**
 * Generates the Season Truth insight
 */
export function generateSeasonTruth(data: InsightInputData): SeasonTruthInsight {
  const { team, ranking, games, cohortStats, rankingHistory } = data;

  const rankTrajectory = analyzeRankTrajectory(ranking);
  const sosPercentile = ranking.sos_norm ? Math.round(ranking.sos_norm * 100) : 50;
  const consistencyNote = analyzeConsistencyPattern(games, team.team_id_master);
  const formSignal = getFormSignal(ranking.perf_centered);
  const playStyle = determinePlayStyle(ranking.offense_norm, ranking.defense_norm);
  const currentStreak = getCurrentStreak(games, team.team_id_master);
  const rankVelocity = computeRankVelocity(rankingHistory);
  const cohortContext = buildCohortContext(ranking, team, cohortStats);

  // Generate narrative text
  let narrative = "";
  const rank = ranking.rank_in_cohort_final;

  if (rank !== null) {
    // Lead with cohort context if available for a specific, grounded opener
    if (cohortContext) {
      narrative = `Ranked ${cohortContext}`;
    } else {
      narrative = `This team is ranked #${rank} nationally`;
    }

    // Add SOS context (informational only - v53e already factored this into the rank)
    if (sosPercentile >= 75) {
      narrative += `, earned against elite competition (${sosPercentile}th percentile SOS)`;
    } else if (sosPercentile <= 25) {
      narrative += ` against a lighter schedule (${sosPercentile}th percentile SOS)`;
    }

    narrative += ".";

    // Add play style identity
    const playStyleNarrative = getPlayStyleNarrative(playStyle);
    if (playStyleNarrative) {
      narrative += ` ${playStyleNarrative}`;
    }

    // Add concrete streak
    if (currentStreak) {
      const streakType = currentStreak[0];
      const streakCount = currentStreak.slice(1);
      if (streakType === "W") {
        narrative += ` Currently riding a ${streakCount}-game winning streak.`;
      } else if (streakType === "L") {
        narrative += ` Currently winless in their last ${streakCount} games.`;
      } else {
        narrative += ` Have drawn their last ${streakCount} games.`;
      }
    }

    // Add form/momentum signal (the key insight from perf_centered)
    const formNarrative = getFormNarrative(formSignal, ranking.perf_centered);
    if (formNarrative) {
      narrative += ` ${formNarrative}`;
    }

    // Add rank velocity if meaningful
    if (rankVelocity) {
      narrative += ` ${rankVelocity}.`;
    }

    // Add trajectory prediction based on recent form
    const trajectoryNarrative = getTrajectoryNarrative(rankTrajectory, ranking.perf_centered);
    if (trajectoryNarrative) {
      narrative += ` ${trajectoryNarrative}`;
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
      rankTrajectory,
      sosPercentile,
      consistencyNote,
      formSignal,
      perfCentered: ranking.perf_centered,
      offenseNorm: ranking.offense_norm,
      defenseNorm: ranking.defense_norm,
      playStyle,
      currentStreak,
      rankVelocity,
      cohortContext,
    },
  };
}
