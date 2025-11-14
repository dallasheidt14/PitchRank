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
}

export interface Ranking {
  team_id: string; // UUID - references teams.team_id_master
  national_rank: number | null;
  national_power_score: number;
  state_rank: number | null;
  games_played: number;
  wins: number;
  losses: number;
  draws: number;
  goals_for: number;
  goals_against: number;
  win_percentage: number | null;
  points_per_game: number | null;
  strength_of_schedule: number | null;
  global_power_score: number | null;
  last_game_date: string | null; // ISO date string
  last_calculated: string;
}

/**
 * Ranking with team details (from rankings_by_age_gender view)
 * This matches the exact columns returned by the rankings_by_age_gender view
 */
export interface RankingWithTeam {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  state_code: string | null;
  age_group: string;
  gender: 'Male' | 'Female';
  national_rank: number | null;
  state_rank: number | null;
  national_sos_rank: number | null;
  state_sos_rank: number | null;
  national_power_score: number;
  global_power_score: number | null;
  games_played: number;
  wins: number;
  losses: number;
  draws: number;
  win_percentage: number | null;
  strength_of_schedule: number | null;
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
 */
export interface GameWithTeams extends Game {
  home_team_name?: string;
  away_team_name?: string;
  home_team_club_name?: string | null;
  away_team_club_name?: string | null;
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

