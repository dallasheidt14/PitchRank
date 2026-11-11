import { beforeAll, expect, it } from 'vitest';
import baseline from '@/test/fixtures/compare-baseline.json';
import { predictMatch, warmMatchPredictorCalibration, type PredictionDiagnostics } from './matchPredictor';
import type { Game, TeamWithRanking } from './types';
import outcomeCalibration from '@/public/data/calibration/heuristic_outcome_calibration.json';

beforeAll(warmMatchPredictorCalibration);
it.each(baseline.cases)('preserves the complete pre-change forecast: $name', ({ teamA, teamB, games, prediction }) => {
  const diagnostics: PredictionDiagnostics = {};
  const actual = predictMatch(teamA as TeamWithRanking, teamB as TeamWithRanking, games as Game[], diagnostics);
  expect(actual).toEqual(prediction);
  expect(diagnostics.preOutcomeCalibration).toHaveLength(3);
  expect(diagnostics.preOutcomeCalibration!.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 12);
});

it.each(baseline.cases.filter(({ name }) => name.includes('mismatch')))(
  'captures A/draw/B probabilities before the final blend: $name',
  ({ teamA, teamB, games, prediction }) => {
    const diagnostics: PredictionDiagnostics = {};
    predictMatch(teamA as TeamWithRanking, teamB as TeamWithRanking, games as Game[], diagnostics);
    const { alpha, prior } = outcomeCalibration;
    const total = prior.team_a + prior.draw + prior.team_b;
    const neutralPrior = [
      (prior.team_a + prior.team_b) / (2 * total),
      prior.draw / total,
      (prior.team_a + prior.team_b) / (2 * total),
    ];
    const final = [prediction.winProbabilityA, prediction.drawProbability, prediction.winProbabilityB];
    // Invert the fixed blend from the pre-change forecast, independently of the diagnostic producer.
    final.forEach((probability, index) => {
      expect(diagnostics.preOutcomeCalibration![index]).toBeCloseTo(
        (probability - (1 - alpha) * neutralPrior[index]) / alpha,
        12
      );
    });
    expect(diagnostics.preOutcomeCalibration).not.toEqual(final);
  }
);
