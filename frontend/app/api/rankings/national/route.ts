import { createServerSupabase } from '@/lib/supabase/server';
import { NextRequest, NextResponse } from 'next/server';
import { normalizeAgeGroup } from '@/lib/utils';

function isMissingNationalRankingsRpc(error: { code?: string | null } | null): boolean {
  return error?.code === 'PGRST202';
}

/**
 * GET /api/rankings/national?age=u12&gender=M&limit=1000&offset=0
 *
 * Returns national rankings for a specific (age, gender) cohort.
 * Uses the get_national_rankings RPC so filters apply on rankings_full before
 * pagination, avoiding heavy rankings_view scans for large national cohorts.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;

  const ageParam = searchParams.get('age');
  const gender = searchParams.get('gender');
  const limit = parseInt(searchParams.get('limit') || '1000', 10);
  const offset = parseInt(searchParams.get('offset') || '0', 10);

  if (!ageParam || !gender) {
    return NextResponse.json({ error: 'Missing required parameters: age, gender' }, { status: 400 });
  }

  const normalizedAge = normalizeAgeGroup(ageParam);
  if (normalizedAge === null) {
    return NextResponse.json({ error: 'Invalid age group format' }, { status: 400 });
  }

  if (isNaN(limit) || limit < 1 || limit > 5000) {
    return NextResponse.json({ error: 'limit must be between 1 and 5000' }, { status: 400 });
  }
  if (isNaN(offset) || offset < 0) {
    return NextResponse.json({ error: 'offset must be >= 0' }, { status: 400 });
  }

  try {
    const supabase = await createServerSupabase();
    const rpcResult = await supabase.rpc('get_national_rankings', {
      p_age: String(normalizedAge),
      p_gender: gender,
      p_limit: limit,
      p_offset: offset,
    });

    if (rpcResult.error && !isMissingNationalRankingsRpc(rpcResult.error)) {
      console.error('[API /rankings/national] RPC error:', rpcResult.error.message);
      return NextResponse.json({ error: 'Failed to fetch national rankings' }, { status: 500 });
    }

    if (rpcResult.error && isMissingNationalRankingsRpc(rpcResult.error)) {
      console.warn('[API /rankings/national] RPC missing, falling back to rankings_view');

      const { data, error } = await supabase
        .from('rankings_view')
        .select('*')
        .in('status', ['Active', 'Not Enough Ranked Games'])
        .eq('age', normalizedAge)
        .eq('gender', gender)
        .order('rank_in_cohort_final', { ascending: true, nullsFirst: false })
        .order('team_id_master', { ascending: true })
        .range(offset, offset + limit - 1);

      if (error) {
        console.error('[API /rankings/national] Fallback query error:', error.message);
        return NextResponse.json({ error: 'Failed to fetch national rankings' }, { status: 500 });
      }

      return NextResponse.json(data || [], {
        headers: {
          'Cache-Control': 'public, s-maxage=120, stale-while-revalidate=300',
        },
      });
    }

    return NextResponse.json(rpcResult.data || [], {
      headers: {
        'Cache-Control': 'public, s-maxage=120, stale-while-revalidate=300',
      },
    });
  } catch (err) {
    console.error('[API /rankings/national] Unexpected error:', err);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
