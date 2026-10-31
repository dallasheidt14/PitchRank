import { NextRequest, NextResponse } from 'next/server';
import { BUSINESS_TIMEZONE } from '@/lib/admin/timezone';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import {
  appliedChange,
  changeText,
  isId,
  stageReviews,
  type AppliedRun,
  type CardRow,
  type CardUndo,
} from '@/lib/mission-control/cleanup';

export const dynamic = 'force-dynamic';

/** Postgres' unique_violation: uq_team_cleanup_card_undos_one_pending already holds a pending undo of this card. */
const UNIQUE_VIOLATION = '23505';
const PAGE_SIZE = 1000;

type Supabase = ReturnType<typeof createServiceSupabase>;
type Run = { run_id: string; status: string; owner_done_at: string | null };

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

/** The run in review and the last finished run: the two the loop runs undos for. */
async function undoableRuns(supabase: Supabase): Promise<Run[]> {
  const [open, finished] = await Promise.all([
    supabase.from('team_cleanup_runs').select('run_id, status, owner_done_at').eq('status', 'reviewing'),
    supabase
      .from('team_cleanup_runs')
      .select('run_id, status, owner_done_at')
      .eq('status', 'done')
      .order('run_id', { ascending: false })
      .limit(1),
  ]);
  if (open.error || finished.error) throw new Error((open.error ?? finished.error)!.message);
  return [...(open.data ?? []), ...(finished.data ?? [])] as Run[];
}

/** Whether the run's Apply choices stand: its review is done, or it has finished. */
function ownerDone(run: Run): boolean {
  return run.status === 'done' || !!run.owner_done_at;
}

/** Each change the run in review and the last finished run applied, with its latest one-card undo. */
export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  try {
    const supabase = createServiceSupabase();
    const runs: AppliedRun[] = [];
    for (const run of await undoableRuns(supabase)) runs.push(await appliedRun(supabase, run));
    return NextResponse.json({ runs });
  } catch (error) {
    console.error('[cleanup] Reading the applied changes failed:', error);
    return NextResponse.json({ error: 'Could not read the applied changes' }, { status: 500 });
  }
}

async function appliedRun(supabase: Supabase, run: Run): Promise<AppliedRun> {
  const rows: CardRow[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const { data, error } = await supabase
      .from('team_cleanup_cards')
      .select('card_id, stage, lane, page_run, position, card, decision, note, swap, decided_at, created_at')
      .eq('run_id', run.run_id)
      .order('card_id')
      .range(offset, offset + PAGE_SIZE - 1);
    if (error) throw new Error(error.message);
    rows.push(...((data ?? []) as CardRow[]));
    if (!data || data.length < PAGE_SIZE) break;
  }
  const undos = await latestCardUndos(supabase, run.run_id);
  const changes = stageReviews(rows)
    .flatMap((stage) => [...stage.auto, ...stage.cards])
    .filter((row) => appliedChange(row, ownerDone(run)))
    .map((row) => ({
      cardId: row.card_id,
      stage: row.stage,
      lane: row.lane,
      text: changeText(row),
      undo: undos.get(row.card_id) ?? null,
    }));
  return { runId: run.run_id, open: run.status !== 'done', changes };
}

/** Each card's latest undo request on a run; none before team_cleanup_card_undos exists. */
async function latestCardUndos(supabase: Supabase, runId: string): Promise<Map<string, CardUndo>> {
  const { data, error } = await supabase
    .from('team_cleanup_card_undos')
    .select('card_id, status, requested_at, handled_at, result')
    .eq('run_id', runId)
    .order('requested_at', { ascending: false });
  const latest = new Map<string, CardUndo>();
  if (error) {
    console.error('[cleanup] Reading the card undos failed:', error.message);
    return latest;
  }
  for (const r of data ?? []) {
    if (latest.has(r.card_id)) continue;
    latest.set(r.card_id, {
      status: r.status,
      requestedLabel: businessTime(r.requested_at) ?? '',
      handledLabel: businessTime(r.handled_at),
      result: r.result,
    });
  }
  return latest;
}

/**
 * Ask the cleanup loop to undo one card's change, and with `decline` to record it as not to propose again. Only
 * for a change the run in review or the last finished run applied. Body: `{ runId, cardId, decline }`.
 */
export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const body = await parseJsonBody<{ runId?: unknown; cardId?: unknown; decline?: unknown }>(request);
  if (body.error) return body.error;
  const { runId, cardId, decline } = body.data ?? {};
  if (!isId(runId) || !isId(cardId) || typeof decline !== 'boolean') {
    return NextResponse.json({ error: 'runId, cardId and decline are required' }, { status: 400 });
  }

  try {
    return await fileUndo(runId, cardId, decline, auth.user.id);
  } catch (error) {
    console.error('[cleanup] Asking for a card undo failed:', error);
    return NextResponse.json({ error: 'Could not ask for the undo' }, { status: 500 });
  }
}

async function fileUndo(runId: string, cardId: string, decline: boolean, userId: string) {
  const supabase = createServiceSupabase();
  const run = (await undoableRuns(supabase)).find((r) => r.run_id === runId);
  if (!run) {
    return NextResponse.json(
      { error: 'Only a change of the run in review or the last finished run can be undone from here' },
      { status: 409 }
    );
  }
  const { data: cards, error: cardError } = await supabase
    .from('team_cleanup_cards')
    .select('card_id, stage, lane, page_run, position, card, decision, note, swap, decided_at, created_at')
    .eq('run_id', runId)
    .eq('card_id', cardId);
  if (cardError) {
    console.error('[cleanup] Reading the card for an undo failed:', cardError.message);
    return NextResponse.json({ error: 'Could not ask for the undo' }, { status: 500 });
  }
  const card = (cards ?? [])[0] as CardRow | undefined;
  if (!card) return NextResponse.json({ error: 'No such card in that run' }, { status: 404 });
  if (!appliedChange(card, ownerDone(run))) {
    return NextResponse.json({ error: 'That card has changed nothing to undo' }, { status: 409 });
  }

  const { error } = await supabase
    .from('team_cleanup_card_undos')
    .insert({ run_id: runId, card_id: cardId, decline, requested_by_user_id: userId });
  if (error?.code === UNIQUE_VIOLATION) {
    return NextResponse.json({ error: 'An undo of this change is already waiting' }, { status: 409 });
  }
  if (error) {
    console.error('[cleanup] Asking for a card undo failed:', error.message);
    return NextResponse.json({ error: 'Could not ask for the undo' }, { status: 500 });
  }
  return NextResponse.json({ requested: true });
}
