import type { PostgrestError, SupabaseClient } from '@supabase/supabase-js';
import { resolveMergedTeamIds } from '@/lib/team-merge';

/** enqueue_scrape_request raises Postgres' unique_violation when the team's active request uses another GotSport registration or date. */
export const SCRAPE_REQUEST_REFUSED = '23505';

/**
 * Looks under the team's whole merge group, as enqueue_scrape_request does, because a request can be
 * filed under an id from before a merge. requestId is null when no pending request was found.
 */
export async function promoteWaitingScrapeRequest(
  supabase: SupabaseClient,
  teamId: string
): Promise<{ requestId: string | null; error: PostgrestError | null }> {
  const { teamIdList } = await resolveMergedTeamIds(supabase, teamId);
  const promoted = await supabase
    .from('scrape_requests')
    .update({ priority: 1 })
    .in('team_id_master', teamIdList)
    .eq('status', 'pending')
    .select('id');
  return { requestId: (promoted.data?.[0]?.id as string | undefined) ?? null, error: promoted.error };
}
