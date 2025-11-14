/**
 * TeamPredictive type - represents predictive match result data
 * This type matches the structure returned by team_predictive_view
 * Predictive fields are computed by Layer 13 ML enhancer
 */

export interface TeamPredictive {
  team_id_master: string;
  
  // Predictive fields (always exist, but may be null in DB)
  exp_margin: number | null; // Expected margin of victory (goal units)
  exp_win_rate: number | null; // Expected win probability (0.0-1.0)
  
  // Predictive fields (optional - may not be stored)
  exp_goals_for?: number | null; // Expected goals for
  exp_goals_against?: number | null; // Expected goals against
  
  // Helpful extras for context
  power_score_final: number;
  sos_norm: number;
  offense_norm: number | null;
  defense_norm: number | null;
}

