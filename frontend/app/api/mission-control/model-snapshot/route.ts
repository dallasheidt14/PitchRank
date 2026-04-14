import { NextResponse } from 'next/server';
import { buildMissionControlSnapshot, type ProspectiveSnapshotRow } from '@/lib/mission-control/modelSnapshot';
import type { TrainingRunSummary } from '@/types/mission-control';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';

export const dynamic = 'force-dynamic';

const PROSPECTIVE_PAGE_SIZE = 1000;
const TRAINING_RUN_LIMIT = 8;

type TrainingRunRow = {
  created_at: string;
  workflow_run_id: number | string;
  workflow_run_attempt: number | string;
  git_sha: string | null;
  model_dir: string;
  model_version: string;
  lookback_days: number | null;
  limit_value: number | null;
  test_ratio: number | null;
  min_examples: number | null;
  requested_probability_strategy: string | null;
  selected_probability_strategy: string | null;
  calibration_enabled: boolean | null;
  calibration_method: string | null;
  draw_calibration_method: string | null;
  games_seen: number | null;
  games_used: number | null;
  examples_built: number | null;
  unique_snapshot_dates_used: number | null;
  winner_accuracy: number | null;
  draw_recall: number | null;
  predicted_draw_rate: number | null;
  log_loss: number | null;
  margin_mae: number | null;
  exact_score_accuracy: number | null;
  calibrated_log_loss: number | null;
  calibrated_draw_recall: number | null;
  calibrated_brier_score: number | null;
};

function isMissingTable(error: unknown, tableName: string): boolean {
  const message = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase();
  return (message.includes('could not find the table') || message.includes('schema cache')) && message.includes(tableName.toLowerCase());
}

async function fetchAllProspectiveRows(): Promise<ProspectiveSnapshotRow[]> {
  const supabase = createServiceSupabase();
  const rows: ProspectiveSnapshotRow[] = [];

  for (let offset = 0; ; offset += PROSPECTIVE_PAGE_SIZE) {
    const { data, error } = await supabase
      .from('prospective_match_predictions')
      .select(
        'fixture_key, game_date, resolution_status, heuristic_prediction_status, heuristic_model_version, heuristic_prediction, heuristic_predicted_at, offline_prediction_status, offline_model_version, offline_prediction, offline_predicted_at, actual_home_score, actual_away_score, actual_outcome, evaluation_status'
      )
      .order('game_date', { ascending: false })
      .range(offset, offset + PROSPECTIVE_PAGE_SIZE - 1);

    if (error) throw error;
    const batch = (data ?? []) as ProspectiveSnapshotRow[];
    rows.push(...batch);
    if (batch.length < PROSPECTIVE_PAGE_SIZE) break;
  }

  return rows;
}

async function fetchPredictionFeatureHistoryCount(): Promise<number | null> {
  const supabase = createServiceSupabase();
  const { count, error } = await supabase.from('prediction_feature_history').select('team_id', { count: 'exact', head: true });
  if (error) throw error;
  return count ?? null;
}

async function fetchScoredGamesCount(filters?: { fromDate?: string }): Promise<number | null> {
  const supabase = createServiceSupabase();
  let query = supabase.from('games').select('id', { count: 'exact', head: true }).not('home_score', 'is', null).not('away_score', 'is', null);
  if (filters?.fromDate) {
    query = query.gte('game_date', filters.fromDate);
  }
  const { count, error } = await query;
  if (error) throw error;
  return count ?? null;
}

async function fetchPitCoverage() {
  const supabase = createServiceSupabase();
  const [{ data: firstSnapshotRows, error: firstError }, { data: lastSnapshotRows, error: lastError }, snapshotRows] =
    await Promise.all([
      supabase.from('prediction_feature_history').select('snapshot_date').order('snapshot_date', { ascending: true }).limit(1),
      supabase.from('prediction_feature_history').select('snapshot_date').order('snapshot_date', { ascending: false }).limit(1),
      fetchPredictionFeatureHistoryCount(),
    ]);

  if (firstError) throw firstError;
  if (lastError) throw lastError;

  const windowStart = firstSnapshotRows?.[0]?.snapshot_date ?? null;
  const windowEnd = lastSnapshotRows?.[0]?.snapshot_date ?? null;

  const now = new Date();
  const last365 = new Date(Date.UTC(now.getUTCFullYear() - 1, now.getUTCMonth(), now.getUTCDate())).toISOString().slice(0, 10);

  const [totalScoredGames, trainableScoredGames, last365ScoredGames, last365TrainableGames] = await Promise.all([
    fetchScoredGamesCount(),
    windowStart ? fetchScoredGamesCount({ fromDate: windowStart }) : Promise.resolve(null),
    fetchScoredGamesCount({ fromDate: last365 }),
    windowStart ? fetchScoredGamesCount({ fromDate: windowStart > last365 ? windowStart : last365 }) : Promise.resolve(null),
  ]);

  return {
    snapshotRows,
    windowStart,
    windowEnd,
    totalScoredGames,
    trainableScoredGames,
    last365ScoredGames,
    last365TrainableGames,
  };
}

async function fetchTrainingRuns(): Promise<TrainingRunSummary[]> {
  const supabase = createServiceSupabase();
  try {
    const { data, error } = await supabase
      .from('model_training_runs')
      .select(
        'created_at, workflow_run_id, workflow_run_attempt, git_sha, model_dir, model_version, lookback_days, limit_value, test_ratio, min_examples, requested_probability_strategy, selected_probability_strategy, calibration_enabled, calibration_method, draw_calibration_method, games_seen, games_used, examples_built, unique_snapshot_dates_used, winner_accuracy, draw_recall, predicted_draw_rate, log_loss, margin_mae, exact_score_accuracy, calibrated_log_loss, calibrated_draw_recall, calibrated_brier_score'
      )
      .order('workflow_run_id', { ascending: false })
      .limit(TRAINING_RUN_LIMIT);

    if (error) throw error;

    return ((data ?? []) as TrainingRunRow[]).map((row) => ({
      createdAt: row.created_at,
      workflowRunId: Number(row.workflow_run_id),
      workflowRunAttempt: Number(row.workflow_run_attempt),
      gitSha: row.git_sha,
      modelDir: row.model_dir,
      modelVersion: row.model_version,
      lookbackDays: row.lookback_days,
      limitValue: row.limit_value,
      testRatio: row.test_ratio,
      minExamples: row.min_examples,
      requestedProbabilityStrategy: row.requested_probability_strategy,
      selectedProbabilityStrategy: row.selected_probability_strategy,
      calibrationEnabled: Boolean(row.calibration_enabled),
      calibrationMethod: row.calibration_method,
      drawCalibrationMethod: row.draw_calibration_method,
      gamesSeen: row.games_seen,
      gamesUsed: row.games_used,
      examplesBuilt: row.examples_built,
      uniqueSnapshotDatesUsed: row.unique_snapshot_dates_used,
      winnerAccuracy: row.winner_accuracy,
      drawRecall: row.draw_recall,
      predictedDrawRate: row.predicted_draw_rate,
      logLoss: row.log_loss,
      marginMae: row.margin_mae,
      exactScoreAccuracy: row.exact_score_accuracy,
      calibratedLogLoss: row.calibrated_log_loss,
      calibratedDrawRecall: row.calibrated_draw_recall,
      calibratedBrierScore: row.calibrated_brier_score,
    }));
  } catch (error) {
    if (isMissingTable(error, 'model_training_runs')) {
      return [];
    }
    throw error;
  }
}

export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  try {
    const [rows, pitCoverage, trainingRuns] = await Promise.all([fetchAllProspectiveRows(), fetchPitCoverage(), fetchTrainingRuns()]);
    const snapshot = buildMissionControlSnapshot(rows, pitCoverage, trainingRuns);
    return NextResponse.json(snapshot);
  } catch (error) {
    console.error('Mission control snapshot error:', error);
    return NextResponse.json({ error: 'Failed to build mission control snapshot' }, { status: 500 });
  }
}
