/** Offline, pinned Compare runner. The production predictor files are never edited. */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import type { Game, TeamWithRanking } from '../lib/types';
import { stableJson } from '../lib/canonicalJson';

const revision = '866f30c73a84524028b9fe8e55b3108ec8d544fc';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const hashedFiles = [
  'matchPredictor.ts',
  'confidenceEngine.ts',
  'teamAge.ts',
  'matchPredictionService.ts',
  'predictionIdentity.ts',
  'calibrationLoader.ts',
  'matchEvidence.ts',
];
const calibrationFiles = [
  'age_group_parameters.json',
  'probability_parameters.json',
  'margin_parameters_v2.json',
  'heuristic_outcome_calibration.json',
  'confidence_parameters_v2.json',
];
function numericDifference(left: unknown, right: unknown): number {
  if (typeof left === 'number' && typeof right === 'number') return Math.abs(left - right);
  if (left !== null && right !== null && typeof left === 'object' && typeof right === 'object') {
    const a = left as Record<string, unknown>;
    const b = right as Record<string, unknown>;
    if (Object.keys(a).sort().join('|') !== Object.keys(b).sort().join('|')) return Infinity;
    return Math.max(0, ...Object.keys(a).map((key) => numericDifference(a[key], b[key])));
  }
  return left === right ? 0 : Infinity;
}
type ResearchCase = {
  period?: 'development' | 'evaluation';
  fixture: { source_game_id: string };
  teamA: TeamWithRanking;
  teamB: TeamWithRanking;
  games: Game[];
  frozenPrediction?: unknown;
  formOverrides?: Record<string, Record<string, number>>;
};

async function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) throw new Error('Usage: run-form-research.ts input.json output.json');
  const payload = JSON.parse(await readFile(path.resolve(inputPath), 'utf8')) as {
    schema_version: number;
    predictor_revision: string;
    cases: ResearchCase[];
    calibrations: Record<string, unknown>;
  };
  if (payload.schema_version !== 1 || payload.predictor_revision !== revision || !Array.isArray(payload.cases)) {
    throw new Error('Wrong research schema or predictor revision');
  }
  if (new Set(payload.cases.map((c) => c.fixture.source_game_id)).size !== payload.cases.length) {
    throw new Error('Duplicate research fixtures');
  }
  const sourceHashes: Record<string, string> = {};
  for (const name of hashedFiles) {
    const frozen = execFileSync('git', ['show', `${revision}:frontend/lib/${name}`], {
      cwd: root,
      encoding: 'utf8',
      windowsHide: true,
    }).replace(/\r\n/g, '\n');
    const current = (await readFile(path.join(root, 'lib', name), 'utf8')).replace(/\r\n/g, '\n');
    if (frozen !== current) throw new Error(`Collecting predictor changed: ${name}`);
    sourceHashes[name] = createHash('sha256').update(frozen).digest('hex');
  }
  const tempRoot = path.resolve(root, '../.turbo');
  await mkdir(tempRoot, { recursive: true });
  const temp = await mkdtemp(path.join(tempRoot, 'form-research-'));
  const originalCwd = process.cwd();
  const originalFetch = globalThis.fetch;
  try {
    const calibrationDir = path.join(temp, 'public/data/calibration');
    await mkdir(calibrationDir, { recursive: true });
    for (const file of calibrationFiles) {
      if (!payload.calibrations[file]) throw new Error(`Missing frozen calibration: ${file}`);
      await writeFile(path.join(calibrationDir, file), JSON.stringify(payload.calibrations[file]));
    }
    let source = await readFile(path.join(root, 'lib/matchPredictor.ts'), 'utf8');
    const anchors = [
      [
        'const formA = recentA.goalDiff;',
        'const formA = researchOverrides?.[teamA.team_id_master] ?? recentA.goalDiff;',
      ],
      [
        'const formB = recentB.goalDiff;',
        'const formB = researchOverrides?.[teamB.team_id_master] ?? recentB.goalDiff;',
      ],
      [
        'const residualSignal = clamp((recentA.mlTrend - recentB.mlTrend) / 3.5, -0.2, 0.2);',
        'const residualSignal = researchDisableMl ? 0 : clamp((recentA.mlTrend - recentB.mlTrend) / 3.5, -0.2, 0.2);',
      ],
    ];
    for (const [anchor, replacement] of anchors) {
      if (source.split(anchor).length !== 2) throw new Error('Pinned research patch no longer matches');
      source = source.replace(anchor, replacement);
    }
    source = source.replace(/from ['"]\.\/(.+?)['"]/g, (_match, moduleName: string) => {
      const file = moduleName.endsWith('.ts') ? moduleName : `${moduleName}.ts`;
      return `from '${pathToFileURL(path.join(root, 'lib', file)).href}'`;
    });
    source +=
      '\nlet researchOverrides: Record<string, number> | null = null;\nlet researchDisableMl = false;\nexport function setResearchForm(value: Record<string,number> | null, disableMl = false) { researchOverrides = value; researchDisableMl = disableMl; }\n';
    const generated = path.join(temp, 'predictor.ts');
    await writeFile(generated, source);
    process.chdir(temp);
    globalThis.fetch = (() => {
      throw new Error('Network disabled in offline research');
    }) as typeof fetch;
    const baseline = await import(pathToFileURL(path.join(root, 'lib/matchPredictor.ts')).href);
    const challenger = await import(pathToFileURL(generated).href);
    await baseline.warmMatchPredictorCalibration();
    await challenger.warmMatchPredictorCalibration();
    const outputs: Record<string, { id: string; prediction: unknown }[]> = { baseline: [] };
    let savedReplayMaximumDifference = 0;
    for (const c of payload.cases) {
      const expected = baseline.predictMatch(c.teamA, c.teamB, c.games);
      if (c.frozenPrediction) {
        const difference = numericDifference(expected, c.frozenPrediction);
        savedReplayMaximumDifference = Math.max(savedReplayMaximumDifference, difference);
        if (difference > 1e-12) throw new Error('Saved forecast replay exceeds floating-point tolerance');
      }
      challenger.setResearchForm(null);
      const replay = challenger.predictMatch(c.teamA, c.teamB, c.games);
      if (stableJson(expected) !== stableJson(replay)) throw new Error('A/A parity failed');
      outputs.baseline.push({ id: c.fixture.source_game_id, prediction: expected });
      for (const [name, overrides] of Object.entries(c.formOverrides ?? {})) {
        if (
          !Object.hasOwn(overrides, c.teamA.team_id_master) ||
          !Object.hasOwn(overrides, c.teamB.team_id_master) ||
          !Object.values(overrides).every(Number.isFinite)
        )
          throw new Error('Incomplete form overrides');
        for (const disableMl of c.period === 'development' ? [false, true] : [false]) {
          const key = disableMl ? `${name}_ml_off` : name;
          challenger.setResearchForm(overrides, disableMl);
          const prediction = challenger.predictMatch(c.teamA, c.teamB, c.games);
          (outputs[key] ??= []).push({ id: c.fixture.source_game_id, prediction });
        }
      }
    }
    await writeFile(
      path.resolve(originalCwd, outputPath),
      JSON.stringify(
        {
          schema_version: 1,
          predictor_revision: revision,
          source_hashes: sourceHashes,
          aa_parity: true,
          saved_replay_maximum_difference: savedReplayMaximumDifference,
          research_script_sha256: createHash('sha256')
            .update(await readFile(fileURLToPath(import.meta.url)))
            .digest('hex'),
          generated_source_sha256: createHash('sha256').update(source).digest('hex'),
          node_version: process.versions.node,
          cases: payload.cases.length,
          outputs,
        },
        null,
        2
      ),
      { flag: 'wx' }
    );
  } finally {
    globalThis.fetch = originalFetch;
    process.chdir(originalCwd);
    if (path.dirname(temp) !== tempRoot) throw new Error('Unexpected research workspace');
    await rm(temp, { recursive: true, force: true });
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : 'Research failed');
  process.exitCode = 1;
});
