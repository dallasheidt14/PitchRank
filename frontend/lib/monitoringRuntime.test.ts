// @vitest-environment node
import { beforeEach, expect, it, vi } from 'vitest';
import { PREDICTOR_SOURCE_FILES } from './predictionSourceInventory';
import { loadMonitoringRuntime, runtimeDigest, validateRuntime, RUNTIME_URL } from './monitoringRuntime';

const git = vi.hoisted(() => vi.fn());
vi.mock('node:child_process', () => ({ execFileSync: git }));
vi.mock('node:fs', () => ({ readFileSync: (file: string) => `contents:${file.split(/[\\/]/).at(-1)}` }));
vi.mock('./matchPredictionService', () => ({ MATCH_PREDICTION_VERSION: 'test-live' }));
const revision = 'a'.repeat(40);
const hash = runtimeDigest(PREDICTOR_SOURCE_FILES.map((name) => [name, `contents:${name}`]));
function profile() {
  return {
    schema_version: 1,
    predictor_version: 'test-live',
    deployment_revision: revision,
    observed_at: new Date().toISOString(),
    calibration: { ageGroups: {}, probability: null, margin: null, outcome: null, confidence: null },
    probes: Array.from({ length: 9 }, () => ({ teamA: {}, teamB: {}, prediction: {} })),
  };
}
beforeEach(() => {
  vi.restoreAllMocks();
  git.mockImplementation((_command: string, args: string[]) =>
    args[0] === 'show' ? `contents:${args[1].split('/').at(-1)}` : ''
  );
});
it('reads only public same-origin metadata and verifies deployed source bytes', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(profile())));
  const result = await loadMonitoringRuntime('.', hash);
  expect(result.calibration.outcome).toBeNull();
  expect(fetcher).toHaveBeenCalledWith(RUNTIME_URL, expect.objectContaining({ redirect: 'error', cache: 'no-store' }));
  expect(fetcher.mock.calls[0][1]).not.toHaveProperty('headers');
  expect(git.mock.calls.filter(([, args]) => args[0] === 'show')).toHaveLength(9);
});
it.each(['missing', 'stale', 'version', 'revision', 'array', 'probe_reference'])(
  'refuses %s runtime metadata',
  (failure) => {
    const p = profile();
    if (failure === 'missing') delete (p.calibration as Partial<typeof p.calibration>).outcome;
    if (failure === 'stale') p.observed_at = '2000-01-01T00:00:00Z';
    if (failure === 'version') p.predictor_version = 'other';
    if (failure === 'revision') p.deployment_revision = '--upload-pack=evil';
    if (failure === 'array') Object.assign(p.calibration, { margin: [] });
    if (failure === 'probe_reference') Object.assign(p.probes[0], { prediction: null });
    expect(() => validateRuntime(p)).toThrow('runtime');
  }
);

it('refuses changed input helpers when the seven predictor modules still agree', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ ...profile(), deployment_revision: 'c'.repeat(40) }))
  );
  git.mockImplementation((_command: string, args: string[]) =>
    args[0] === 'show'
      ? args[1].endsWith('/utils.ts')
        ? 'changed helper'
        : `contents:${args[1].split('/').at(-1)}`
      : ''
  );
  await expect(loadMonitoringRuntime('.', hash)).rejects.toThrow('input normalization differs');
});
it('refuses source drift even when the declared model version agrees', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ ...profile(), deployment_revision: 'b'.repeat(40) }))
  );
  await expect(loadMonitoringRuntime('.', '0'.repeat(64))).rejects.toThrow('source differs');
});
