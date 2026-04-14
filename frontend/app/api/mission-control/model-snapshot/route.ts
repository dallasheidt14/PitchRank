import { NextResponse } from 'next/server';
import { buildMissionControlSnapshot, type ProspectiveSnapshotRow } from '@/lib/mission-control/modelSnapshot';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';

export const dynamic = 'force-dynamic';

const PROSPECTIVE_PAGE_SIZE = 1000;

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

export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  try {
    const [rows, pitCoverage] = await Promise.all([fetchAllProspectiveRows(), fetchPitCoverage()]);
    const snapshot = buildMissionControlSnapshot(rows, pitCoverage);
    return NextResponse.json(snapshot);
  } catch (error) {
    console.error('Mission control snapshot error:', error);
    return NextResponse.json({ error: 'Failed to build mission control snapshot' }, { status: 500 });
  }
}
