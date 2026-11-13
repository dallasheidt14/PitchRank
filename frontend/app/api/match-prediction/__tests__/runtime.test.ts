// @vitest-environment node
import { expect, it, vi } from 'vitest';
import { GET } from '../route';
vi.mock('@/lib/calibrationLoader.ts', () => ({ loadCalibrationJson: async () => null }));

it('reports effective fallback settings with synthetic probes and no private data', async () => {
  vi.stubEnv('VERCEL_GIT_COMMIT_SHA', 'a'.repeat(40));
  const response = await GET();
  expect(response.headers.get('cache-control')).toBe('no-store');
  const body = await response.json();
  expect(body.calibration).toEqual({ ageGroups: {}, probability: null, margin: null, outcome: null, confidence: null });
  expect(body.probes).toHaveLength(9);
  expect(body.probes[0].prediction.winProbabilityA).toBeGreaterThan(0);
  expect(new Set(body.probes.map((p: { teamA: { team_id_master: string } }) => p.teamA.team_id_master)).size).toBe(1);
  expect(Object.keys(body).sort()).toEqual([
    'calibration',
    'deployment_revision',
    'observed_at',
    'predictor_version',
    'probes',
    'schema_version',
  ]);
  vi.unstubAllEnvs();
});
