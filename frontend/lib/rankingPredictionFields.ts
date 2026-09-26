import type { SupabaseClient } from '@supabase/supabase-js';

type RankingListRow = {
  team_id_master?: string | null;
  [key: string]: unknown;
};

type PredictionFieldRow = {
  team_id: string;
  prediction_power_score: number | null;
  power_score_scale_version: string | null;
};

const PREDICTION_FIELD_BATCH_SIZE = 500;

/**
 * Ranking list RPCs intentionally stay optimized for display. Enrich their
 * paginated rows with the versioned compatibility score used by prediction
 * consumers such as the head-to-head infographic.
 *
 * This is deployment-order tolerant: before the migration lands, missing
 * columns leave the legacy rows unchanged and predictors retain their existing
 * power_score_final fallback.
 */
export async function enrichRankingPredictionFields<T extends RankingListRow>(
  supabase: SupabaseClient,
  rows: T[]
): Promise<T[]> {
  const teamIds = rows
    .map((row) => row.team_id_master)
    .filter((teamId): teamId is string => Boolean(teamId));

  if (teamIds.length === 0) return rows;

  const fieldsByTeam = new Map<string, PredictionFieldRow>();
  for (let index = 0; index < teamIds.length; index += PREDICTION_FIELD_BATCH_SIZE) {
    const batch = teamIds.slice(index, index + PREDICTION_FIELD_BATCH_SIZE);
    const { data, error } = await supabase
      .from('rankings_full')
      .select('team_id, prediction_power_score, power_score_scale_version')
      .in('team_id', batch);

    if (error) {
      const message = error.message.toLowerCase();
      const missingNewColumn =
        error.code === '42703' ||
        message.includes('prediction_power_score') ||
        message.includes('power_score_scale_version');
      if (missingNewColumn) return rows;
      throw error;
    }

    for (const fieldRow of (data ?? []) as PredictionFieldRow[]) {
      fieldsByTeam.set(fieldRow.team_id, fieldRow);
    }
  }

  return rows.map((row) => {
    const teamId = row.team_id_master;
    const fields = teamId ? fieldsByTeam.get(teamId) : undefined;
    return fields
      ? {
          ...row,
          prediction_power_score: fields.prediction_power_score,
          power_score_scale_version: fields.power_score_scale_version,
        }
      : row;
  });
}
