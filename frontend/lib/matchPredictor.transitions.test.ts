// @vitest-environment node
import { beforeAll, describe, expect, it, vi } from 'vitest';
import cases from '../test/compare-transition-cases.json';
import {
  calculateSparseDrawBoost,
  getAdaptiveWeights,
  predictMatch,
  warmMatchPredictorCalibration,
} from './matchPredictor';
import type { Game, TeamWithRanking } from './types';

// Exercise built-in calibration defaults separately from checked-in calibration.
vi.mock('./calibrationLoader', () => ({ loadCalibrationJson: async () => null }));
beforeAll(warmMatchPredictorCalibration);

describe('continuous adaptive weights', () => {
  it('preserves endpoint weights, normalized totals and orientation', () => {
    expect(getAdaptiveWeights(0, 0.5, 0.5, 0.5, 0.5).weights).toEqual({
      POWER_SCORE: 0.5,
      SOS: 0.18,
      RECENT_FORM: 0.28,
      MATCHUP: 0.04,
    });
    expect(getAdaptiveWeights(0.08, 0.5, 0.5, 0.5, 0.5).weights.POWER_SCORE).toBe(0.85);
    for (let gap = 0; gap <= 0.2; gap += 0.001) {
      const forward = getAdaptiveWeights(gap, 0.65, 0.4, 0.6, 0.5).weights;
      expect(getAdaptiveWeights(-gap, 0.4, 0.65, 0.5, 0.6).weights).toEqual(forward);
      expect(Object.values(forward).reduce((a, b) => a + b, 0)).toBeCloseTo(1, 12);
      expect(forward.POWER_SCORE).toBeGreaterThanOrEqual(0.5);
      expect(forward.POWER_SCORE).toBeLessThanOrEqual(0.85);
    }
  });

  it.each([
    [0.05, 0.5, 0.5, 0.5, 0.5],
    [0.08, 0.5, 0.5, 0.5, 0.5],
    [0.01, 0.65, 0.5, 0.5, 0.5],
    [0.01, 0.5, 0.5, 0.65, 0.5],
    [0.01, 0.625, 0.5, 0.625, 0.5],
    // All offense/defense gaps equal: mismatch scores .4 and .6.
    [0, 0.5 + 0.4 / (0.5 / 0.18 + 1), 0.5, 0.5 + 0.4 / (0.5 / 0.18 + 1), 0.5],
    // Asymmetry is saturated here: .5 * gap / .18 + .15 = .6.
    [0, 0.662, 0.5, 0.662, 0.5],
  ])('has no jump around the former boundary %j', (power, oa, ob, da, db) => {
    for (let input = 0; input < 5; input++) {
      const left = [power, oa, ob, da, db] as [number, number, number, number, number];
      const right = [...left] as typeof left;
      left[input] -= 1e-8;
      right[input] += 1e-8;
      const a = getAdaptiveWeights(...left).weights;
      const b = getAdaptiveWeights(...right).weights;
      for (const key of Object.keys(a) as Array<keyof typeof a>) expect(Math.abs(a[key] - b[key])).toBeLessThan(1e-6);
    }
  });
});

describe('sparse draw adjustment', () => {
  it('tapers to zero at six points, symmetrically, preserving the maximum and cap', () => {
    expect(calculateSparseDrawBoost(0, 0.18)).toBe(0.05);
    expect(calculateSparseDrawBoost(0, 0.23)).toBeCloseTo(0.01, 12);
    expect(calculateSparseDrawBoost(0, 0.25)).toBe(0);
    expect(calculateSparseDrawBoost(0.06, 0.18)).toBe(0);
    expect(calculateSparseDrawBoost(0.08, 0.18)).toBe(0);
    expect(calculateSparseDrawBoost(0.06 - 1e-8, 0.18)).toBeLessThan(1e-8);
    expect(calculateSparseDrawBoost(0.03, 0.18)).toBeCloseTo(0.025, 12);
    expect(calculateSparseDrawBoost(-0.03, 0.18)).toBe(calculateSparseDrawBoost(0.03, 0.18));
  });
});

describe('full-predictor threshold regressions (synthetic inputs)', () => {
  it.each(cases)('improving $field no longer causes the audited drop', (c) => {
    const a = c.a as unknown as TeamWithRanking;
    const b = c.b as unknown as TeamWithRanking;
    const games = c.games as unknown as Game[];
    const clock = Date.parse('2026-11-13T22:38:46.070Z');
    const before = predictMatch(a, b, games, undefined, clock);
    const improved = { ...a, [c.field]: c.improvedValue };
    const after = predictMatch(improved, b, games, undefined, clock);
    expect(after.winProbabilityA).toBeGreaterThanOrEqual(before.winProbabilityA);
    expect(after.expectedMargin).toBeGreaterThanOrEqual(before.expectedMargin);
    expect(predictMatch(improved, b, games, undefined, clock)).toEqual(after);
    const reverse = predictMatch(b, improved, games, undefined, clock);
    expect(reverse.winProbabilityB).toBeCloseTo(after.winProbabilityA, 12);
    expect(reverse.expectedMargin).toBeCloseTo(-after.expectedMargin, 12);
    expect(reverse.blowout4PlusProbability).toBeCloseTo(after.blowout4PlusProbability!, 12);
    expect(after.winProbabilityA! + after.winProbabilityB! + after.drawProbability!).toBeCloseTo(1, 12);
  });
});
