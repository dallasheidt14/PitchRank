import { createFormulaRuntime, FORMULA_ARMS, FORMULA_CONTROLS, formulaDigest } from './compareFormulaResearch';
import { createHistoryAuditor } from './compareHistoryAudit';
import {
  formulaSyntheticCases,
  formulaBoundaryCases,
  improvedFormulaContext,
  SENSITIVITY_STEPS,
  SYNTHETIC_CLOCK,
} from './compareFormulaCases';
import { stableJson } from './canonicalJson';
import pin from './compareFormulaPin.json';
import { readFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { PREDICTOR_SOURCE_FILES } from './predictionSourceInventory';
import type { MatchPredictionShadowContext } from './matchPredictionService';
import type { MatchPrediction } from './matchPredictor';

export interface FormulaInput {
  cutoff: string;
  model: {
    signature: string;
    manifest: {
      model_version: string;
      code_revision: string;
      runtime_profile: { calibration: NonNullable<MatchPredictionShadowContext['calibration']> };
    };
  };
  rows: Array<{
    baseline_forecast_id: string;
    captured_at: string;
    game_date: string;
    provider: string;
    payload: {
      context: MatchPredictionShadowContext;
      prediction: MatchPrediction;
      reference_time: string;
      input_hash: string;
      receipt: { source_hashes: Record<string, string> };
    };
  }>;
}

export function validateFormulaInput(input: FormulaInput) {
  if (
    !input ||
    !Array.isArray(input.rows) ||
    !input.rows.length ||
    !Number.isFinite(Date.parse(input.cutoff)) ||
    input.model?.manifest?.model_version !== pin.model_version ||
    input.model.manifest.code_revision !== pin.revision ||
    !input.model.manifest.runtime_profile?.calibration
  )
    throw new Error('Expected a verified v8 frozen input export');
  const ids = new Set<string>();
  for (const row of input.rows) {
    const p = row.payload;
    if (
      !row.baseline_forecast_id ||
      ids.has(row.baseline_forecast_id) ||
      !Number.isFinite(Date.parse(row.captured_at)) ||
      Date.parse(row.captured_at) > Date.parse(input.cutoff) ||
      !/^\d{4}-\d{2}-\d{2}$/.test(row.game_date) ||
      !Number.isFinite(Date.parse(row.game_date)) ||
      Date.parse(row.captured_at) >= Date.parse(row.game_date) ||
      !Number.isFinite(Date.parse(p?.reference_time)) ||
      Date.parse(p.reference_time) > Date.parse(row.captured_at) ||
      formulaDigest(p.context) !== p.input_hash ||
      stableJson(p.context.calibration) !== stableJson(input.model.manifest.runtime_profile.calibration) ||
      Object.keys(p.receipt?.source_hashes ?? {})
        .sort()
        .join('|') !== [...PREDICTOR_SOURCE_FILES].sort().join('|') ||
      Object.entries(p.receipt.source_hashes).some(
        ([name, hash]) => pin.source_hashes[name as keyof typeof pin.source_hashes] !== hash
      )
    )
      throw new Error('Unverified, duplicate, changed or late frozen forecast');
    ids.add(row.baseline_forecast_id);
  }
}

export async function buildFormulaReport(input: FormulaInput, frontendRoot: string, synthetic = false) {
  validateFormulaInput(input);
  const calibration = input.model.manifest.runtime_profile.calibration;
  const runtime = await createFormulaRuntime(calibration, frontendRoot);
  const auditHistory = createHistoryAuditor(frontendRoot);
  const cases = input.rows.map((row) => ({
    id: row.baseline_forecast_id,
    provider: row.provider,
    game_date: row.game_date,
    captured_at: row.captured_at,
    context: row.payload.context,
    variants: runtime.variants(row.payload.context, row.payload.reference_time, row.payload.prediction),
    history: auditHistory(row.payload.context, row.payload.reference_time),
  }));
  const coverage: Record<string, number> = {};
  for (const c of cases) {
    const key = `${c.provider}|${[...new Set(c.history.teams.map((t) => t.age ?? 'unknown'))].sort().join('/')}|${Math.min(...c.history.teams.map((t) => t.recent_count)) < 8 ? 'under8' : '8+'}`;
    coverage[key] = (coverage[key] ?? 0) + 1;
  }
  const armChanges = Object.fromEntries(
    FORMULA_ARMS.map((arm) => [
      arm,
      {
        changed_winners: cases.filter(
          (c) => c.variants[arm].prediction.predictedWinner !== c.variants.baseline.prediction.predictedWinner
        ).length,
        max_win_probability_change: Math.max(
          ...cases.map((c) =>
            Math.abs(c.variants[arm].prediction.winProbabilityA - c.variants.baseline.prediction.winProbabilityA)
          )
        ),
      },
    ])
  );

  function sensitivity(contexts: MatchPredictionShadowContext[], times: string[]) {
    const stats = Object.fromEntries(
      Object.keys(SENSITIVITY_STEPS).map((field) => [
        field,
        {
          tested: 0,
          reversals: 0,
          max_drop: 0,
          winner_changes: 0,
          resolved_by_fixed_weights: 0,
          resolved_by_fixed_sos: 0,
        },
      ])
    );
    let maxSwapDifference = 0;
    let worstPower: null | { index: number; drop: number; diagnostic: ReturnType<typeof runtime.diagnose> } = null;
    contexts.forEach((context, index) => {
      const time = times[index];
      const initial = runtime.run(context, time);
      const swapped = runtime.run(
        { ...context, teamAInput: context.teamBInput, teamBInput: context.teamAInput },
        time
      ).prediction;
      const p = initial.prediction;
      maxSwapDifference = Math.max(
        maxSwapDifference,
        Math.abs(p.winProbabilityA - swapped.winProbabilityB),
        Math.abs(p.winProbabilityB - swapped.winProbabilityA),
        Math.abs(p.drawProbability! - swapped.drawProbability!),
        Math.abs(p.expectedMargin + swapped.expectedMargin),
        Math.abs(p.blowout4PlusProbability! - swapped.blowout4PlusProbability!)
      );
      for (const field of Object.keys(SENSITIVITY_STEPS) as Array<keyof typeof SENSITIVITY_STEPS>) {
        const improved = improvedFormulaContext(context, field);
        if (!improved) continue;
        const after = runtime.run(improved, time);
        const drop = p.winProbabilityA - after.prediction.winProbabilityA;
        const s = stats[field];
        s.tested++;
        s.winner_changes += Number(p.predictedWinner !== after.prediction.predictedWinner);
        if (drop <= 1e-8) continue;
        s.reversals++;
        s.max_drop = Math.max(s.max_drop, drop);
        const diagnostic = runtime.diagnose(context, improved, time);
        s.resolved_by_fixed_weights += Number(
          diagnostic.fixed_weights.prediction.winProbabilityA >= p.winProbabilityA - 1e-8
        );
        s.resolved_by_fixed_sos += Number(diagnostic.fixed_sos.prediction.winProbabilityA >= p.winProbabilityA - 1e-8);
        if (field === 'power_score_final' && (!worstPower || drop > worstPower.drop))
          worstPower = { index, drop, diagnostic };
      }
    });
    if (maxSwapDifference > 1e-12) throw new Error('Formula symmetry failed');
    return { cases: contexts.length, stats, max_swap_difference: maxSwapDifference, worst_power: worstPower };
  }
  const frozenSensitivity = sensitivity(
    input.rows.map((r) => r.payload.context),
    input.rows.map((r) => r.payload.reference_time)
  );
  const syntheticContexts = synthetic ? formulaSyntheticCases(calibration) : [];
  const boundaries = synthetic ? formulaBoundaryCases(syntheticContexts[1]) : [];
  const researchFiles = readdirSync(path.join(frontendRoot, 'lib')).filter(
    (name) => /^compare(?:Formula|History).*\.(?:ts|json)$/.test(name) && !name.endsWith('.test.ts')
  );
  const researchHashes = Object.fromEntries(
    [
      ...researchFiles.map((name) => `lib/${name}`),
      'scripts/audit-compare-formula.ts',
      'scripts/audit-compare-formula.mjs',
    ]
      .sort()
      .map((name) => [
        name,
        createHash('sha256')
          .update(readFileSync(path.join(frontendRoot, name), 'utf8').replace(/\r\n/g, '\n'))
          .digest('hex'),
      ])
  );
  return {
    schema_version: 1,
    study: 'compare-formula-diagnostic-v1',
    input_sha256: formulaDigest(input),
    model_signature: input.model.signature,
    cutoff: input.cutoff,
    baseline_revision: pin.revision,
    research_source_hashes: researchHashes,
    configuration_sha256: formulaDigest({
      arms: FORMULA_CONTROLS,
      sensitivity_steps: SENSITIVITY_STEPS,
      synthetic,
      synthetic_seed: 1449,
      synthetic_clock: SYNTHETIC_CLOCK,
    }),
    live_formula_changed: false,
    adoption_decision: 'not_authorized',
    summary: {
      captured: cases.length,
      baseline_replays: cases.length,
      coverage,
      arm_changes: armChanges,
      histories_with_source_copies: cases.filter((c) => c.history.same_source_fixture_copies.length).length,
      invalid_history_cases: cases.filter(
        (c) =>
          c.history.invalid_scores.length ||
          c.history.future_games.length ||
          c.history.excluded_games.length ||
          c.history.duplicate_ids ||
          c.history.ordering_errors.length
      ).length,
      outcome_status: 'coverage_only_no_results_loaded',
    },
    frozen_sensitivity: frozenSensitivity,
    synthetic_sensitivity: synthetic
      ? sensitivity(
          syntheticContexts,
          syntheticContexts.map(() => SYNTHETIC_CLOCK)
        )
      : null,
    boundary_sensitivity: synthetic
      ? sensitivity(
          boundaries,
          boundaries.map(() => SYNTHETIC_CLOCK)
        )
      : null,
    limitations: [
      'Synthetic changes and reversals measure behavior, not accuracy.',
      'All alternatives are reconstructed now from frozen inputs; only the baseline was captured before the match.',
      'Constant SOS arms replace only the SOS coefficient. Other adaptive coefficients keep their baseline values; no renormalization.',
      'Diagnostic fixed-weight controls are explanations, not candidate configurations.',
    ],
    cases,
  };
}
