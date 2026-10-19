import { NextRequest, NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import { isId } from '@/lib/mission-control/cleanup';

export const dynamic = 'force-dynamic';

/**
 * Mark a run's review done. Its choices lock: the decisions route refuses further saves, and the
 * collect reads them once it sees owner_done_at. Body: `{ runId }`.
 */
export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const body = await parseJsonBody<{ runId?: unknown }>(request);
  if (body.error) return body.error;
  const runId = body.data?.runId;
  if (!isId(runId)) {
    return NextResponse.json({ error: 'runId is required' }, { status: 400 });
  }

  try {
    return await markDone(runId);
  } catch (error) {
    console.error('[cleanup] Marking the review done failed:', error);
    return NextResponse.json({ error: 'Could not mark the review done' }, { status: 500 });
  }
}

async function markDone(runId: string) {
  const supabase = createServiceSupabase();
  const { data, error } = await supabase
    .from('team_cleanup_runs')
    .update({ owner_done_at: new Date().toISOString(), owner_done_by: 'owner' })
    .eq('run_id', runId)
    .eq('status', 'reviewing')
    .is('owner_done_at', null)
    .select('run_id, owner_done_at, owner_done_by');
  if (error) {
    console.error('[cleanup] Marking the review done failed:', error.message);
    return NextResponse.json({ error: 'Could not mark the review done' }, { status: 500 });
  }
  if (!data?.length) {
    return NextResponse.json({ error: 'The run is not in review, or is already marked done' }, { status: 409 });
  }

  return NextResponse.json({ ownerDoneAt: data[0].owner_done_at, ownerDoneBy: data[0].owner_done_by });
}
