/** Offline instrumentation of the collecting v8 predictor. No live modules are changed. */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';
import pin from './compareFormulaPin.json';
import { stableJson } from './canonicalJson';
import {
  PREDICTOR_SOURCE_FILES,
  PREDICTOR_INPUT_SOURCE_FILES,
  PREDICTOR_CALIBRATION_FILES,
} from './predictionSourceInventory';
import type { MatchPredictionShadowContext } from './matchPredictionService';
import type { MatchPrediction } from './matchPredictor';

export const FORMULA_ARMS = [
  'baseline',
  'sos_x0',
  'sos_x0.5',
  'sos_x1.5',
  'fixed_sos_0.06',
  'fixed_sos_0.12',
  'fixed_sos_0.18',
  'extra_record_off',
] as const;
export type FormulaArm = (typeof FORMULA_ARMS)[number];
type Weights = { POWER_SCORE: number; SOS: number; RECENT_FORM: number; MATCHUP: number };
type Controls = { sosMultiplier?: number; weights?: Weights; sosCoefficient?: number; recordCoefficient?: number };
export const FORMULA_CONTROLS: Record<FormulaArm, Controls> = {
  baseline: {},
  sos_x0: { sosMultiplier: 0 },
  'sos_x0.5': { sosMultiplier: 0.5 },
  'sos_x1.5': { sosMultiplier: 1.5 },
  'fixed_sos_0.06': { sosCoefficient: 0.06 },
  'fixed_sos_0.12': { sosCoefficient: 0.12 },
  'fixed_sos_0.18': { sosCoefficient: 0.18 },
  extra_record_off: { recordCoefficient: 0 },
};
export interface FormulaTrace {
  weights: Weights;
  terms: Record<string, number>;
  strengthSignal: number;
  recordDiff: number;
  hasGlicko: boolean;
  powerDiff: number;
  mismatchScore: number;
  beforeAmplification: number;
  amplification: number;
  compositeDiff: number;
  shareSignal: number;
  mlComposite: number;
  mlShare: number;
  predictiveShare: number;
  totalGoals: number;
  marginMultiplier: number;
  desiredMargin: number;
  boundedMargin: number;
  expectedGoals: { teamA: number; teamB: number };
  preOutcomeCalibration: number[];
}
export const formulaDigest = (value: unknown) => createHash('sha256').update(stableJson(value)).digest('hex');
const sourceDigest = (value: string) => createHash('sha256').update(value).digest('hex');

function replaceOnce(source: string, anchor: string, replacement: string) {
  if (source.split(anchor).length !== 2) throw new Error('Pinned formula instrumentation anchor changed');
  return source.replace(anchor, replacement);
}

export function instrumentFormula(original: string) {
  let source = replaceOnce(
    original,
    'const { weights, mismatchScore } = getAdaptiveWeights(powerDiff, offenseA, offenseB, defenseA, defenseB);',
    `const adaptive = getAdaptiveWeights(powerDiff, offenseA, offenseB, defenseA, defenseB);
     const weights = { ...(researchControls.weights ?? adaptive.weights) };
     if (researchControls.sosCoefficient !== undefined) weights.SOS = researchControls.sosCoefficient;
     const mismatchScore = adaptive.mismatchScore;
     researchTerms = {};`
  );
  const terms = [
    ['strength', 'weights.POWER_SCORE * strengthSignal'],
    ['sos', 'weights.SOS * sosDiff'],
    ['form', 'weights.RECENT_FORM * formDiffNorm'],
    ['matchup', 'weights.MATCHUP * matchupAdvantage'],
    ['record', 'recordDiff * 0.08'],
    ['ml', 'residualSignal * 0.06'],
    ['evidence', 'evidenceSignal * 0.07'],
    ['headToHead', 'h2hSignal * 0.08'],
  ];
  for (const [key, expression] of terms) {
    const changed =
      key === 'sos'
        ? '(researchControls.sosMultiplier ?? 1) * weights.SOS * sosDiff'
        : key === 'record'
          ? 'recordDiff * (researchControls.recordCoefficient ?? 0.08)'
          : expression;
    source = replaceOnce(source, expression + ' +', `researchTerm('${key}', ${changed}) +`);
  }
  source = replaceOnce(
    source,
    '    commonOpponent.advantage;',
    "    researchTerm('commonOpponent', commonOpponent.advantage);\n  const researchBeforeAmplification = compositeDiff;"
  );
  source = replaceOnce(
    source,
    '  return {\n    predictedWinner,',
    `  researchTrace = {
    weights, terms: researchTerms, strengthSignal, recordDiff, hasGlicko: Boolean(glickoStrength),
    powerDiff, mismatchScore, beforeAmplification: researchBeforeAmplification,
    amplification: mismatchScore > 0.4 ? 1 + (mismatchScore - 0.4) * 0.9 : 1,
    compositeDiff, shareSignal, mlComposite: residualSignal * 0.06,
    mlShare: residualSignal * 0.15, predictiveShare: predictiveShareBias * 0.45,
    totalGoals, marginMultiplier, desiredMargin, boundedMargin,
    expectedGoals: { teamA: lambdaA, teamB: lambdaB },
    preOutcomeCalibration: [rawWinProbA, rawDrawProbability, rawWinProbB]
  };
  return {\n    predictedWinner,`
  );
  return (
    source +
    `
let researchControls = {};
let researchTerms = {};
let researchTrace;
function researchTerm(name, value) { researchTerms[name] = value; return value; }
export function setResearchControls(value) { researchControls = value; }
export function getResearchTrace() { return researchTrace; }
`
  );
}

function difference(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number')
    return Number.isFinite(a) && Number.isFinite(b) ? Math.abs(a - b) : Infinity;
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const left = a as Record<string, unknown>,
      right = b as Record<string, unknown>;
    if (Object.keys(left).sort().join('|') !== Object.keys(right).sort().join('|')) return Infinity;
    return Math.max(0, ...Object.keys(left).map((key) => difference(left[key], right[key])));
  }
  return a === b ? 0 : Infinity;
}

export function validateFormulaPrediction(p: MatchPrediction) {
  const probabilities = [p.winProbabilityA, p.drawProbability, p.winProbabilityB] as number[];
  if (
    [...probabilities, p.blowout4PlusProbability].some(
      (v) => typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 1
    ) ||
    Math.abs(probabilities.reduce((a, b) => a + b, 0) - 1) > 1e-12 ||
    [
      p.expectedMargin,
      p.expectedAbsoluteGoalDifference,
      p.expectedGoals?.teamA,
      p.expectedGoals?.teamB,
      p.expectedScore?.teamA,
      p.expectedScore?.teamB,
    ].some((v) => typeof v !== 'number' || !Number.isFinite(v))
  )
    throw new Error('Incomplete formula probability, score or risk outputs');
}

/** Compiles the actual pinned source in memory: default CLI mode creates no temporary files. */
export async function createFormulaRuntime(
  calibration: NonNullable<MatchPredictionShadowContext['calibration']>,
  frontendRoot: string
) {
  if (
    !calibration ||
    !calibration.ageGroups ||
    Object.keys(calibration).sort().join('|') !== Object.keys(PREDICTOR_CALIBRATION_FILES).sort().join('|') ||
    Object.values(calibration).some((v) => v !== null && (typeof v !== 'object' || Array.isArray(v)))
  )
    throw new Error('Incomplete frozen calibration');
  calibration = structuredClone(calibration);
  const sources = Object.fromEntries(
    [...PREDICTOR_SOURCE_FILES, ...PREDICTOR_INPUT_SOURCE_FILES].map((name) => {
      const source = readFileSync(path.join(frontendRoot, 'lib', name), 'utf8').replace(/\r\n/g, '\n');
      if (sourceDigest(source) !== pin.source_hashes[name as keyof typeof pin.source_hashes])
        throw new Error('Collecting predictor source differs from pinned v8');
      return [name, source];
    })
  );
  const generated = instrumentFormula(sources['matchPredictor.ts']);
  const snapshots = Object.fromEntries(
    Object.entries(PREDICTOR_CALIBRATION_FILES).map(([key, name]) => [
      name,
      calibration[key as keyof typeof calibration],
    ])
  );
  let timestamp = 0;
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
  const calibrationLoader = {
    loadCalibrationJson: async (name: string) => {
      if (!(name in snapshots)) throw new Error('Unfrozen calibration dependency');
      return structuredClone(snapshots[name]);
    },
  };
  type PredictorModule = {
    predictMatch: typeof import('./matchPredictor').predictMatch;
    warmMatchPredictorCalibration: () => Promise<void>;
    setResearchControls: (controls: Controls) => void;
    getResearchTrace: () => FormulaTrace;
  };
  function loadGraph(predictorSource: string): PredictorModule {
    const sandbox = vm.createContext({ Date: FrozenDate });
    const cache = new Map<string, { exports: unknown }>();
    function load(name: string): unknown {
      if (name === 'calibrationLoader.ts') return calibrationLoader;
      if (cache.has(name)) return cache.get(name)!.exports;
      if (!['matchPredictor.ts', 'confidenceEngine.ts', 'teamAge.ts', 'matchEvidence.ts'].includes(name))
        throw new Error('Unexpected predictor runtime dependency');
      const source = name === 'matchPredictor.ts' ? predictorSource : sources[name];
      const compiled = ts.transpileModule(source, {
        compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
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
    return load('matchPredictor.ts') as PredictorModule;
  }
  const baseline = loadGraph(sources['matchPredictor.ts']),
    research = loadGraph(generated);
  await baseline.warmMatchPredictorCalibration();
  await research.warmMatchPredictorCalibration();
  const receipt = {
    predictor_revision: pin.revision,
    model_version: pin.model_version,
    source_hashes: pin.source_hashes,
    generated_source_sha256: sourceDigest(generated),
    calibration_sha256: formulaDigest(calibration),
    research_source_sha256: sourceDigest(
      readFileSync(path.join(frontendRoot, 'lib/compareFormulaResearch.ts'), 'utf8').replace(/\r\n/g, '\n')
    ),
    typescript_version: ts.version,
    node_version: process.versions.node,
  };
  function run(
    context: MatchPredictionShadowContext,
    referenceTime: string,
    controls: Controls = {},
    frozen?: MatchPrediction
  ) {
    if (
      context.predictorVersion !== pin.model_version ||
      !context.frozenEvidence ||
      stableJson(context.calibration) !== stableJson(calibration)
    )
      throw new Error('Changed predictor or frozen calibration/evidence');
    timestamp = Date.parse(referenceTime);
    if (!Number.isFinite(timestamp) || !/(Z|[+-]\d\d:\d\d)$/.test(referenceTime))
      throw new Error('Invalid frozen clock');
    const previousTimezone = process.env.TZ;
    try {
      process.env.TZ = 'UTC';
      const inputs = [context.teamAInput, context.teamBInput, context.frozenEvidence.games] as const;
      const expected = baseline.predictMatch(...inputs);
      if (frozen !== undefined && (!frozen || difference(expected, frozen) > 1e-12))
        throw new Error('Frozen baseline replay failed');
      research.setResearchControls({});
      const unchanged = research.predictMatch(...inputs);
      if (stableJson(unchanged) !== stableJson(expected))
        throw new Error('Research unchanged mode differs from baseline');
      research.setResearchControls(controls);
      const prediction = research.predictMatch(...inputs);
      validateFormulaPrediction(prediction);
      const trace = structuredClone(research.getResearchTrace());
      if (
        Math.abs(Object.values(trace.terms).reduce((a, b) => a + b, 0) - trace.beforeAmplification) > 1e-12 ||
        Math.abs(trace.beforeAmplification * trace.amplification - prediction.components!.compositeDiff) > 1e-12
      )
        throw new Error('Trace does not reconcile with predictor');
      return {
        prediction: structuredClone(prediction),
        trace,
        receipt: {
          ...receipt,
          aa_parity: true,
          reference_time: referenceTime,
          input_sha256: formulaDigest({ context, referenceTime }),
          controls_sha256: formulaDigest(controls),
          baseline_provenance: frozen === undefined ? 'reconstructed' : 'frozen_baseline_replay',
          prediction_provenance:
            frozen !== undefined && Object.keys(controls).length === 0 ? 'frozen_replay' : 'reconstructed',
        },
      };
    } finally {
      if (previousTimezone === undefined) delete process.env.TZ;
      else process.env.TZ = previousTimezone;
    }
  }
  return {
    run,
    variants(context: MatchPredictionShadowContext, time: string, frozen?: MatchPrediction) {
      return Object.fromEntries(
        FORMULA_ARMS.map((arm) => {
          return [arm, run(context, time, FORMULA_CONTROLS[arm], frozen)];
        })
      ) as Record<FormulaArm, ReturnType<typeof run>>;
    },
    diagnose(
      context: MatchPredictionShadowContext,
      improved: MatchPredictionShadowContext,
      time: string,
      frozen?: MatchPrediction
    ) {
      const before = run(context, time, {}, frozen);
      return {
        before,
        after: run(improved, time),
        fixed_weights: run(improved, time, { weights: before.trace.weights }),
        fixed_sos: run(improved, time, { sosCoefficient: before.trace.weights.SOS }),
      };
    },
  };
}
