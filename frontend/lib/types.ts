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
}

/**
 * Ranking with team details (from rankings_view / state_rankings_view)
 * This matches the exact columns returned by the rankings views (RankingRow contract)
 * Matches canonical backend contract
 */
export interface RankingWithTeam {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  state: string | null; // alias for state_code
  age: number; // INTEGER age group number (e.g., 11)
  gender: 'M' | 'F' | 'B' | 'G'; // Backend returns single letter codes
  // Scores (backend contract)
  power_score_final: number;
  sos_norm: number;
  offense_norm: number | null;
  defense_norm: number | null;
  // Ranks (backend contract)
  rank_in_cohort_final: number; // National rank within age/gender cohort
  rank_in_state_final?: number; // State rank - ONLY in state_rankings_view
  // Record
  wins: number;
  losses: number;
  draws: number;
  games_played: number;
  win_percentage: number | null;
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
  national_power_score?: never;
  /** @deprecated Use sos_norm instead */
  strength_of_schedule?: never;
  /** @deprecated Use sos_norm instead */
  sos?: never;
  /** @deprecated Use sos_norm instead */
  sos_rank?: never;
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
  power_score_final: number | null; // ML Adjusted, final score
  sos_norm: number | null; // normalized 0–1 SOS index
  offense_norm: number | null;
  defense_norm: number | null;
  // Record
  wins: number;
  losses: number;
  draws: number;
  games_played: number; // Games used for rankings calculation (last 30)
  total_games_played?: number; // Total games in history (all games)
  total_wins?: number; // Total wins from all games
  total_losses?: number; // Total losses from all games
  total_draws?: number; // Total draws from all games
  win_percentage: number | null; // backend should calculate
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

/**
 * Scrape request for missing games
 * Used to track user-initiated requests to fetch missing game data
 */
export interface ScrapeRequest {
  id: string;
  team_id_master: string;
  team_name: string;
  provider_id: string | null;
  provider_team_id: string | null;
  game_date: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  request_type: string;
  requested_at: string;
  processed_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  games_found: number | null;
}

