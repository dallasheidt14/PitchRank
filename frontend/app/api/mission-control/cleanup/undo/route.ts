import { NextRequest, NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import {
  CLEANUP_LANES,
  CLEANUP_STAGES,
  isId,
  type CleanupLane,
  type CleanupStage,
} from '@/lib/mission-control/cleanup';

export const dynamic = 'force-dynamic';

/** Postgres' unique_violation: uq_team_cleanup_requests_one_pending already holds a pending undo of this lane. */
const UNIQUE_VIOLATION = '23505';

/**
 * Ask the cleanup loop to undo one lane of a stage: the owner's choices, or the changes the evidence settled.
 * The hourly loop runs it once the lane has applied and records the result. Only for the run in review.
 * Body: `{ runId, stage, lane }`.
 */
export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const body = await parseJsonBody<{ runId?: unknown; stage?: unknown; lane?: unknown }>(request);
  if (body.error) return body.error;
  const { runId, stage, lane } = body.data ?? {};
  if (!isId(runId) || !CLEANUP_STAGES.includes(stage as CleanupStage) || !CLEANUP_LANES.includes(lane as CleanupLane)) {
    return NextResponse.json({ error: 'runId, stage and lane are required' }, { status: 400 });
  }

  try {
    return await fileUndo(runId, stage as CleanupStage, lane as CleanupLane, auth.user.id);
  } catch (error) {
    console.error('[cleanup] Asking for an undo failed:', error);
    return NextResponse.json({ error: 'Could not ask for the undo' }, { status: 500 });
  }
}

async function fileUndo(runId: string, stage: CleanupStage, lane: CleanupLane, userId: string) {
  const supabase = createServiceSupabase();
  const { data: runs, error: runError } = await supabase.from('team_cleanup_runs').select('status').eq('run_id', runId);
  if (runError) {
    console.error('[cleanup] Reading the run for an undo failed:', runError.message);
    return NextResponse.json({ error: 'Could not ask for the undo' }, { status: 500 });
  }
  if (runs?.[0]?.status !== 'reviewing') {
    return NextResponse.json({ error: 'Only the run in review can be undone from here' }, { status: 409 });
  }

  const { error } = await supabase
    .from('team_cleanup_requests')
    .insert({ run_id: runId, stage, lane, requested_by_user_id: userId });
  if (error?.code === UNIQUE_VIOLATION) {
    return NextResponse.json({ error: 'An undo of these changes is already waiting' }, { status: 409 });
  }
  if (error) {
    console.error('[cleanup] Asking for an undo failed:', error.message);
    return NextResponse.json({ error: 'Could not ask for the undo' }, { status: 500 });
  }
  return NextResponse.json({ requested: true });
}
