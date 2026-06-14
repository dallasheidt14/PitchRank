import { createServiceSupabase } from '@/lib/supabase/service';
import { requirePremium } from '@/lib/api/requirePremium';
import { isValidUuid } from '@/lib/validation';
import { NextResponse } from 'next/server';

const MAX_GAME_IDS = 150;

const SELECT_COLUMNS = [
  'team_id',
  'game_uuid',
  'game_id',
  'opp_id',
  'game_date',
  'gf',
  'ga',
  'team_mu',
  'team_sigma',
  'opp_mu',
  'opp_sigma',
  'expected_outcome',
  'actual_outcome',
  'outcome_surprise',
  'g_factor',
  'recency_weight',
  'rating_contribution',
  'off_residual',
  'def_residual',
  'last_calculated',
  'created_at',
].join(', ');

export async function POST(req: Request, { params }: { params: Promise<{ teamId: string }> }) {
  try {
    const auth = await requirePremium();
    if (auth.error) return auth.error;

    const { teamId } = await params;
    if (!isValidUuid(teamId)) {
      return NextResponse.json({ error: 'Invalid team ID' }, { status: 400 });
    }
    const supabase = createServiceSupabase();

    const body = (await req.json().catch(() => null)) as { gameIds?: unknown } | null;
    if (!body || !Array.isArray(body.gameIds)) {
      return NextResponse.json({ error: 'gameIds must be an array' }, { status: 400 });
    }

    if (body.gameIds.length > MAX_GAME_IDS) {
      return NextResponse.json({ error: `Too many game IDs requested (max ${MAX_GAME_IDS})` }, { status: 400 });
    }

    const uniqueGameIds = Array.from(new Set(body.gameIds));
    if (!uniqueGameIds.every((gameId) => typeof gameId === 'string' && isValidUuid(gameId))) {
      return NextResponse.json({ error: 'All game IDs must be valid UUIDs' }, { status: 400 });
    }
    const validatedGameIds = uniqueGameIds as string[];

    if (validatedGameIds.length === 0) {
      return NextResponse.json({ breakdowns: [] });
    }

    const { data, error } = await supabase
      .from('game_explainability')
      .select(SELECT_COLUMNS)
      .eq('team_id', teamId)
      .in('game_uuid', validatedGameIds)
      .order('game_date', { ascending: false });

    if (error) {
      console.error('Error fetching game explainability:', error);
      return NextResponse.json({ error: 'Failed to fetch game explainability' }, { status: 500 });
    }

    return NextResponse.json({ breakdowns: data ?? [] });
  } catch (error) {
    console.error('Game explainability route error:', error);
    return NextResponse.json({ error: 'Failed to load game explainability' }, { status: 500 });
  }
}
