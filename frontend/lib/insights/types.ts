/**
 * Types for Team Insight Engine
 * Premium-only scouting-style insights computed from team data
 */

/**
 * Form signal derived from v53e perf_centered metric
 * Indicates whether team is over/underperforming expectations
 */
export type FormSignal =
  | "hot_streak"
  | "overperforming"
  | "meeting_expectations"
  | "underperforming"
  | "cold_streak";

/**
 * Rank trajectory derived from v53e perf_centered
 * Indicates whether team's rank is likely to rise, fall, or stay stable
 * based on recent performance vs expectations
 *
 * IMPORTANT: v53e already incorporates SOS into the final rank.
 * We should NOT use SOS to question the rank - instead we use
 * perf_centered (recent form) to predict rank movement.
 */
export type RankTrajectory = "rising" | "falling" | "stable";

/**
 * Season Truth Summary - narrative evaluation of team's season
 * Uses v53e perf_centered to predict rank trajectory
 */
export interface SeasonTruthInsight {
  type: "season_truth";
  text: string;
  details: {
    /** Rank trajectory based on recent form (perf_centered) */
    rankTrajectory: RankTrajectory;
    sosPercentile: number;
    consistencyNote: string;
    /** Form signal from v53e perf_centered - shows current momentum */
    formSignal: FormSignal;
    /** Raw perf_centered value from v53e (-0.5 to +0.5) */
    perfCentered: number | null;
    /** Offensive strength percentile (0-1) from v53e */
    offenseNorm: number | null;
    /** Defensive strength percentile (0-1) from v53e */
    defenseNorm: number | null;
  };
}

/**
 * Consistency Score - measure of team reliability
 */
export interface ConsistencyInsight {
  type: "consistency_score";
  score: number; // 0-100
  label: "very reliable" | "moderately reliable" | "unpredictable" | "highly volatile";
  details: {
    goalDifferentialStdDev: number;
    streakFragmentation: number;
    powerScoreVolatility: number;
  };
}

/**
 * Persona Label - team archetype based on performance patterns
 */
export interface PersonaInsight {
  type: "persona";
  label: "Giant Killer" | "Flat Track Bully" | "Gatekeeper" | "Wildcard";
  explanation: string;
  details: {
    winsVsHigherRanked: number;
    totalVsHigherRanked: number;
    winsVsLowerRanked: number;
    totalVsLowerRanked: number;
    winRateVsTop: number;
    winRateVsBottom: number;
  };
}

/**
 * Union type for all insights
 */
export type TeamInsight = SeasonTruthInsight | ConsistencyInsight | PersonaInsight;

/**
 * Full insights response for a team
 */
export interface TeamInsightsResponse {
  teamId: string;
  teamName: string;
  insights: TeamInsight[];
  generatedAt: string;
}

/**
 * Input data needed for generating insights
 */
export interface InsightInputData {
  team: {
    team_id_master: string;
    team_name: string;
    state: string | null;
    age: number | null;
    gender: "M" | "F" | "B" | "G";
  };
  ranking: {
    rank_in_cohort_final: number | null;
    power_score_final: number | null;
    sos_norm: number | null;
    wins: number;
    losses: number;
    draws: number;
    games_played: number;
    rank_change_7d: number | null;
    rank_change_30d: number | null;
    /** Offensive strength from v53e Layer 9 (0-1 percentile) */
    offense_norm: number | null;
    /** Defensive strength from v53e Layer 9 (0-1 percentile) */
    defense_norm: number | null;
    /** Form/momentum signal from v53e Layer 6 (-0.5 to +0.5) */
    perf_centered: number | null;
  };
  games: Array<{
    game_date: string;
    home_team_master_id: string | null;
    away_team_master_id: string | null;
    home_score: number | null;
    away_score: number | null;
    opponent_rank: number | null;
    opponent_power_score: number | null;
  }>;
  rankingHistory: Array<{
    snapshot_date: string;
    rank_in_cohort: number;
    power_score_final: number | null;
  }>;
  cohortStats: {
    totalTeams: number;
    medianPowerScore: number;
    percentile: number;
  };
}
