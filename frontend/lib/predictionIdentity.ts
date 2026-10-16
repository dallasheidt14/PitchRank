import 'server-only';
import type { SupabaseClient } from '@supabase/supabase-js';

type Merge = { deprecated_team_id: string; canonical_team_id: string };

async function mergeRows(db: SupabaseClient, field: keyof Merge, ids: string[]): Promise<Merge[]> {
  const rows: Merge[] = [];
  const unique = [...new Set(ids)].sort();
  for (let start = 0; start < unique.length; start += 100) {
    for (let offset = 0; ; offset += 1000) {
      const { data, error } = await db
        .from('team_merge_map')
        .select('deprecated_team_id, canonical_team_id')
        .in(field, unique.slice(start, start + 100))
        .order('deprecated_team_id', { ascending: true })
        .range(offset, offset + 999);
      if (error) throw error;
      rows.push(
        ...(data ?? []).map((row) => ({
          deprecated_team_id: row.deprecated_team_id.toLowerCase(),
          canonical_team_id: row.canonical_team_id?.toLowerCase(),
        }))
      );
      if ((data?.length ?? 0) < 1000) break;
    }
  }
  return rows;
}

/** Follow every merge hop; cycles and conflicting identities fail closed. */
export async function canonicalPredictionIds(db: SupabaseClient, ids: string[]): Promise<Map<string, string>> {
  const edges = new Map<string, string>();
  const visited = new Set<string>();
  let frontier = [...new Set(ids.map((id) => id.toLowerCase()))].sort();
  for (let depth = 0; frontier.length; depth++) {
    if (depth >= 100) throw new Error('Prediction merge chain exceeds the safety limit');
    const rows = await mergeRows(db, 'deprecated_team_id', frontier);
    frontier.forEach((id) => visited.add(id));
    for (const row of rows) {
      if (
        !row.canonical_team_id ||
        (edges.has(row.deprecated_team_id) && edges.get(row.deprecated_team_id) !== row.canonical_team_id)
      ) {
        throw new Error('Conflicting prediction team merge');
      }
      edges.set(row.deprecated_team_id, row.canonical_team_id);
    }
    frontier = [...new Set(rows.map((row) => row.canonical_team_id))].filter((id) => !visited.has(id)).sort();
  }
  const resolved = new Map<string, string>();
  for (const id of visited) {
    const path = new Set<string>();
    let current = id;
    while (edges.has(current)) {
      if (path.has(current)) throw new Error('Cyclic prediction team merge');
      path.add(current);
      current = edges.get(current)!;
    }
    resolved.set(id, current);
  }
  for (const id of ids) resolved.set(id, resolved.get(id.toLowerCase())!);
  return resolved;
}

export async function predictionIdentityClosure(db: SupabaseClient, teamId: string) {
  const canonicalTeamId = (await canonicalPredictionIds(db, [teamId])).get(teamId)!;
  const ids = new Set([canonicalTeamId]);
  let frontier = [canonicalTeamId];
  for (let depth = 0; frontier.length; depth++) {
    if (depth >= 100) throw new Error('Prediction alias closure exceeds the safety limit');
    const rows = await mergeRows(db, 'canonical_team_id', frontier);
    frontier = rows.map((row) => row.deprecated_team_id).filter((id) => !ids.has(id));
    frontier.forEach((id) => ids.add(id));
  }
  return { canonicalTeamId, allTeamIds: [...ids].sort() };
}
