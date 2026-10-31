import { NextRequest, NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import {
  MAX_NOTE_LENGTH,
  SPOT_CHECK_RUNS,
  SPOT_CHECK_SIZE,
  cleanWeeks,
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
  const { data: rows, error } = await supabase
    .from('team_cleanup_spot_checks')
    .select('run_id, position, card_id, verdict, note')
    .order('run_id', { ascending: false })
    .limit(SPOT_CHECK_RUNS * SPOT_CHECK_SIZE);
  if (error?.code === TABLE_MISSING) {
    return NextResponse.json({ runs: [], cleanWeeks: 0 } satisfies SpotCheckReview);
  }
  if (error) {
    console.error('[cleanup] Reading the spot-checks failed:', error.message);
    return NextResponse.json({ error: 'Could not read the spot-checks' }, { status: 500 });
  }

  const ids = (rows ?? []).map((row) => row.card_id as string);
  const { data: cards, error: cardError } = ids.length
    ? await supabase.from('team_cleanup_cards').select('card_id, card, swap').in('card_id', ids)
    : { data: [], error: null };
  if (cardError) {
    console.error('[cleanup] Reading the spot-checked cards failed:', cardError.message);
    return NextResponse.json({ error: 'Could not read the spot-checks' }, { status: 500 });
  }
  const byId = new Map((cards ?? []).map((row) => [row.card_id as string, row]));

  const runs = new Map<string, SpotCheckRun>();
  for (const row of rows ?? []) {
    const found = byId.get(row.card_id);
    if (!found) continue;
    if (!runs.has(row.run_id)) runs.set(row.run_id, { runId: row.run_id, checks: [] });
    runs.get(row.run_id)!.checks.push({
      cardId: row.card_id,
      position: row.position,
      card: found.card as PairCard,
      swap: found.swap as boolean,
      verdict: row.verdict as SpotVerdict | null,
      note: row.note,
    });
  }
  const ordered = [...runs.values()].sort((a, b) => b.runId.localeCompare(a.runId));
  for (const run of ordered) run.checks.sort((a, b) => a.position - b.position);
  return NextResponse.json({ runs: ordered, cleanWeeks: cleanWeeks(ordered) } satisfies SpotCheckReview);
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
