import { NextRequest, NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import {
  MAX_CARDS_PER_WRITE,
  MAX_NOTE_LENGTH,
  isDecision,
  isId,
  isStage,
  type CleanupDecision,
  type CleanupStage,
} from '@/lib/mission-control/cleanup';

export const dynamic = 'force-dynamic';

/**
 * Save the owner's decision, note or swap on cards of a stage's review page.
 *
 * Body: `{ runId, stage, pageRun, cardIds, decision?, note?, swap?, onlyUndecided? }`. A `decision` of null
 * clears it with its time and author; `swap`, on duplicate-team cards only, sets whether the owner keeps the row
 * the pair would retire;
 * `onlyUndecided` leaves a card already decided as it is. Only the owner's lane is written, and only on the
 * page's newest build, while the run is in review and not yet marked done.
 */
export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const body = await parseJsonBody<unknown>(request);
  if (body.error) return body.error;
  if (!body.data || typeof body.data !== 'object' || Array.isArray(body.data)) {
    return NextResponse.json({ error: 'Invalid request body' }, { status: 400 });
  }
  const fields = body.data as Record<string, unknown>;
  const { runId, stage, pageRun, cardIds, decision, note, swap, onlyUndecided } = fields;
  const setsDecision = 'decision' in fields;
  const setsNote = 'note' in fields;
  const setsSwap = 'swap' in fields;

  if (!isId(runId) || !isStage(stage) || !isId(pageRun)) {
    return NextResponse.json({ error: 'runId, stage and pageRun are required' }, { status: 400 });
  }
  if (!Array.isArray(cardIds) || cardIds.length === 0 || cardIds.length > MAX_CARDS_PER_WRITE || !cardIds.every(isId)) {
    return NextResponse.json({ error: `cardIds must list 1 to ${MAX_CARDS_PER_WRITE} cards` }, { status: 400 });
  }
  if (!setsDecision && !setsNote && !setsSwap) {
    return NextResponse.json({ error: 'Nothing to save: send a decision, a note or a swap' }, { status: 400 });
  }
  if (setsDecision && decision !== null && !isDecision(decision)) {
    return NextResponse.json({ error: 'decision must be apply, dont_apply, unsure or null' }, { status: 400 });
  }
  if (setsNote && note !== null && (typeof note !== 'string' || note.trim().length > MAX_NOTE_LENGTH)) {
    return NextResponse.json({ error: `note must be at most ${MAX_NOTE_LENGTH} characters` }, { status: 400 });
  }
  if (setsSwap && (stage !== 'merges' || typeof swap !== 'boolean')) {
    return NextResponse.json({ error: 'swap must be true or false, on a duplicate-team card' }, { status: 400 });
  }
  if (onlyUndecided !== undefined && typeof onlyUndecided !== 'boolean') {
    return NextResponse.json({ error: 'onlyUndecided must be true or false' }, { status: 400 });
  }

  const patch: Record<string, unknown> = {};
  if (setsDecision) {
    const chosen = decision as CleanupDecision | null;
    patch.decision = chosen;
    patch.decided_at = chosen ? new Date().toISOString() : null;
    patch.decided_by_user_id = chosen ? auth.user.id : null;
  }
  if (setsNote) patch.note = typeof note === 'string' && note.trim() ? note.trim() : null;
  if (setsSwap) patch.swap = swap;

  try {
    return await save({ runId, stage, pageRun, cardIds, patch, onlyUndecided: onlyUndecided === true });
  } catch (error) {
    console.error('[cleanup] Saving choices failed:', error);
    return NextResponse.json({ error: 'Could not save the choice' }, { status: 500 });
  }
}

async function save({
  runId,
  stage,
  pageRun,
  cardIds,
  patch,
  onlyUndecided,
}: {
  runId: string;
  stage: CleanupStage;
  pageRun: string;
  cardIds: string[];
  patch: Record<string, unknown>;
  onlyUndecided: boolean;
}) {
  const supabase = createServiceSupabase();
  const { data: run, error: runError } = await supabase
    .from('team_cleanup_runs')
    .select('status, owner_done_at')
    .eq('run_id', runId)
    .maybeSingle();
  if (runError) {
    console.error('[cleanup] Reading the run failed:', runError.message);
    return NextResponse.json({ error: 'Could not read the cleanup run' }, { status: 500 });
  }
  if (!run) return NextResponse.json({ error: 'No such cleanup run' }, { status: 404 });
  // The check and the write below are two statements. One owner saves choices, and the page waits for its
  // queued saves before it marks the review done, so no save of its own lands after Done.
  if (run.owner_done_at) {
    return NextResponse.json({ error: 'The review is marked done, so its choices are locked' }, { status: 409 });
  }
  if (run.status !== 'reviewing') {
    return NextResponse.json({ error: 'The run is not in review' }, { status: 409 });
  }

  const { data: newest, error: buildError } = await supabase
    .from('team_cleanup_cards')
    .select('page_run')
    .eq('run_id', runId)
    .eq('stage', stage)
    .order('created_at', { ascending: false })
    .limit(1);
  if (buildError) {
    console.error('[cleanup] Reading the newest build failed:', buildError.message);
    return NextResponse.json({ error: 'Could not read the review page' }, { status: 500 });
  }
  if (newest?.[0]?.page_run !== pageRun) {
    return NextResponse.json({ error: 'This page was built again since it loaded' }, { status: 409 });
  }

  let write = supabase
    .from('team_cleanup_cards')
    .update(patch)
    .eq('run_id', runId)
    .eq('stage', stage)
    .eq('page_run', pageRun)
    .eq('lane', 'owner')
    .in('card_id', cardIds);
  if (onlyUndecided) write = write.is('decision', null);
  const { data: updated, error: writeError } = await write.select('card_id, decision, note, swap, decided_at');
  if (writeError) {
    console.error('[cleanup] Saving choices failed:', writeError.message);
    return NextResponse.json({ error: 'Could not save the choice' }, { status: 500 });
  }

  return NextResponse.json({ updated: updated ?? [] });
}
