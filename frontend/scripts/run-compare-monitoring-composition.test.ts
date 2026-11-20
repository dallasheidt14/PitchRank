// @vitest-environment node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { main } from './run-compare-monitoring.mjs';
import { loadMonitoringRuntime, runtimeDigest } from '../lib/monitoringRuntime';
import { PREDICTOR_INPUT_SOURCE_FILES, PREDICTOR_SOURCE_FILES } from '../lib/predictionSourceInventory';

const state = vi.hoisted(() => ({
  known: new Set<string>(),
  sources: new Map<string, string>(),
  drift: '',
}));
vi.mock('../lib/matchPredictionService', () => ({ MATCH_PREDICTION_VERSION: 'fixed-test-version' }));
vi.mock('node:fs', async (importActual) => {
  const actual = await importActual<typeof import('node:fs')>();
  return {
    ...actual,
    readFileSync: (file: string) => state.sources.get(path.basename(file)) ?? actual.readFileSync(file),
  };
});
vi.mock('node:child_process', () => ({
  execFileSync: (_command: string, args: string[]) => {
    if (args[0] === 'cat-file') {
      if (!state.known.has(args[2].split('^')[0])) throw new Error('Unknown deployment');
      return '';
    }
    if (args[0] === 'fetch') {
      state.known.add(args[3]);
      return '';
    }
    if (args[0] === 'show') {
      const [revision, name] = args[1].split(':');
      const source = state.sources.get(path.basename(name));
      return revision === state.drift ? 'changed ' + source : source;
    }
    throw new Error('Unexpected git operation');
  },
}));

let owned = '';
const bridge = globalThis as typeof globalThis & { __monitorComposition?: () => Promise<unknown> };
beforeEach(() => {
  state.known.clear();
  state.sources.clear();
  state.drift = '';
  for (const name of [...PREDICTOR_SOURCE_FILES, ...PREDICTOR_INPUT_SOURCE_FILES])
    state.sources.set(name, 'frozen ' + name);
  owned = fs.mkdtempSync(path.join(os.tmpdir(), 'compare-launcher-composition-'));
  const frontend = path.join(owned, 'frontend');
  const packageDir = path.join(frontend, 'node_modules/@supabase/supabase-js');
  fs.mkdirSync(packageDir, { recursive: true });
  fs.mkdirSync(path.join(frontend, 'scripts'), { recursive: true });
  fs.writeFileSync(path.join(frontend, 'package.json'), '{"type":"commonjs"}');
  fs.writeFileSync(path.join(packageDir, 'index.js'), 'exports.createClient = () => ({ pinnedClient: true });');
  fs.writeFileSync(
    path.join(frontend, 'scripts/capture-compare-monitoring.ts'),
    'exports.captureMonitoring = async (client, options) => { ' +
      'if (!client.pinnedClient || options.execute) throw new Error("Unexpected write"); ' +
      'await globalThis.__monitorComposition(); await globalThis.__monitorComposition(); ' +
      'return {monitorSignature:"pinned-signature", captured:0, errors:0}; };'
  );
  vi.spyOn(process, 'cwd').mockReturnValue(frontend);
  vi.stubEnv('SUPABASE_URL', 'https://unit-test.invalid');
  vi.stubEnv('SUPABASE_SERVICE_ROLE_KEY', 'fake-test-key');
  const hash = runtimeDigest(PREDICTOR_SOURCE_FILES.map((name) => [name, state.sources.get(name)]));
  bridge.__monitorComposition = () => loadMonitoringRuntime(owned, hash);
});
afterEach(() => {
  delete bridge.__monitorComposition;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  if (!path.resolve(owned).startsWith(path.resolve(os.tmpdir()) + path.sep + 'compare-launcher-composition-'))
    throw new Error('Unexpected temporary test directory');
  fs.rmSync(owned, { recursive: true, force: true });
});

function profiles(revisions: string[]) {
  state.known.add(revisions[0]);
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      Response.json({
        schema_version: 1,
        predictor_version: 'fixed-test-version',
        deployment_revision: revisions.shift(),
        observed_at: new Date().toISOString(),
        calibration: { ageGroups: {}, probability: null, margin: null, outcome: null, confidence: null },
        probes: Array.from({ length: 9 }, () => ({ teamA: {}, teamB: {}, prediction: {} })),
      })
    )
  );
}

it('loads the collector from its working checkout and fetches a mid-batch deployment before the real verifier', async () => {
  profiles(['a'.repeat(40), 'b'.repeat(40)]);
  const originalFetch = globalThis.fetch;
  const log = vi.spyOn(console, 'log').mockImplementation(() => {});
  await main(['--limit', '2']);
  expect(JSON.parse(log.mock.calls[0][0])).toEqual({
    monitorSignature: 'pinned-signature',
    captured: 0,
    errors: 0,
    deploymentRevisionsFetched: 1,
  });
  expect(globalThis.fetch).toBe(originalFetch);
});

it('retains the real verifier source-drift refusal after fetching a new deployment and restores fetch', async () => {
  profiles(['c'.repeat(40), 'd'.repeat(40)]);
  state.drift = 'd'.repeat(40);
  const originalFetch = globalThis.fetch;
  await expect(main(['--limit', '2'])).rejects.toThrow('Deployed predictor source differs from monitoring');
  expect(globalThis.fetch).toBe(originalFetch);
});
