/** Match the deployed configuration, rather than assuming repository JSON was loaded. */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { stableJson } from './canonicalJson';
import {
  PREDICTOR_SOURCE_FILES,
  PREDICTOR_CALIBRATION_FILES,
  PREDICTOR_INPUT_SOURCE_FILES,
} from './predictionSourceInventory';
import { MATCH_PREDICTION_VERSION } from './matchPredictionService';
import type { PredictionRuntime } from './predictionRuntime';

export const RUNTIME_URL = 'https://www.pitchrank.io/api/match-prediction';
export const runtimeDigest = (value: unknown) => createHash('sha256').update(stableJson(value)).digest('hex');
const verifiedSources = new Map<string, string>();

export function validateRuntime(value: unknown): asserts value is PredictionRuntime {
  const p = value as PredictionRuntime;
  const keys = Object.keys(PREDICTOR_CALIBRATION_FILES).sort();
  if (
    !p ||
    p.schema_version !== 1 ||
    p.predictor_version !== MATCH_PREDICTION_VERSION ||
    typeof p.deployment_revision !== 'string' ||
    !/^[a-f0-9]{40}$/.test(p.deployment_revision) ||
    !Number.isFinite(Date.parse(p.observed_at)) ||
    Math.abs(Date.now() - Date.parse(p.observed_at)) > 300000 ||
    !p.calibration ||
    Object.keys(p.calibration).sort().join('|') !== keys.join('|') ||
    keys.some((key) => {
      const item = p.calibration[key as keyof typeof p.calibration];
      return item !== null && (typeof item !== 'object' || Array.isArray(item));
    }) ||
    !p.calibration.ageGroups ||
    !Array.isArray(p.probes) ||
    p.probes.length !== 9 ||
    p.probes.some(
      (probe) =>
        !probe ||
        !probe.teamA ||
        !probe.teamB ||
        !probe.prediction ||
        typeof probe.prediction !== 'object' ||
        Array.isArray(probe.prediction)
    )
  ) {
    throw new Error('Missing, stale or incompatible production runtime');
  }
}

export async function loadMonitoringRuntime(
  repoRoot: string,
  algorithmHash: string,
  options: { fetchMissingRevision?: boolean } = {}
) {
  // No credentials, redirects or configurable destination: this request reads public metadata only.
  const response = await fetch(RUNTIME_URL, {
    cache: 'no-store',
    redirect: 'error',
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok || Number(response.headers.get('content-length') ?? 0) > 1000000)
    throw new Error('Production runtime unavailable');
  const body = await response.text();
  if (body.length > 1000000) throw new Error('Production runtime too large');
  const profile: unknown = JSON.parse(body);
  validateRuntime(profile);
  const revision = profile.deployment_revision!;
  const inputHash = runtimeDigest(
    PREDICTOR_INPUT_SOURCE_FILES.map((file) => [
      file,
      readFileSync(path.join(repoRoot, 'frontend/lib', file), 'utf8').replace(/\r\n/g, '\n'),
    ])
  );
  const sourceKey = runtimeDigest({ algorithmHash, inputHash });
  if (verifiedSources.get(revision) === sourceKey) return { ...profile, input_source_hash: inputHash };
  const git = (args: string[]) =>
    execFileSync('git', args, {
      cwd: repoRoot,
      encoding: 'utf8',
      windowsHide: true,
      timeout: 30000,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  try {
    git(['cat-file', '-e', `${revision}^{commit}`]);
  } catch {
    if (!options.fetchMissingRevision) throw new Error('Fetch the deployed revision in the monitoring preflight first');
    git(['fetch', 'origin', revision, '--depth=1']);
  }
  const pairs = PREDICTOR_SOURCE_FILES.map((file) => [
    file,
    git(['show', `${revision}:frontend/lib/${file}`]).replace(/\r\n/g, '\n'),
  ]);
  if (runtimeDigest(pairs) !== algorithmHash) throw new Error('Deployed predictor source differs from monitoring');
  const inputs = PREDICTOR_INPUT_SOURCE_FILES.map((file) => [
    file,
    git(['show', `${revision}:frontend/lib/${file}`]).replace(/\r\n/g, '\n'),
  ]);
  if (runtimeDigest(inputs) !== inputHash) throw new Error('Deployed input normalization differs from monitoring');
  verifiedSources.set(revision, sourceKey);
  return { ...profile, input_source_hash: inputHash };
}
