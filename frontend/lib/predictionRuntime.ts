/** Public configuration only: no teams, histories, users or credentials. */
import { MATCH_PREDICTION_VERSION } from './matchPredictionService';
import { matchCalibrationSnapshot, predictMatch, warmMatchPredictorCalibration } from './matchPredictor';
import type { TeamWithRanking } from './types';

export async function predictionRuntime() {
  await warmMatchPredictorCalibration();
  const calibration = matchCalibrationSnapshot();
  const probes = [10, 12, 19].flatMap((age) =>
    [0, 0.02, 0.3].map((gap) => {
      const teamA = {
        team_id_master: '11111111-1111-4111-8111-111111111111',
        team_name: 'Runtime probe A',
        age,
        gender: 'M',
        power_score_final: 0.5 + gap,
        sos_norm: 0.6,
        offense_norm: 0.6,
        defense_norm: 0.5,
        glicko_rating: 1500 + gap * 500,
        glicko_rd: 100,
        wins: 8,
        losses: 4,
        draws: 2,
        games_played: 14,
      } as TeamWithRanking;
      const teamB = {
        ...teamA,
        team_id_master: '22222222-2222-4222-8222-222222222222',
        team_name: 'Runtime probe B',
        power_score_final: 0.5,
        glicko_rating: 1500,
      };
      return { teamA, teamB, prediction: predictMatch(teamA, teamB, []) };
    })
  );
  return {
    schema_version: 1 as const,
    predictor_version: MATCH_PREDICTION_VERSION,
    deployment_revision: process.env.VERCEL_GIT_COMMIT_SHA ?? null,
    observed_at: new Date().toISOString(),
    calibration,
    probes,
  };
}
export type PredictionRuntime = Awaited<ReturnType<typeof predictionRuntime>>;
