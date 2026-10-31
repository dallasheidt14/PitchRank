import { NextRequest, NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import {
  MAX_CARDS_PER_WRITE,
  MAX_NOTE_LENGTH,
  SPOT_CHECK_WEEKS,
  cleanWeeks,
  cleanupWeek,
  isId,
  isSpotVerdict,
  type PairCard,
  type SpotCheckReview,
  type SpotCheckRun,
  type SpotVerdict,
} from '@/lib/mission-control/cleanup';

export const dynamic = 'force-dynamic';

/** PostgREST's answer for a table no migration has created yet. */
const TABLE_MISSING = 'PGRST205';
const PAGE_SIZE = 1000;

/** The newest runs' samples of their automatic merges, with the owner's verdicts and the clean weeks in a row. */
export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  try {
    return await readSpotChecks();
  } catch (error) {
    console.error('[cleanup] Reading the spot-checks failed:', error);
    return NextResponse.json({ error: 'Could not read the spot-checks' }, { status: 500 });
  }
}

async function readSpotChecks() {
  const supabase = createServiceSupabase();
  // Every check, so each run's sample is whole: a run holds ten at most, and the loop files one run a week.
  const rows: Array<Record<string, unknown>> = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const { data, error } = await supabase
      .from('team_cleanup_spot_checks')
      .select('id, run_id, position, card_id, verdict, note')
      .order('id')
      .range(offset, offset + PAGE_SIZE - 1);
    if (error?.code === TABLE_MISSING) {
      return NextResponse.json({ runs: [], cleanWeeks: 0 } satisfies SpotCheckReview);
    }
    if (error) {
      console.error('[cleanup] Reading the spot-checks failed:', error.message);
      return NextResponse.json({ error: 'Could not read the spot-checks' }, { status: 500 });
    }
    rows.push(...(data ?? []));
    if (!data || data.length < PAGE_SIZE) break;
  }

  const ids = rows.map((row) => row.card_id as string);
  const byId = new Map<string, { card: PairCard; swap: boolean }>();
  for (let i = 0; i < ids.length; i += MAX_CARDS_PER_WRITE) {
    const { data: cards, error } = await supabase
      .from('team_cleanup_cards')
      .select('card_id, card, swap')
      .in('card_id', ids.slice(i, i + MAX_CARDS_PER_WRITE));
    if (error) {
      console.error('[cleanup] Reading the spot-checked cards failed:', error.message);
      return NextResponse.json({ error: 'Could not read the spot-checks' }, { status: 500 });
    }
    for (const row of cards ?? []) byId.set(row.card_id as string, { card: row.card as PairCard, swap: row.swap });
  }

  const runs = new Map<string, SpotCheckRun>();
  for (const row of rows) {
    const runId = row.run_id as string;
    const found = byId.get(row.card_id as string);
    if (!found) continue;
    if (!runs.has(runId)) runs.set(runId, { runId, checks: [] });
    runs.get(runId)!.checks.push({
      cardId: row.card_id as string,
      position: row.position as number,
      card: found.card,
      swap: found.swap,
      verdict: row.verdict as SpotVerdict | null,
      note: row.note as string | null,
    });
  }
  const ordered = [...runs.values()].sort((a, b) => b.runId.localeCompare(a.runId));
  for (const run of ordered) run.checks.sort((a, b) => a.position - b.position);
  const shown = new Set([...new Set(ordered.map((run) => cleanupWeek(run.runId)))].slice(0, SPOT_CHECK_WEEKS));
  return NextResponse.json({
    runs: ordered.filter((run) => shown.has(cleanupWeek(run.runId))),
    cleanWeeks: cleanWeeks(ordered),
  } satisfies SpotCheckReview);
}

/**
 * Record the owner's verdict on one sampled merge, and its note; a null verdict takes the verdict back. Body:
 * `{ runId, cardId, verdict, note }`.
 */
export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const body = await parseJsonBody<{ runId?: unknown; cardId?: unknown; verdict?: unknown; note?: unknown }>(request);
  if (body.error) return body.error;
  const { runId, cardId, verdict = null, note = null } = body.data ?? {};
  if (!isId(runId) || !isId(cardId) || (verdict !== null && !isSpotVerdict(verdict))) {
    return NextResponse.json(
      { error: 'runId, cardId and a verdict of right, wrong or null are required' },
      { status: 400 }
    );
  }
  if (note !== null && (typeof note !== 'string' || note.length > MAX_NOTE_LENGTH)) {
    return NextResponse.json({ error: `A note is text of at most ${MAX_NOTE_LENGTH} characters` }, { status: 400 });
  }

  try {
    return await judge(
      runId,
      cardId,
      verdict as SpotVerdict | null,
      (note as string | null)?.trim() || null,
      auth.user.id
    );
  } catch (error) {
    console.error('[cleanup] Recording a spot-check failed:', error);
    return NextResponse.json({ error: 'Could not record the verdict' }, { status: 500 });
  }
}

async function judge(runId: string, cardId: string, verdict: SpotVerdict | null, note: string | null, userId: string) {
  const supabase = createServiceSupabase();
  const { data, error } = await supabase
    .from('team_cleanup_spot_checks')
    .update({
      verdict,
      note,
      judged_at: verdict ? new Date().toISOString() : null,
      judged_by_user_id: verdict ? userId : null,
    })
    .eq('run_id', runId)
    .eq('card_id', cardId)
    .select('card_id, verdict, note');
  if (error) {
    console.error('[cleanup] Recording a spot-check failed:', error.message);
    return NextResponse.json({ error: 'Could not record the verdict' }, { status: 500 });
  }
  if (!data?.length) {
    return NextResponse.json({ error: "That merge is not in the run's spot-check" }, { status: 404 });
  }
  return NextResponse.json({ verdict: data[0].verdict, note: data[0].note });
}
