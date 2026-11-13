// @vitest-environment node
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';
import { matchCalibrationSnapshot, predictMatch, warmMatchPredictorCalibration } from './matchPredictor';
import type { MatchPredictionShadowContext } from './matchPredictionService';
import type { TeamWithRanking } from './types';

function runCases(
  cases: Array<{
    context: MatchPredictionShadowContext;
    prediction: ReturnType<typeof predictMatch>;
    reference_time: string;
  }>,
  root: string
) {
  return JSON.parse(
    execFileSync(process.execPath, ['--import', 'tsx', path.join(root, 'scripts/run-sos-research.ts')], {
      input: JSON.stringify({ cases }),
      encoding: 'utf8',
      windowsHide: true,
      timeout: 30000,
      env: { ...process.env, NODE_OPTIONS: '--conditions=react-server' },
    })
  );
}

describe('SOS frozen research', () => {
  it('reproduces all baseline outputs and swaps teams consistently for every arm', async () => {
    await warmMatchPredictorCalibration();
    const a = {
      team_id_master: 'a',
      team_name: 'A',
      age: 12,
      gender: 'M',
      power_score_final: 0.5,
      glicko_rating: 1500,
      glicko_rd: 80,
      sos_norm: 0.8,
      offense_norm: 0.5,
      defense_norm: 0.5,
      wins: 10,
      losses: 5,
      draws: 2,
      games_played: 17,
    } as TeamWithRanking;
    const b = { ...a, team_id_master: 'b', team_name: 'B', sos_norm: 0.3 };
    const context = {
      teamAInput: a,
      teamBInput: b,
      frozenEvidence: { games: [] },
      calibration: matchCalibrationSnapshot(),
    } as unknown as MatchPredictionShadowContext;
    const root = process.cwd();
    const frontendRoot = path.basename(root) === 'frontend' ? root : path.join(root, 'frontend');
    const clock = new Date().toISOString();
    const frozen = predictMatch(a, b, []);
    const [result, swapped, repeated] = runCases(
      [
        { context, prediction: frozen, reference_time: clock },
        {
          context: { ...context, teamAInput: b, teamBInput: a },
          prediction: predictMatch(b, a, []),
          reference_time: clock,
        },
        { context, prediction: frozen, reference_time: clock },
      ],
      frontendRoot
    );
    expect(repeated).toEqual(result);
    expect(result.variants['1']).toEqual(frozen);
    expect(result.receipt.aa_parity).toBe(true);
    expect(result.variants['0'].components.compositeDiff).toBeCloseTo(0, 12);
    expect(result.variants['1.5'].winProbabilityA).toBeGreaterThan(result.variants['1'].winProbabilityA);
    for (const arm of ['0', '0.5', '1', '1.5']) {
      expect(result.variants[arm].winProbabilityA).toBeCloseTo(swapped.variants[arm].winProbabilityB, 12);
      expect(result.variants[arm].expectedMargin).toBeCloseTo(-swapped.variants[arm].expectedMargin, 12);
      expect(result.variants[arm].blowout4PlusProbability).toBeCloseTo(
        swapped.variants[arm].blowout4PlusProbability,
        12
      );
    }
  });
});
