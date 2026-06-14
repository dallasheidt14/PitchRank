import type { SupabaseClient } from '@supabase/supabase-js';

export interface ResolvedTeamIds {
  /** Canonical team_id_master after following any incoming merge. */
  canonicalTeamId: string;
  /** Canonical + original + all deprecated IDs, for membership checks. */
  teamIdsToQuery: Set<string>;
  /** Same set as an array, for building PostgREST `.or()` filters. */
  teamIdList: string[];
}

/**
 * Resolve a team_id_master to its canonical team plus every deprecated ID merged
 * into it, so games stored under pre-merge IDs are still included in a team's
 * history. Mirrors api.getTeamGames.
 */
export async function resolveMergedTeamIds(supabase: SupabaseClient, teamId: string): Promise<ResolvedTeamIds> {
  const { data: incomingMerge } = await supabase
    .from('team_merge_map')
    .select('canonical_team_id')
    .eq('deprecated_team_id', teamId)
    .maybeSingle();
  const canonicalTeamId = (incomingMerge as { canonical_team_id?: string } | null)?.canonical_team_id ?? teamId;

  const { data: mergedTeams } = await supabase
    .from('team_merge_map')
    .select('deprecated_team_id')
    .eq('canonical_team_id', canonicalTeamId);

  const teamIdsToQuery = new Set<string>([canonicalTeamId, teamId]);
  ((mergedTeams || []) as { deprecated_team_id: string | null }[]).forEach((m) => {
    if (m.deprecated_team_id) teamIdsToQuery.add(m.deprecated_team_id);
  });

  return { canonicalTeamId, teamIdsToQuery, teamIdList: Array.from(teamIdsToQuery) };
}
