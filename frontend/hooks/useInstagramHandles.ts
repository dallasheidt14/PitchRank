import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';

export interface InstagramHandle {
  team_id: string;
  club_name: string | null;
  handle: string;
  profile_level: 'club' | 'team';
}

/**
 * Fetch approved/confirmed Instagram handles for a set of team IDs.
 * Returns a map: team_id → { clubHandle, teamHandle }
 */
export function useInstagramHandles(teamIds: string[]) {
  return useQuery<Map<string, { clubHandle: string | null; teamHandle: string | null }>>({
    queryKey: ['instagram-handles', teamIds.join(',')],
    enabled: teamIds.length > 0,
    queryFn: async () => {
      // Batch to 100 IDs max per query (Supabase URI limit)
      const batchSize = 100;
      const allRows: InstagramHandle[] = [];

      for (let i = 0; i < teamIds.length; i += batchSize) {
        const batch = teamIds.slice(i, i + batchSize);
        const { data, error } = await supabase
          .from('team_instagram_handles')
          .select('team_id, club_name, handle, profile_level')
          .in('team_id', batch);

        if (error) {
          console.error('[useInstagramHandles] Error:', error.message);
          throw error;
        }
        if (data) {
          allRows.push(...(data as InstagramHandle[]));
        }
      }

      // Build lookup map: team_id → handles
      const handleMap = new Map<string, { clubHandle: string | null; teamHandle: string | null }>();
      for (const row of allRows) {
        const existing = handleMap.get(row.team_id) || { clubHandle: null, teamHandle: null };
        if (row.profile_level === 'club') {
          existing.clubHandle = row.handle;
        } else if (row.profile_level === 'team') {
          existing.teamHandle = row.handle;
        }
        handleMap.set(row.team_id, existing);
      }

      return handleMap;
    },
    staleTime: 10 * 60 * 1000, // 10 minutes - handles don't change often
    gcTime: 30 * 60 * 1000,
  });
}

/**
 * Get the best Instagram handle for a team (prefer team-level, fallback to club-level).
 */
export function getBestHandle(
  handleMap: Map<string, { clubHandle: string | null; teamHandle: string | null }>,
  teamId: string
): string | null {
  const entry = handleMap.get(teamId);
  if (!entry) return null;
  return entry.teamHandle || entry.clubHandle || null;
}

/**
 * Collect unique @handles for a list of team IDs, formatted for captions.
 * Returns both team-level and club-level, deduplicated.
 */
export function collectHandlesForCaption(
  handleMap: Map<string, { clubHandle: string | null; teamHandle: string | null }>,
  teamIds: string[]
): string[] {
  const seen = new Set<string>();
  const handles: string[] = [];

  for (const id of teamIds) {
    const entry = handleMap.get(id);
    if (!entry) continue;
    // Prefer team handle, also include club handle
    for (const h of [entry.teamHandle, entry.clubHandle]) {
      if (h && !seen.has(h.toLowerCase())) {
        seen.add(h.toLowerCase());
        handles.push(`@${h}`);
      }
    }
  }

  return handles;
}
