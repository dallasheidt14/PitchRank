import 'server-only';

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import type { SupabaseClient } from '@supabase/supabase-js';
import { buildMatchPredictionWithShadowContext, MATCH_PREDICTION_VERSION } from './matchPredictionService';
import { AppError } from './errors';
import { stableJson } from './canonicalJson';

export type CaptureOptions = {
  status: 'pending' | 'error';
  limit: number;
  execute: boolean;
  concurrency: number;
  budgetMinutes: number;
  source: 'all' | 'database';
  selection?: 'balanced' | 'chronological';
};
export type ProspectiveFixture = {
  id: string;
  fixture_key: string;
  game_date: string;
  source_game_id: string | null;
  provider_code: string;
  home_team_master_id: string | null;
  away_team_master_id: string | null;
  fixture_payload: { cohort?: string; source_snapshot?: Record<string, unknown> };
};
export const digest = (value: unknown) => createHash('sha256').update(stableJson(value)).digest('hex');

export function captureCodeIdentity() {
  const root = path.basename(process.cwd()) === 'frontend' ? process.cwd() : path.join(process.cwd(), 'frontend');
  const files = [
    'matchPredictor.ts',
    'confidenceEngine.ts',
    'teamAge.ts',
    'matchPredictionService.ts',
    'predictionIdentity.ts',
    'calibrationLoader.ts',
    'matchEvidence.ts',
  ];
  return {
    codeRevision: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8', windowsHide: true }).trim(),
    algorithmHash: digest(
      files.map((name) => [name, readFileSync(path.join(root, 'lib', name), 'utf8').replace(/\r\n/g, '\n')])
    ),
  };
}
export async function fetchCaptureRows(client: SupabaseClient, options: CaptureOptions, now: Date) {
  const today = now.toISOString().slice(0, 10);
  const end = new Date(now.getTime() + 7 * 86400000).toISOString().slice(0, 10);
  const rows: ProspectiveFixture[] = [];
  for (let offset = 0; ; offset += 1000) {
    let query = client
      .from('prospective_match_predictions')
      .select(
        'id,fixture_key,game_date,source_game_id,provider_code,home_team_master_id,away_team_master_id,fixture_payload'
      )
      .eq('resolution_status', 'resolved')
      .eq('heuristic_prediction_status', options.status)
      .gt('game_date', today)
      .lte('game_date', end)
      .order('game_date')
      .order('id');
    if (options.source === 'database') query = query.eq('source_system', 'database_games');
    const { data, error } = await query.range(offset, offset + 999);
    if (error) throw error;
    rows.push(...(data ?? []));
    if ((data?.length ?? 0) < 1000) break;
  }
  if (options.selection === 'balanced') {
    const root = path.basename(process.cwd()) === 'frontend' ? path.dirname(process.cwd()) : process.cwd();
    const ordered: unknown = JSON.parse(
      execFileSync('python', [path.join(root, 'scripts/select_compare_capture.py')], {
        input: JSON.stringify(rows),
        encoding: 'utf8',
        windowsHide: true,
        timeout: 30000,
        maxBuffer: 16 * 1024 * 1024,
      })
    );
    const byId = new Map(rows.map((row) => [row.id, row]));
    if (
      !Array.isArray(ordered) ||
      ordered.length !== rows.length ||
      new Set(ordered).size !== rows.length ||
      ordered.some((id) => typeof id !== 'string' || !byId.has(id))
    ) {
      throw new Error('Sampler did not cover the exact pending fixture set');
    }
    return (ordered as string[]).map((id) => byId.get(id)!);
  }
  return rows.sort(
    (a, b) =>
      a.game_date.localeCompare(b.game_date) ||
      createHash('sha256')
        .update(a.fixture_key)
        .digest('hex')
        .localeCompare(createHash('sha256').update(b.fixture_key).digest('hex'))
  );
}
async function checkSource(client: SupabaseClient, row: ProspectiveFixture) {
  if (!row.source_game_id) return;
  const { data, error } = await client
    .from('games')
    .select(
      'game_date,home_team_master_id,away_team_master_id,provider_id,source_url,home_score,away_score,is_excluded'
    )
    .eq('id', row.source_game_id)
    .maybeSingle();
  if (error) throw error;
  const source = row.fixture_payload?.source_snapshot;
  if (
    !data ||
    !source ||
    data.is_excluded !== false ||
    data.home_score !== null ||
    data.away_score !== null ||
    (['game_date', 'home_team_master_id', 'away_team_master_id', 'provider_id', 'source_url'] as const).some(
      (key) => data[key] !== source[key]
    )
  ) {
    throw new Error('source_fixture_changed');
  }
}
export async function captureForecasts(
  client: SupabaseClient,
  options: CaptureOptions,
  dependencies: {
    now?: () => Date;
    predict?: typeof buildMatchPredictionWithShadowContext;
    identity?: ReturnType<typeof captureCodeIdentity>;
  } = {}
) {
  if (
    !Number.isSafeInteger(options.limit) ||
    options.limit < 1 ||
    options.limit > 500 ||
    !Number.isSafeInteger(options.concurrency) ||
    options.concurrency < 1 ||
    options.concurrency > 4 ||
    !Number.isFinite(options.budgetMinutes) ||
    options.budgetMinutes <= 0 ||
    options.budgetMinutes > 45
  ) {
    throw new Error('Invalid capture limits');
  }
  const now = dependencies.now ?? (() => new Date());
  const predict = dependencies.predict ?? buildMatchPredictionWithShadowContext;
  const identity = dependencies.identity ?? captureCodeIdentity();
  const started = now();
  const rows = await fetchCaptureRows(client, options, started);
  const selected = rows.slice(0, options.limit);
  const summary = {
    dryRun: !options.execute,
    requestedStatus: options.status,
    requestedLimit: options.limit,
    selection: options.selection ?? 'chronological',
    heuristicModelVersion: MATCH_PREDICTION_VERSION,
    codeRevision: identity.codeRevision,
    eligible: rows.length,
    selected: selected.length,
    processed: 0,
    frozen: 0,
    frozenIds: [] as string[],
    wouldFreeze: 0,
    skipped: 0,
    errored: 0,
    deadlineReached: false,
    coverage: {} as Record<string, Record<string, number>>,
    errors: [] as Array<{ fixtureKey: string; reason: string }>,
  };
  function count(row: ProspectiveFixture, name: string) {
    const key = row.provider_code + '|' + (row.fixture_payload?.cohort ?? 'unknown');
    const bucket = (summary.coverage[key] ??= {});
    bucket[name] = (bucket[name] ?? 0) + 1;
  }
  rows.forEach((row) => count(row, 'eligible'));
  selected.forEach((row) => count(row, 'selected'));
  let cursor = 0;
  async function worker() {
    while (cursor < selected.length) {
      if (now().getTime() - started.getTime() >= options.budgetMinutes * 60000) {
        summary.deadlineReached = true;
        return;
      }
      const row = selected[cursor++];
      summary.processed++;
      try {
        if (row.game_date <= now().toISOString().slice(0, 10)) throw new Error('match_day_started');
        if (!row.home_team_master_id || !row.away_team_master_id) throw new Error('missing_team_identity');
        await checkSource(client, row);
        const result = await predict(client, row.home_team_master_id, row.away_team_master_id, client, {
          freezeInputs: true,
        });
        const context = result.shadowContext;
        if (
          !context.calibration ||
          Object.values(context.calibration).some((value) => value === null) ||
          !context.preOutcomeCalibration ||
          !context.frozenEvidence
        )
          throw new Error('incomplete_capture_inputs');
        if (context.predictorVersion !== MATCH_PREDICTION_VERSION) throw new Error('model_version_mismatch');
        const payload = {
          modelVersion: MATCH_PREDICTION_VERSION,
          codeRevision: identity.codeRevision,
          modelSignature: digest({ algorithm: identity.algorithmHash, calibration: context.calibration }),
          response: result.response,
          shadowContext: context,
          inputHash: digest({ fixture: row, context }),
        };
        if (row.game_date <= now().toISOString().slice(0, 10)) throw new Error('match_day_started');
        if (!options.execute) {
          summary.wouldFreeze++;
          count(row, 'wouldFreeze');
          continue;
        }
        const { data, error } = await client.rpc('freeze_prospective_forecast', {
          p_fixture_id: row.id,
          p_model_version: MATCH_PREDICTION_VERSION,
          p_prediction: payload,
        });
        if (error) throw error;
        if (data === true) {
          summary.frozen++;
          summary.frozenIds.push(row.id);
          count(row, 'frozen');
        } else {
          summary.skipped++;
          count(row, 'skipped');
        }
      } catch (error) {
        const reason =
          error instanceof Error ? error.message : String((error as { message?: string })?.message ?? error);
        const ineligible =
          (error instanceof AppError &&
            ['prediction_unavailable', 'prediction_metadata_conflict', 'same_team'].includes(error.code ?? '')) ||
          ['match_day_started', 'source_fixture_changed', 'missing_team_identity'].includes(reason);
        if (ineligible) summary.skipped++;
        else summary.errored++;
        count(row, ineligible ? 'skipped' : 'errored');
        summary.errors.push({ fixtureKey: row.fixture_key, reason });
        if (options.execute) {
          const update = await client
            .from('prospective_match_predictions')
            .update({
              heuristic_prediction_status: ineligible ? 'skipped' : 'error',
              heuristic_prediction: { error: { message: reason } },
            })
            .eq('id', row.id)
            .in('heuristic_prediction_status', ['pending', 'error']);
          if (update.error) throw update.error;
        }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(options.concurrency, selected.length) }, worker));
  summary.frozenIds.sort();
  return summary;
}
