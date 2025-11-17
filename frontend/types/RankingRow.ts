/**
 * RankingRow type - represents a single row in the rankings table
 * This type matches the structure returned by rankings_view and state_rankings_view
 * Matches canonical backend contract
 */

export interface RankingRow {
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
  // Metadata
  last_calculated: string | null; // ISO timestamp when rankings were last calculated
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

