/** Observe live Compare privately; never write the original forecast ledger. */
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { buildMatchPredictionWithShadowContext, MATCH_PREDICTION_VERSION } from '../lib/matchPredictionService';
import { captureCodeIdentity, digest } from '../lib/prospectiveCapture';
import { createSosRuntime, SOS_MULTIPLIERS } from '../lib/sosResearch';
import { warmMatchPredictorCalibration, matchCalibrationSnapshot } from '../lib/matchPredictor';

export async function captureMonitoring(client: SupabaseClient, options: { limit: number; execute: boolean }) {
  const { limit, execute } = options;
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new Error('Limit must be 1..500');
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const identity = captureCodeIdentity();
  const researchHash = createHash('sha256')
    .update(fs.readFileSync(path.join(root, 'lib/sosResearch.ts'), 'utf8').replace(/\r\n/g, '\n'))
    .digest('hex');
  await warmMatchPredictorCalibration();
  const modelSignature = digest({ algorithm: identity.algorithmHash, calibration: matchCalibrationSnapshot() });
  const manifest = {
    kind: 'compare_live_sos_monitoring',
    schema_version: 1,
    model_version: MATCH_PREDICTION_VERSION,
    model_signature: modelSignature,
    code_revision: identity.codeRevision,
    algorithm_hash: identity.algorithmHash,
    research_hash: researchHash,
    multipliers: SOS_MULTIPLIERS,
    production_promotion: false,
  };
  const manifestText = JSON.stringify(manifest);
  const monitor = createHash('sha256').update(manifestText).digest('hex');
  if (execute) {
    const registration = await client.rpc('register_compare_monitor', { p_manifest: manifestText });
    if (registration.error || registration.data !== monitor) throw new Error('Monitoring registration failed');
  }
  const today = new Date().toISOString().slice(0, 10);
  const summary = {
    execute,
    selected: 0,
    captured: 0,
    existing: 0,
    errors: 0,
    skipped: 0,
    modelVersion: MATCH_PREDICTION_VERSION,
    monitorSignature: monitor,
    formulaChanged: false,
  };
  // Queue includes completed originals: the collector's pinned formula remains authoritative for its study.
  let runtime: Awaited<ReturnType<typeof createSosRuntime>> | undefined;
  try {
    for (let offset = 0; summary.selected < limit; offset += 1000) {
      const { data, error } = await client
        .from('prospective_match_predictions')
        .select('id,game_date,home_team_master_id,away_team_master_id,source_game_id')
        .eq('heuristic_prediction_status', 'completed')
        .eq('source_system', 'database_games')
        .gt('game_date', today)
        .lte('game_date', new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10))
        .order('game_date')
        .order('id')
        .range(offset, offset + 999);
      if (error) throw new Error('Monitoring queue unavailable');
      for (const row of data ?? []) {
        if (summary.selected >= limit) break;
        if (execute) {
          const existing = await client
            .from('compare_monitoring_forecasts')
            .select('baseline_forecast_id')
            .eq('baseline_forecast_id', row.id)
            .eq('monitor_signature', monitor)
            .maybeSingle();
          if (existing.error) throw new Error('Monitoring deduplication failed');
          if (existing.data) {
            summary.existing++;
            continue;
          }
        }
        summary.selected++;
        if (!execute) continue; // Preview never runs research, creates files, or registers a model.
        try {
          const referenceTime = new Date().toISOString();
          const result = await buildMatchPredictionWithShadowContext(
            client,
            row.home_team_master_id,
            row.away_team_master_id,
            client,
            { freezeInputs: true }
          );
          const context = result.shadowContext;
          if (digest({ algorithm: identity.algorithmHash, calibration: context.calibration }) !== modelSignature)
            throw new Error('Calibration changed during capture');
          runtime ??= await createSosRuntime(context.calibration!, root);
          const research = runtime.run(context, result.response.prediction, referenceTime);
          if (research.receipt.algorithm_hash !== identity.algorithmHash)
            throw new Error('Research source identity changed');
          const payload = {
            context,
            prediction: result.response.prediction,
            ...research,
            reference_time: referenceTime,
            model_signature: modelSignature,
            input_hash: digest(context),
            code_revision: identity.codeRevision,
          };
          const saved = await client.rpc('freeze_compare_monitor', {
            p_baseline: row.id,
            p_signature: monitor,
            p_payload: JSON.stringify(payload),
          });
          if (saved.error) throw new Error('Monitoring capture refused');
          if (saved.data === true) summary.captured++;
          else summary.existing++;
        } catch {
          summary.errors++;
        } // Never print raw private records or database errors.
      }
      if ((data?.length ?? 0) < 1000) break;
    }
  } finally {
    await runtime?.close();
  }
  return summary;
}

async function main() {
  const args = process.argv.slice(2);
  const execute = args.includes('--execute');
  const limitIndex = args.indexOf('--limit');
  const limit = limitIndex < 0 ? 500 : Number(args[limitIndex + 1]);
  if (
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > 500 ||
    args.some((a, i) => a !== '--execute' && a !== '--limit' && !(limitIndex >= 0 && i === limitIndex + 1))
  )
    throw new Error('Use [--execute] [--limit 1..500]');
  const url = process.env.SUPABASE_URL,
    key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) throw new Error('Configure server credentials');
  const client = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
  const summary = await captureMonitoring(client, { limit, execute });
  console.log(JSON.stringify(summary));
  if (summary.errors) process.exitCode = 1;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch(() => {
    console.error('Compare monitoring failed; inspect private diagnostics.');
    process.exitCode = 1;
  });
