// @vitest-environment node
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { expect, it, vi } from 'vitest';
import { predictionRuntime } from './predictionRuntime';
vi.mock('./calibrationLoader.ts', () => ({ loadCalibrationJson: async () => null }));

it.each([null, undefined])('refuses a missing frozen reference through the real runner (%s)', async (prediction) => {
  const p = await predictionRuntime();
  const probe = p.probes[0];
  const payload = {
    verifiedProductionRuntime: true,
    cases: [
      {
        context: {
          teamAInput: probe.teamA,
          teamBInput: probe.teamB,
          frozenEvidence: { games: [] },
          calibration: p.calibration,
        },
        prediction,
        reference_time: p.observed_at,
      },
    ],
  };
  expect(() =>
    execFileSync(process.execPath, ['--import', 'tsx', path.join(process.cwd(), 'scripts/run-sos-research.ts')], {
      input: JSON.stringify(payload),
      encoding: 'utf8',
      timeout: 30000,
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, NODE_OPTIONS: '--conditions=react-server' },
    })
  ).toThrow();
});

it('replays the actual predictor using explicit runtime defaults through Node/tsx', async () => {
  const p = await predictionRuntime();
  const cases = p.probes.map((probe) => ({
    context: {
      teamAInput: probe.teamA,
      teamBInput: probe.teamB,
      frozenEvidence: { games: [] },
      calibration: p.calibration,
    },
    prediction: probe.prediction,
    reference_time: p.observed_at,
  }));
  const results = JSON.parse(
    execFileSync(process.execPath, ['--import', 'tsx', path.join(process.cwd(), 'scripts/run-sos-research.ts')], {
      input: JSON.stringify({ verifiedProductionRuntime: true, cases }),
      encoding: 'utf8',
      timeout: 30000,
      windowsHide: true,
      env: { ...process.env, NODE_OPTIONS: '--conditions=react-server' },
    })
  );
  expect(results).toHaveLength(9);
  for (const [i, result] of results.entries()) {
    expect(result.receipt.replay_difference).toBe(0);
    expect(result.prediction).toEqual(cases[i].prediction);
    expect(result.variants['1']).toEqual(cases[i].prediction);
    expect(result.variants['1'].blowout4PlusProbability).toBeGreaterThan(0);
  }
});
