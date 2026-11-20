/** Isolated weighted challenger. Never imported by the live Compare route. */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';
import { createHash } from 'node:crypto';
import { stableJson } from './canonicalJson';
import { PREDICTOR_SOURCE_FILES, PREDICTOR_CALIBRATION_FILES } from './predictionSourceInventory';
import type { MatchPredictionShadowContext } from './matchPredictionService';
import type { MatchPrediction } from './matchPredictor';

export const WEIGHT_NAMES = [
  'strength',
  'schedule',
  'raw_form',
  'offense_defense',
  'record',
  'evidence',
  'head_to_head',
  'common_opponents',
  'ml_directional',
] as const;

const anchors: Array<[string, number]> = [
  ['weights.POWER_SCORE * strengthSignal +', 0],
  ['weights.SOS * sosDiff +', 1],
  ['weights.RECENT_FORM * formDiffNorm +', 2],
  ['weights.MATCHUP * matchupAdvantage +', 3],
  ['recordDiff * 0.08 +', 4],
  ['evidenceSignal * 0.07 +', 5],
  ['h2hSignal * 0.08 +', 6],
  ['commonOpponent.advantage;', 7],
  ['residualSignal * 0.06 +', 8],
  ['residualSignal * 0.15', 8],
];

export async function createWinnerRuntime(context: MatchPredictionShadowContext, frontend: string) {
  const calibration = structuredClone(context.calibration);
  if (
    !calibration ||
    !context.frozenEvidence ||
    Object.keys(calibration).sort().join('|') !== Object.keys(PREDICTOR_CALIBRATION_FILES).sort().join('|')
  )
    throw new Error('Missing frozen inputs');
  const pairs = PREDICTOR_SOURCE_FILES.map(
    (name) => [name, readFileSync(path.join(frontend, 'lib', name), 'utf8').replace(/\r\n/g, '\n')] as const
  );
  const sources = Object.fromEntries(pairs);
  let generated = sources['matchPredictor.ts'];
  for (const [anchor, index] of anchors) {
    if (generated.split(anchor).length !== 2) throw new Error('Weighted research anchor changed');
    generated = generated.replace(anchor, `researchWeights[${index}] * ${anchor}`);
  }
  generated +=
    '\nlet researchWeights = Array(9).fill(1); export function setResearchWeights(v: number[]) { researchWeights = v; }\n';
  const snapshots = Object.fromEntries(
    Object.entries(PREDICTOR_CALIBRATION_FILES).map(([key, name]) => [
      name,
      calibration[key as keyof typeof calibration],
    ])
  );
  let timestamp = 0,
    closed = false;
  const FrozenDate = new Proxy(Date, {
    construct(target, args) {
      return Reflect.construct(target, args.length ? args : [timestamp]);
    },
    apply() {
      return new Date(timestamp).toString();
    },
    get(target, key, receiver) {
      return key === 'now' ? () => timestamp : Reflect.get(target, key, receiver);
    },
  });
  type Predictor = {
    predictMatch: typeof import('./matchPredictor').predictMatch;
    warmMatchPredictorCalibration: () => Promise<void>;
    setResearchWeights: (weights: number[]) => void;
  };
  function graph(predictorSource: string): Predictor {
    const sandbox = vm.createContext({ Date: FrozenDate });
    const cache = new Map<string, { exports: unknown }>();
    function load(name: string): unknown {
      if (name === 'calibrationLoader.ts')
        return {
          loadCalibrationJson: async (file: string) => {
            if (!(file in snapshots)) throw new Error('Missing calibration');
            return structuredClone(snapshots[file]);
          },
        };
      if (cache.has(name)) return cache.get(name)!.exports;
      if (!['matchPredictor.ts', 'confidenceEngine.ts', 'teamAge.ts', 'matchEvidence.ts'].includes(name))
        throw new Error('Unexpected predictor dependency');
      const source = name === 'matchPredictor.ts' ? predictorSource : sources[name];
      const compiled = ts.transpileModule(source, {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          target: ts.ScriptTarget.ES2022,
        },
      }).outputText;
      const loadedModule = { exports: {} };
      cache.set(name, loadedModule);
      const evaluate = vm.runInContext('(function(require,module,exports){' + compiled + '\n})', sandbox, {
        filename: name,
      });
      evaluate(
        (request: string) => {
          if (!/^\.\/[A-Za-z]+\.ts$/.test(request)) throw new Error('Unexpected predictor import');
          return load(request.slice(2));
        },
        loadedModule,
        loadedModule.exports
      );
      return loadedModule.exports;
    }
    return load('matchPredictor.ts') as Predictor;
  }
  const baseline = graph(sources['matchPredictor.ts']),
    candidate = graph(generated);
  await baseline.warmMatchPredictorCalibration();
  await candidate.warmMatchPredictorCalibration();
  return {
    run(
      c: MatchPredictionShadowContext,
      frozen: MatchPrediction,
      referenceTime: string,
      weights: Record<string, number>
    ) {
      if (closed || !c.frozenEvidence || stableJson(c.calibration) !== stableJson(calibration))
        throw new Error('Closed runtime or changed calibration');
      if (
        Object.keys(weights).sort().join('|') !== [...WEIGHT_NAMES].sort().join('|') ||
        WEIGHT_NAMES.some((key) => !Number.isFinite(weights[key]) || weights[key] < 0 || weights[key] > 6)
      )
        throw new Error('Invalid fixed weights');
      timestamp = Date.parse(referenceTime);
      if (!Number.isFinite(timestamp) || !/(Z|[+-]\d\d:\d\d)$/.test(referenceTime)) throw new Error('Invalid clock');
      const timezone = process.env.TZ;
      try {
        process.env.TZ = 'UTC';
        const inputs = [c.teamAInput, c.teamBInput, c.frozenEvidence.games] as const;
        const prediction = baseline.predictMatch(...inputs);
        if (!frozen || stableJson(prediction) !== stableJson(frozen)) throw new Error('Frozen baseline replay failed');
        candidate.setResearchWeights(Array(9).fill(1));
        if (stableJson(prediction) !== stableJson(candidate.predictMatch(...inputs)))
          throw new Error('A/A parity failed');
        candidate.setResearchWeights(WEIGHT_NAMES.map((key) => weights[key]));
        return {
          prediction: candidate.predictMatch(...inputs),
          receipt: {
            aa_parity: true,
            baseline_replay: true,
            reference_time: referenceTime,
            generated_source_sha256: createHash('sha256').update(generated).digest('hex'),
            source_hashes: Object.fromEntries(
              pairs.map(([name, source]) => [name, createHash('sha256').update(source).digest('hex')])
            ),
            node_version: process.versions.node,
            typescript_version: ts.version,
          },
        };
      } finally {
        if (timezone === undefined) delete process.env.TZ;
        else process.env.TZ = timezone;
      }
    },
    async close() {
      closed = true;
    },
  };
}
