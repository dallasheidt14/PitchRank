import { NextResponse } from 'next/server';
import { BUSINESS_TIMEZONE } from '@/lib/admin/timezone';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { stageReviews, type CardRow, type CleanupReview } from '@/lib/mission-control/cleanup';

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
  if (!run) return NextResponse.json({ run: null, stages: [] } satisfies CleanupReview);

  const rows: CardRow[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const { data, error } = await supabase
      .from('team_cleanup_cards')
      .select('card_id, stage, lane, page_run, position, card, decision, note, decided_at, created_at')
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
  } satisfies CleanupReview);
}
