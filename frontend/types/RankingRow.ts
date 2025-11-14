/**
 * RankingRow type - represents a single row in the rankings table
 * This type matches the structure returned by rankings_view and state_rankings_view
 */

export interface RankingRow {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  state_code: string | null;
  age_group: string;
  gender: 'Male' | 'Female';
  // Scores (backend contract)
  power_score_final: number;
  sos_norm: number;
  // Ranks (backend contract)
  national_rank: number | null;
  state_rank: number | null;
  national_sos_rank: number | null;
  state_sos_rank: number | null;
  // Record
  wins: number;
  losses: number;
  draws: number;
  games_played: number;
  win_percentage: number | null;
  goals_for?: number;
  // Deprecated fields (do not use)
  /** @deprecated Use power_score_final instead */
  national_power_score?: never;
  /** @deprecated Use sos_norm instead */
  strength_of_schedule?: never;
  /** @deprecated Use sos_norm instead */
  sos?: never;
  /** @deprecated Use sos_norm instead */
  sos_rank?: never;
}

