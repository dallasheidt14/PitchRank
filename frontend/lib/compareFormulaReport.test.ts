// @vitest-environment node
import { expect, it } from 'vitest';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { buildFormulaReport, validateFormulaInput, type FormulaInput } from './compareFormulaReport';
import { createFormulaRuntime, formulaDigest } from './compareFormulaResearch';
import { formulaSyntheticCases, SYNTHETIC_CLOCK } from './compareFormulaCases';
import { PREDICTOR_SOURCE_FILES } from './predictionSourceInventory';
import pin from './compareFormulaPin.json';

async function input() {
  const calibration = { ageGroups: {}, probability: null, margin: null, outcome: null, confidence: null };
  const context = formulaSyntheticCases(calibration)[1];
  const runtime = await createFormulaRuntime(calibration, process.cwd());
  return {
    cutoff: SYNTHETIC_CLOCK,
    model: {
      signature: 'private-model-signature',
      manifest: { model_version: pin.model_version, code_revision: pin.revision, runtime_profile: { calibration } },
    },
    rows: [
      {
        baseline_forecast_id: 'one',
        captured_at: SYNTHETIC_CLOCK,
        game_date: '2026-11-15',
        provider: 'synthetic',
        payload: {
          context,
          prediction: runtime.run(context, SYNTHETIC_CLOCK).prediction,
          reference_time: SYNTHETIC_CLOCK,
          input_hash: formulaDigest(context),
          receipt: {
            source_hashes: Object.fromEntries(
              PREDICTOR_SOURCE_FILES.map((name) => [name, pin.source_hashes[name as keyof typeof pin.source_hashes]])
            ),
          },
        },
      },
    ],
  } satisfies FormulaInput;
}

it('replays the full candidate report deterministically without producing accuracy claims', async () => {
  const data = await input();
  const a = await buildFormulaReport(data, process.cwd());
  expect(await buildFormulaReport(data, process.cwd())).toEqual(a);
  expect(a.summary.baseline_replays).toBe(1);
  expect(a.adoption_decision).toBe('not_authorized');
  expect(a.summary.outcome_status).toBe('coverage_only_no_results_loaded');
  expect(a.cases[0].variants.baseline.prediction).toEqual(data.rows[0].payload.prediction);
});

it('refuses changed inputs, source inventories, duplicate forecasts, and post-match captures', async () => {
  const data = await input();
  const changed = structuredClone(data);
  changed.rows[0].payload.context.teamAInput.sos_norm = 0.9;
  expect(() => validateFormulaInput(changed)).toThrow('Unverified');
  const sources = structuredClone(data);
  delete sources.rows[0].payload.receipt.source_hashes['matchPredictor.ts'];
  sources.rows[0].payload.receipt.source_hashes['utils.ts'] = pin.source_hashes['utils.ts'];
  expect(() => validateFormulaInput(sources)).toThrow('Unverified');
  expect(() => validateFormulaInput({ ...data, rows: [data.rows[0], data.rows[0]] })).toThrow('Unverified');
  const late = structuredClone(data);
  late.rows[0].game_date = '2026-11-13';
  expect(() => validateFormulaInput(late)).toThrow('Unverified');
});

it('runs the real CLI in read-only mode and refuses output without execute', async () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'formula-cli-test-'));
  try {
    const filename = path.join(directory, 'input.json');
    writeFileSync(filename, JSON.stringify(await input()));
    const command = ['scripts/audit-compare-formula.mjs', '--input', filename];
    const options = {
      encoding: 'utf8' as const,
      timeout: 30000,
      windowsHide: true,
      env: { ...process.env, TSX_DISABLE_CACHE: '', TMPDIR: directory, TMP: directory, TEMP: directory },
    };
    const result = JSON.parse(execFileSync(process.execPath, command, options));
    expect(result.output_written).toBe(false);
    expect(result.baseline_replays).toBe(1);
    expect(readdirSync(directory)).toEqual(['input.json']);
    expect(() =>
      execFileSync(process.execPath, [...command, '--output', path.join(directory, 'report.json')], {
        ...options,
        stdio: 'pipe',
      })
    ).toThrow();
    expect(readdirSync(directory)).toEqual(['input.json']);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}, 30000);
