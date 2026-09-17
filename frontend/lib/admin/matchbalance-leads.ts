import 'server-only';
import { createServiceSupabase } from '@/lib/supabase/service';

export interface MatchBalanceLead {
  id: string;
  created_at: string;
  updated_at: string;
  name: string;
  email: string;
  organization: string;
  tournament_name: string;
  event_dates: string;
  team_count: number | null;
  bracket_review_date: string | null;
  event_url: string | null;
  request_type: string;
  notes: string | null;
  source_ip_masked: string | null;
  status: string;
}

export type MatchBalanceLeads = {
  leads: MatchBalanceLead[];
  total: number;
  thisWeek: number;
  awaitingReply: number;
  errors: string[];
};

const LEADS_LIST_LIMIT = 200;

function formatSupabaseError(e: unknown): string {
  if (e && typeof e === 'object' && 'message' in e && typeof (e as { message: unknown }).message === 'string') {
    return (e as { message: string }).message;
  }
  return String(e);
}

/**
 * A failed query degrades only its own figure (0 / empty) and lands in `errors`; postgrest-js resolves
 * a failure as `{ error }` rather than rejecting. Counts come from `count`, never the
 * list's length, so they stay totals once there are more rows than the list shows.
 */
export async function fetchMatchBalanceLeads(): Promise<MatchBalanceLeads> {
  const errors: string[] = [];

  let supabase: ReturnType<typeof createServiceSupabase>;
  try {
    supabase = createServiceSupabase();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    errors.push(`leads client: ${msg}`);
    return { leads: [], total: 0, thisWeek: 0, awaitingReply: 0, errors };
  }

  const sevenDaysAgo = new Date(Date.now() - 7 * 86_400_000).toISOString();

  const [listRes, totalRes, awaitingRes, weekRes] = await Promise.all([
    supabase.from('matchbalance_leads').select('*').order('created_at', { ascending: false }).limit(LEADS_LIST_LIMIT),
    supabase.from('matchbalance_leads').select('id', { count: 'exact', head: true }),
    supabase.from('matchbalance_leads').select('id', { count: 'exact', head: true }).eq('status', 'new'),
    supabase.from('matchbalance_leads').select('id', { count: 'exact', head: true }).gte('created_at', sevenDaysAgo),
  ]);

  const countOf = (label: string, res: { count: number | null; error: unknown }): number => {
    if (res.error) {
      errors.push(`leads ${label}: ${formatSupabaseError(res.error)}`);
      return 0;
    }
    return res.count ?? 0;
  };

  let leads: MatchBalanceLead[] = [];
  if (listRes.error) {
    errors.push(`leads list: ${formatSupabaseError(listRes.error)}`);
  } else {
    leads = (listRes.data ?? []) as MatchBalanceLead[];
  }

  return {
    leads,
    total: countOf('total', totalRes),
    thisWeek: countOf('this week', weekRes),
    awaitingReply: countOf('awaiting reply', awaitingRes),
    errors,
  };
}
