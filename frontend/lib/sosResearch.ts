/** Private research only. Production predictor bytes and calibration stay untouched. */
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { stableJson } from './canonicalJson';
import type { MatchPredictionShadowContext } from './matchPredictionService';
import type { MatchPrediction } from './matchPredictor';

export const SOS_MULTIPLIERS = [0, 0.5, 1, 1.5] as const;
import { PREDICTOR_SOURCE_FILES, PREDICTOR_CALIBRATION_FILES } from './predictionSourceInventory';
const sha = (value: string) => createHash('sha256').update(value).digest('hex');

function difference(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b);
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const left = a as Record<string, unknown>,
      right = b as Record<string, unknown>;
    if (Object.keys(left).sort().join('|') !== Object.keys(right).sort().join('|')) return Infinity;
    return Math.max(0, ...Object.keys(left).map((key) => difference(left[key], right[key])));
  }
  return a === b ? 0 : Infinity;
}

export async function createSosRuntime(
  calibrationSnapshot: NonNullable<MatchPredictionShadowContext['calibration']>,
  frontendRoot: string,
  options: { verifiedProductionRuntime?: boolean } = {}
) {
  if (
    !calibrationSnapshot ||
    (!options.verifiedProductionRuntime && Object.values(calibrationSnapshot).some((v) => v === null))
  )
    throw new Error('Incomplete frozen calibration');
  const pairs = await Promise.all(
    PREDICTOR_SOURCE_FILES.map(
      async (name) =>
        [name, (await readFile(path.join(frontendRoot, 'lib', name), 'utf8')).replace(/\r\n/g, '\n')] as const
    )
  );
  const original = pairs.find(([name]) => name === 'matchPredictor.ts')![1];
  const anchor = 'weights.SOS * sosDiff +';
  if (original.split(anchor).length !== 2) throw new Error('SOS research anchor changed');
  const mlAnchor = 'residualSignal * 0.15';
  if (original.split(mlAnchor).length !== 2) throw new Error('ML share research anchor changed');
  const generated =
    original
      .replace(anchor, 'researchSosMultiplier * weights.SOS * sosDiff +')
      .replace(mlAnchor, 'researchMlShareMultiplier * residualSignal * 0.15') +
    '\nlet researchSosMultiplier = 1;\nlet researchMlShareMultiplier = 1;\nexport function setResearchSos(value: number) { researchSosMultiplier = value; }\nexport function setResearchMlShare(value: number) { researchMlShareMultiplier = value; }\n';
  const workspace = await mkdtemp(path.join(tmpdir(), 'compare-sos-'));
  try {
    for (const [name, contents] of pairs) await writeFile(path.join(workspace, name), contents);
    const calibration = Object.fromEntries(
      Object.entries(PREDICTOR_CALIBRATION_FILES).map(([key, file]) => [
        file,
        calibrationSnapshot[key as keyof typeof PREDICTOR_CALIBRATION_FILES],
      ])
    );
    await writeFile(
      path.join(workspace, 'calibrationLoader.ts'),
      `const snapshots: Record<string, unknown> = ${JSON.stringify(calibration)};\n` +
        'export async function loadCalibrationJson<T>(name: string): Promise<T> { if (!(name in snapshots)) throw new Error("Missing calibration"); return structuredClone(snapshots[name]) as T; }\n'
    );
    await writeFile(path.join(workspace, 'researchPredictor.ts'), generated);
    const baseline = await import(pathToFileURL(path.join(workspace, 'matchPredictor.ts')).href);
    const candidate = await import(pathToFileURL(path.join(workspace, 'researchPredictor.ts')).href);
    await baseline.warmMatchPredictorCalibration();
    await candidate.warmMatchPredictorCalibration();
    const sourceHash = sha(
      (await readFile(path.join(frontendRoot, 'lib/sosResearch.ts'), 'utf8')).replace(/\r\n/g, '\n')
    );
    let closed = false;
    function calculate(
      context: MatchPredictionShadowContext,
      referenceTime: string,
      frozen?: MatchPrediction,
      experiment: 'sos' | 'ml_share' = 'sos'
    ) {
      if (closed || !context.frozenEvidence || stableJson(context.calibration) !== stableJson(calibrationSnapshot))
        throw new Error('Closed runtime or changed frozen calibration');
      const timestamp = Date.parse(referenceTime);
      if (!Number.isFinite(timestamp) || !/(Z|[+-]\d\d:\d\d)$/.test(referenceTime))
        throw new Error('Invalid research clock');
      const OriginalDate = globalThis.Date;
      const originalTimezone = process.env.TZ;
      try {
        process.env.TZ = 'UTC';
        globalThis.Date = new Proxy(OriginalDate, {
          construct(target, args) {
            return Reflect.construct(target, args.length ? args : [timestamp]);
          },
          apply() {
            return new OriginalDate(timestamp).toString();
          },
          get(target, key, receiver) {
            return key === 'now' ? () => timestamp : Reflect.get(target, key, receiver);
          },
        });
        const inputs = [context.teamAInput, context.teamBInput, context.frozenEvidence.games] as const;
        const diagnostics: { preOutcomeCalibration?: [number, number, number] } = {};
        const expected: MatchPrediction = baseline.predictMatch(...inputs, diagnostics);
        if (frozen !== undefined && (!frozen || typeof frozen !== 'object' || Array.isArray(frozen)))
          throw new Error('Invalid frozen reference prediction');
        const replayDifference = frozen !== undefined ? difference(expected, frozen) : 0;
        if (replayDifference > 1e-12) throw new Error('Live frozen prediction replay failed');
        const variants: Record<string, MatchPrediction> = {};
        for (const multiplier of experiment === 'sos' ? SOS_MULTIPLIERS : [0, 1]) {
          candidate.setResearchSos(experiment === 'sos' ? multiplier : 1);
          candidate.setResearchMlShare(experiment === 'ml_share' ? multiplier : 1);
          const prediction = candidate.predictMatch(...inputs);
          if (multiplier === 1 && stableJson(expected) !== stableJson(prediction))
            throw new Error('Research A/A parity failed');
          variants[String(multiplier)] = prediction;
        }
        return {
          prediction: expected,
          preOutcomeCalibration: diagnostics.preOutcomeCalibration,
          variants,
          receipt: {
            aa_parity: true,
            experiment,
            replay_difference: replayDifference,
            algorithm_hash: sha(stableJson(pairs)),
            generated_source_sha256: sha(generated),
            research_source_sha256: sourceHash,
            source_hashes: Object.fromEntries(pairs.map(([name, content]) => [name, sha(content)])),
            reference_time: referenceTime,
            node_version: process.versions.node,
          },
        };
      } finally {
        globalThis.Date = OriginalDate;
        if (originalTimezone === undefined) delete process.env.TZ;
        else process.env.TZ = originalTimezone;
      }
    }
    return {
      run(context: MatchPredictionShadowContext, frozen: MatchPrediction, referenceTime: string) {
        if (!frozen || typeof frozen !== 'object' || Array.isArray(frozen))
          throw new Error('Missing frozen reference prediction');
        return calculate(context, referenceTime, frozen);
      },
      capture(context: MatchPredictionShadowContext, referenceTime: string) {
        return calculate(context, referenceTime);
      },
      compareMlShare(context: MatchPredictionShadowContext, referenceTime: string, frozen?: MatchPrediction) {
        return calculate(context, referenceTime, frozen, 'ml_share');
      },
      async close() {
        closed = true;
        await rm(workspace, { recursive: true, force: true });
      },
    };
  } catch (error) {
    await rm(workspace, { recursive: true, force: true });
    throw error;
  }
}

export async function sosVariants(
  context: MatchPredictionShadowContext,
  frozen: MatchPrediction,
  referenceTime: string,
  frontendRoot: string
) {
  if (!context.calibration) throw new Error('Missing frozen calibration');
  const runtime = await createSosRuntime(context.calibration, frontendRoot);
  try {
    return runtime.run(context, frozen, referenceTime);
  } finally {
    await runtime.close();
  }
}
