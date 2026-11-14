import { afterAll, beforeAll, expect, it, vi } from 'vitest';
import baseline from '@/test/fixtures/compare-baseline.json';
import current from '@/test/fixtures/compare-live-v8-predictions.json';
import previous from '@/test/fixtures/compare-live-v7-predictions.json';
import {
  predictMatch,
  warmMatchPredictorCalibration,
  type MatchPrediction,
  type PredictionDiagnostics,
} from './matchPredictor';
import type { Game, TeamWithRanking } from './types';
import outcomeCalibration from '@/public/data/calibration/heuristic_outcome_calibration.json';

beforeAll(async () => {
  await warmMatchPredictorCalibration();
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(current.referenceTime));
});
afterAll(() => vi.useRealTimers());
const predictions = current.predictions as Record<string, MatchPrediction>;
it.each(baseline.cases)('reproduces the complete v8 forecast: $name', ({ name, teamA, teamB, games }) => {
  const diagnostics: PredictionDiagnostics = {};
  const actual = predictMatch(teamA as TeamWithRanking, teamB as TeamWithRanking, games as Game[], diagnostics);
  expect(actual).toEqual(predictions[name]);
  expect(diagnostics.preOutcomeCalibration).toHaveLength(3);
  expect(diagnostics.preOutcomeCalibration!.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 12);
});

it.each(baseline.cases.filter(({ name }) => name.includes('mismatch')))(
  'captures A/draw/B probabilities before the final blend: $name',
  ({ name, teamA, teamB, games }) => {
    const diagnostics: PredictionDiagnostics = {};
    predictMatch(teamA as TeamWithRanking, teamB as TeamWithRanking, games as Game[], diagnostics);
    const { alpha, prior } = outcomeCalibration;
    const total = prior.team_a + prior.draw + prior.team_b;
    const neutralPrior = [
      (prior.team_a + prior.team_b) / (2 * total),
      prior.draw / total,
      (prior.team_a + prior.team_b) / (2 * total),
    ];
    const prediction = predictions[name];
    // Large-gap endpoints retain the complete previous-version outputs.
    expect(prediction).toEqual((previous.predictions as Record<string, MatchPrediction>)[name]);
    const final = [prediction.winProbabilityA, prediction.drawProbability!, prediction.winProbabilityB];
    // Invert the fixed blend independently of the diagnostic producer.
    final.forEach((probability, index) => {
      expect(diagnostics.preOutcomeCalibration![index]).toBeCloseTo(
        (probability - (1 - alpha) * neutralPrior[index]) / alpha,
        12
      );
    });
    expect(diagnostics.preOutcomeCalibration).not.toEqual(final);
  }
);
