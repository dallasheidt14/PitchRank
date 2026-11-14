// @vitest-environment node
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import cases from '../test/compare-transition-cases.json';
import { matchCalibrationSnapshot, predictMatch, warmMatchPredictorCalibration } from './matchPredictor';
import { MATCH_PREDICTION_VERSION } from './matchPredictionService';
import type { Game, TeamWithRanking } from './types';

vi.mock('./calibrationLoader', () => ({ loadCalibrationJson: async () => null }));
beforeAll(warmMatchPredictorCalibration);
const root = path.basename(process.cwd()) === 'frontend' ? process.cwd() : path.join(process.cwd(), 'frontend');
const clock = '2026-11-13T22:38:46.070Z';
const fixture = cases[0];
const a = fixture.a as unknown as TeamWithRanking;
const b = fixture.b as unknown as TeamWithRanking;
const games = fixture.games as unknown as Game[];
function context() {
  return {
    teamAInput: a,
    teamBInput: b,
    frozenEvidence: { games },
    calibration: matchCalibrationSnapshot(),
    predictorVersion: MATCH_PREDICTION_VERSION,
  };
}
function run(cases: unknown[]) {
  return JSON.parse(
    execFileSync(process.execPath, ['--import', 'tsx', path.join(root, 'scripts/run-ml-share-research.ts')], {
      input: JSON.stringify({ verifiedProductionRuntime: true, cases }),
      encoding: 'utf8',
      windowsHide: true,
      timeout: 30000,
      env: { ...process.env, NODE_OPTIONS: '--conditions=react-server' },
      stdio: ['pipe', 'pipe', 'pipe'],
    })
  );
}

describe('isolated extra ML share experiment', () => {
  it('reproduces the baseline, changes only the extra share term and keeps risk outputs', () => {
    const prediction = predictMatch(a, b, games, undefined, Date.parse(clock));
    const first = { context: context(), prediction, reference_time: clock };
    const [result, reverse, repeated] = run([
      first,
      {
        context: { ...context(), teamAInput: b, teamBInput: a },
        prediction: predictMatch(b, a, games, undefined, Date.parse(clock)),
        reference_time: clock,
      },
      first,
    ]);
    expect(repeated).toEqual(result);
    expect(result.receipt.aa_parity).toBe(true);
    expect(result.receipt.experiment).toBe('ml_share');
    expect(result.production_promotion).toBe(false);
    expect(result.variants['1']).toEqual(prediction);
    expect(result.baseline_origin).toBe('verified_frozen_prediction');
    const off = result.variants['0'];
    expect(off.components).toEqual(prediction.components);
    expect(off.formA).toBe(prediction.formA);
    expect(off.formB).toBe(prediction.formB);
    expect(off.expectedGoals.teamA + off.expectedGoals.teamB).toBeCloseTo(
      prediction.expectedGoals!.teamA + prediction.expectedGoals!.teamB,
      12
    );
    expect(off.winProbabilityA).not.toBe(prediction.winProbabilityA);
    const allMlRemoved = predictMatch(
      a,
      b,
      games.map((g) => ({ ...g, ml_overperformance: null })),
      undefined,
      Date.parse(clock)
    );
    expect(off.components.compositeDiff).not.toBe(allMlRemoved.components.compositeDiff);
    expect(off.expectedGoals.teamA + off.expectedGoals.teamB).not.toBeCloseTo(
      allMlRemoved.expectedGoals!.teamA + allMlRemoved.expectedGoals!.teamB,
      8
    );
    for (const arm of ['0', '1']) {
      const p = result.variants[arm];
      expect(p.winProbabilityA + p.winProbabilityB + p.drawProbability).toBeCloseTo(1, 12);
      expect(p.winProbabilityA).toBeCloseTo(reverse.variants[arm].winProbabilityB, 12);
      expect(p.expectedMargin).toBeCloseTo(-reverse.variants[arm].expectedMargin, 12);
      expect(p.blowout4PlusProbability).toBeCloseTo(reverse.variants[arm].blowout4PlusProbability, 12);
      expect(p.blowout4PlusProbability).toBeGreaterThan(0);
      expect(p.expectedAbsoluteGoalDifference).toBeGreaterThan(0);
    }
  });

  it('labels reconstruction separately and rejects wrong or malformed reference predictions', () => {
    const c = { context: { ...context(), predictorVersion: 'historical-input-version' }, reference_time: clock };
    const [result] = run([c]);
    expect(result.baseline_origin).toBe('reconstructed_from_frozen_inputs');
    expect(result.input_predictor_version).toBe('historical-input-version');
    expect(result.research_predictor_version).toBe(MATCH_PREDICTION_VERSION);
    for (const prediction of [null, {}, { ...result.prediction, winProbabilityA: 0 }]) {
      expect(() => run([{ ...c, prediction }])).toThrow();
    }
  }, 15000);

  it('resets both experiments when reusing one runtime', () => {
    const script = `import { createSosRuntime } from './lib/sosResearch.ts';
      import { readFileSync } from 'node:fs';
      const c = JSON.parse(readFileSync(0, 'utf8'));
      const r = await createSosRuntime(c.calibration, process.cwd(), {verifiedProductionRuntime:true});
      try {
        const before = r.capture(c, '${clock}');
        const ml = r.compareMlShare(c, '${clock}');
        const after = r.capture(c, '${clock}');
        const mlAgain = r.compareMlShare(c, '${clock}');
        console.log(JSON.stringify({before,ml,after,mlAgain}));
      } finally { await r.close(); }`;
    const result = JSON.parse(
      execFileSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', script], {
        cwd: root,
        input: JSON.stringify(context()),
        encoding: 'utf8',
        windowsHide: true,
        timeout: 30000,
        env: { ...process.env, NODE_OPTIONS: '--conditions=react-server' },
      })
    );
    expect(result.after).toEqual(result.before);
    expect(result.mlAgain).toEqual(result.ml);
    expect(result.ml.variants['1']).toEqual(result.before.variants['1']);
  });
});
