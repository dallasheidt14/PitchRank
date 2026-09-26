import type { TeamWithRanking } from './types';

/**
 * Keep prediction math on the pre-age-scale numeric contract.
 * Unversioned payloads are legacy data and may safely use power_score_final.
 * Versioned payloads must carry the explicit compatibility score.
 */
export function predictionPowerScore(team: TeamWithRanking): number {
  if (team.prediction_power_score != null) return team.prediction_power_score;
  if (team.power_score_scale_version != null) {
    throw new Error(
      `Prediction input is missing prediction_power_score for scale ${team.power_score_scale_version}`
    );
  }
  return team.power_score_final ?? 0.5;
}
