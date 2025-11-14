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
  national_rank: number | null;
  state_rank?: number | null; // Optional, only present in state rankings
  national_sos_rank: number | null;
  state_sos_rank?: number | null;
  national_power_score: number;
  global_power_score: number | null;
  power_score_final: number; // ML-adjusted power score (ML > global > adj > national)
  games_played: number;
  wins: number;
  losses: number;
  draws: number;
  win_percentage: number | null;
  strength_of_schedule: number | null;
  sos?: number | null; // Raw SOS value (0.0-1.0)
  sos_norm?: number | null; // Normalized SOS (percentile/z-score within cohort)
  // Additional fields that may be used for display
  power_score?: number; // Alias for power_score_final in state rankings (backward compatibility)
}

