/**
 * Analytics Event Payload Types
 * Type definitions for GA4 custom event payloads
 * Note: These types use `| null` to match database types (TeamWithRanking, etc.)
 */

/**
 * Payload for team-related events
 */
export interface TeamEventPayload {
  team_id_master: string;
  team_name: string;
  club_name?: string | null;
  state?: string | null;
  age?: number | null;
  gender?: 'M' | 'F' | 'B' | 'G' | null;
  rank_in_cohort_final?: number | null;
  rank_in_state_final?: number | null;
  power_score_final?: number | null;
}

/**
 * Payload for filter events
 */
export interface FilterEventPayload {
  region: string;
  age_group: string;
  gender: string;
}

/**
 * Payload for sort events
 */
export interface SortEventPayload {
  column: string;
  direction: 'asc' | 'desc';
  region?: string | null;
  age_group?: string | null;
  gender?: string | null;
}

/**
 * Payload for search events
 */
export interface SearchEventPayload {
  query: string;
  results_count: number;
}

/**
 * Payload for comparison events
 */
export interface CompareEventPayload {
  team_count: number;
  team_ids?: string[];
  team_names?: string[];
}

/**
 * Payload for prediction events
 */
export interface PredictionEventPayload {
  team_a_id: string;
  team_a_name: string;
  team_b_id: string;
  team_b_name: string;
  win_probability_a?: number | null;
  win_probability_b?: number | null;
  draw_probability?: number | null;
  predicted_winner?: string | null;
}

/**
 * Payload for chart view events
 */
export interface ChartViewEventPayload {
  chart_type: 'momentum' | 'trajectory';
  team_id_master: string;
  team_name?: string | null;
}

/**
 * Payload for missing game form events
 */
export interface MissingGameEventPayload {
  team_id_master: string;
  team_name: string;
  game_date?: string | null;
}
