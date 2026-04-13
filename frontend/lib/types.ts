/**
 * TypeScript interfaces for PitchRank data models
 * These match the Supabase database schema
 */

export interface Team {
  id: string; // UUID from teams table
  team_id_master: string; // UUID - primary identifier
  provider_team_id: string;
  provider_id: string | null;
  team_name: string;
  club_name: string | null;
  state: string | null;
  state_code: string | null; // 2-letter state code
  age_group: string; // 'u10', 'u11', etc.
  birth_year: number | null;
  gender: 'Male' | 'Female';
  created_at: string;
  updated_at: string;
  last_scraped_at: string | null;
}

export interface Game {
  id: string; // UUID
  home_team_master_id: string | null; // UUID reference to teams.team_id_master
  away_team_master_id: string | null;
  home_provider_id: string;
  away_provider_id: string;
  home_score: number | null;
  away_score: number | null;
  result: 'W' | 'L' | 'D' | 'U' | null; // W=Win, L=Loss, D=Draw, U=Unknown
  game_date: string; // ISO date string
  competition: string | null;
  division_name: string | null;
  event_name: string | null;
  venue: string | null;
  provider_id: string | null;
  source_url: string | null;
  scraped_at: string | null;
  created_at: string;
  ml_overperformance: number | null; // Layer 13 ML residual: actual - expected goal margin (home team perspective)
  is_excluded: boolean; // True for games excluded from rankings (e.g., futsal)
}

/**
 * Team with ranking data merged (TeamWithRanking contract)
 * Used when fetching a team with its current ranking information
 * This is the authoritative shape for team detail pages
 * Matches canonical backend contract
 */
export interface TeamWithRanking {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  state: string | null; // alias for state_code
  age: number | null; // INTEGER age group number (e.g., 11)
  gender: 'M' | 'F' | 'B' | 'G'; // Backend returns single letter codes
  // Correct Ranking Fields (backend contract)
  rank_in_cohort_final: number | null; // National rank within age/gender cohort
  rank_in_state_final?: number | null; // State rank - may not exist from rankings_view
  power_score_final: number | null; // Published Glicko-derived score
  glicko_rating?: number | null; // Underlying Glicko rating (mu)
  glicko_rd?: number | null; // Glicko rating deviation / uncertainty
  glicko_volatility?: number | null; // Glicko volatility parameter
  sos_norm: number | null; // normalized 0–1 SOS index (national normalization)
  sos_norm_state?: number | null; // normalized 0–1 SOS index (state normalization, for state rankings)
  sos_rank_national?: number | null; // SOS rank within (age, gender) cohort nationally
  sos_rank_state?: number | null; // SOS rank within (age, gender, state)
  offense_norm: number | null;
  defense_norm: number | null;
  same_age_games?: number | null;
  same_age_game_share?: number | null;
  same_age_unique_opponents?: number | null;
  same_age_top100_opp_count?: number | null;
  same_age_top500_opp_count?: number | null;
  same_age_avg_opp_power_adj?: number | null;
  repeat_opponent_share?: number | null;
  positive_ml_evidence_scale?: number | null;
  publication_cap_rank?: number | null;
  publication_cap_score?: number | null;
  // Record
  wins: number;
  losses: number;
  draws: number;
  games_played: number; // Games used for rankings calculation (last 30)
  last_scraped_at: string | null; // When team data was last scraped from provider
  total_games_played?: number; // Total games in history (all games)
  total_wins?: number; // Total wins from all games
  total_losses?: number; // Total losses from all games
  total_draws?: number; // Total draws from all games
  win_percentage: number | null; // backend should calculate
  // Optional predictive fields from team_predictive_view
  exp_margin?: number | null;
  exp_win_rate?: number | null;
  exp_goals_for?: number | null;
  exp_goals_against?: number | null;
  // Deprecated fields (do not use)
  /** @deprecated Use state instead */
  state_code?: never;
  /** @deprecated Use age instead */
  age_group?: never;
  /** @deprecated Use rank_in_cohort_final instead */
  national_rank?: never;
  /** @deprecated Use rank_in_state_final instead */
  state_rank?: never;
  /** @deprecated Use sos_norm instead */
  national_sos_rank?: never;
  /** @deprecated Use sos_norm instead */
  state_sos_rank?: never;
  /** @deprecated Use power_score_final instead */
  power_score?: never;
  /** @deprecated Use power_score_final instead */
  national_power_score?: never;
  /** @deprecated Use sos_norm instead */
  strength_of_schedule?: never;
  /** @deprecated Not in new views */
  last_game_date?: never;
  /** @deprecated Not in new views */
  goals_for?: never;
}

/**
 * Team trajectory data - performance over time
 * This aggregates game data to show team performance trends
 */
export interface TeamTrajectory {
  team_id: string;
  period_start: string; // ISO date string
  period_end: string; // ISO date string
  games_played: number;
  wins: number;
  losses: number;
  draws: number;
  goals_for: number;
  goals_against: number;
  win_percentage: number;
  avg_goals_for: number;
  avg_goals_against: number;
}

/**
 * Ranking history snapshot - weekly rank position for charting
 */
export interface RankHistoryPoint {
  snapshot_date: string; // ISO date string (Monday)
  rank: number;
}

/**
 * Game with team names (for display purposes)
 * Extends Game interface which already includes ml_overperformance
 */
export interface GameWithTeams extends Game {
  home_team_name?: string;
  away_team_name?: string;
  home_team_club_name?: string | null;
  away_team_club_name?: string | null;
  was_overperformed?: boolean | null; // Deprecated: use ml_overperformance from Game interface
}

export interface GameExplainability {
  team_id: string;
  game_uuid: string;
  game_id: string;
  opp_id: string;
  game_date: string | null;
  gf: number | null;
  ga: number | null;
  team_mu: number | null;
  team_sigma: number | null;
  opp_mu: number | null;
  opp_sigma: number | null;
  expected_outcome: number | null;
  actual_outcome: number | null;
  outcome_surprise: number | null;
  g_factor: number | null;
  recency_weight: number | null;
  rating_contribution: number | null;
  off_residual: number | null;
  def_residual: number | null;
  last_calculated?: string;
  created_at?: string;
}
