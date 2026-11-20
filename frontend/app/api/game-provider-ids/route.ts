import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { isValidUuid } from '@/lib/validation';
import { NextResponse } from 'next/server';

const MAX_GAME_IDS = 150;

export async function POST(req: Request) {
  try {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

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
      return NextResponse.json({ games: [] });
    }

    const { data, error } = await createServiceSupabase()
      .from('games')
      .select('id, home_provider_id, away_provider_id')
      .in('id', validatedGameIds);

    if (error) {
      console.error('Error fetching game provider ids:', error);
      return NextResponse.json({ error: 'Failed to fetch game provider ids' }, { status: 500 });
    }

    return NextResponse.json({ games: data ?? [] });
  } catch (error) {
    console.error('Game provider ids route error:', error);
    return NextResponse.json({ error: 'Failed to load game provider ids' }, { status: 500 });
  }
}
