import { NextResponse } from 'next/server';
import { BUSINESS_TIMEZONE } from '@/lib/admin/timezone';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import {
  CLEANUP_STAGES,
  stageReviews,
  type CardRow,
  type CleanupReview,
  type CleanupStage,
  type PreviousRun,
  type UndoRequest,
} from '@/lib/mission-control/cleanup';

export const dynamic = 'force-dynamic';

// team_cleanup_runs keeps at most one run in these states (uq_team_cleanup_runs_one_open).
const OPEN_STATUSES = ['proposing', 'reviewing', 'applying', 'second_lap'];
const PAGE_SIZE = 1000;

function businessTime(iso: string | null): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: BUSINESS_TIMEZONE,
  });
}

/** The open cleanup run and the newest published build of each of its stage pages. */
export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  try {
    return await readReview();
  } catch (error) {
    console.error('[cleanup] Reading the review failed:', error);
    return NextResponse.json({ error: 'Could not read the cleanup review' }, { status: 500 });
  }
}

async function readReview() {
  const supabase = createServiceSupabase();
  const { data: runs, error: runError } = await supabase
    .from('team_cleanup_runs')
    .select('run_id, scope, status, owner_done_at, owner_done_by')
    .in('status', OPEN_STATUSES);
  if (runError) {
    console.error('[cleanup] Reading the open run failed:', runError.message);
    return NextResponse.json({ error: 'Could not read the cleanup run' }, { status: 500 });
  }
  const run = runs?.[0];
  const previous = await previousRun(supabase);
  if (!run) return NextResponse.json({ run: null, stages: [], undo: [], previous } satisfies CleanupReview);

  const rows: CardRow[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const { data, error } = await supabase
      .from('team_cleanup_cards')
      .select('card_id, stage, lane, page_run, position, card, decision, note, swap, decided_at, created_at')
      .eq('run_id', run.run_id)
      .order('card_id')
      .range(offset, offset + PAGE_SIZE - 1);
    if (error) {
      console.error('[cleanup] Reading the cards failed:', error.message);
      return NextResponse.json({ error: 'Could not read the cleanup cards' }, { status: 500 });
    }
    rows.push(...((data ?? []) as CardRow[]));
    if (!data || data.length < PAGE_SIZE) break;
  }

  return NextResponse.json({
    run: {
      runId: run.run_id,
      states: run.scope?.states ?? [],
      status: run.status,
      ownerDoneAt: run.owner_done_at,
      ownerDoneBy: run.owner_done_by,
      ownerDoneLabel: businessTime(run.owner_done_at),
    },
    stages: stageReviews(rows),
    undo: await latestUndo(supabase, run.run_id),
    previous,
  } satisfies CleanupReview);
}

type Supabase = ReturnType<typeof createServiceSupabase>;

/**
 * The last finished run, whose changes the page offers to undo. A run's last lane applies and the run closes in
 * one hourly tick, so its undo can only be asked for after the close. Failing reads give none, not no page.
 */
async function previousRun(supabase: Supabase): Promise<PreviousRun | null> {
  const { data, error } = await supabase
    .from('team_cleanup_runs')
    .select('run_id')
    .eq('status', 'done')
    .order('run_id', { ascending: false })
    .limit(1);
  if (error) console.error('[cleanup] Reading the last finished run failed:', error.message);
  const runId = error ? undefined : data?.[0]?.run_id;
  return runId ? { runId, stages: await stagesOf(supabase, runId), undo: await latestUndo(supabase, runId) } : null;
}

/** The stages a run published cards for, in run order; a stage whose cards cannot be read is left out. */
async function stagesOf(supabase: Supabase, runId: string): Promise<CleanupStage[]> {
  const published = await Promise.all(
    CLEANUP_STAGES.map(async (stage) => {
      const { data, error } = await supabase
        .from('team_cleanup_cards')
        .select('card_id')
        .eq('run_id', runId)
        .eq('stage', stage)
        .limit(1);
      if (error) console.error(`[cleanup] Reading the ${stage} cards of run ${runId} failed:`, error.message);
      return !error && !!data?.length;
    })
  );
  return CLEANUP_STAGES.filter((_, i) => published[i]);
}

/**
 * Each stage and lane's latest undo request on a run. The cards matter more than the undo statuses: a failed
 * read, as before team_cleanup_requests exists, gives none rather than no page.
 */
async function latestUndo(supabase: Supabase, runId: string): Promise<UndoRequest[]> {
  const { data, error } = await supabase
    .from('team_cleanup_requests')
    .select('stage, lane, status, requested_at, handled_at, result')
    .eq('run_id', runId)
    .order('requested_at', { ascending: false });
  if (error) {
    console.error('[cleanup] Reading the undo requests failed:', error.message);
    return [];
  }
  // Newest first, so the first seen per stage and lane is its latest.
  const latest = new Map<string, UndoRequest>();
  for (const r of data ?? []) {
    const key = `${r.stage}|${r.lane}`;
    if (latest.has(key)) continue;
    latest.set(key, {
      stage: r.stage,
      lane: r.lane,
      status: r.status,
      requestedLabel: businessTime(r.requested_at) ?? '',
      handledLabel: businessTime(r.handled_at),
      result: r.result,
    });
  }
  return [...latest.values()];
}
