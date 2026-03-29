import { createServerSupabase } from '@/lib/supabase/server';
import { NextRequest, NextResponse } from 'next/server';
import { normalizeAgeGroup } from '@/lib/utils';
import { validatePagination } from '@/lib/api/validatePagination';

/**
 * GET /api/rankings/state?state=TX&age=u12&gender=M&limit=1000&offset=0
 *
 * Returns state rankings for a specific (state, age, gender) cohort.
 * Uses the get_state_rankings RPC which filters BEFORE computing ROW_NUMBER(),
 * avoiding the timeout that state_rankings_view causes on large states.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;

  const state = searchParams.get('state');
  const ageParam = searchParams.get('age');
  const gender = searchParams.get('gender');

  // Validate required params
  if (!state || !ageParam || !gender) {
    return NextResponse.json({ error: 'Missing required parameters: state, age, gender' }, { status: 400 });
  }

  // Normalize age group (e.g., "u12" -> 12)
  const normalizedAge = normalizeAgeGroup(ageParam);
  if (normalizedAge === null) {
    return NextResponse.json({ error: `Invalid age group: ${ageParam}` }, { status: 400 });
  }

  // Validate limit/offset
  const pagination = validatePagination(searchParams);
  if ('error' in pagination && pagination.error) return pagination.error;
  const { limit, offset } = pagination as { limit: number; offset: number };

  try {
    const supabase = await createServerSupabase();

    const { data, error } = await supabase.rpc('get_state_rankings', {
      p_state: state.toUpperCase(),
      p_age: String(normalizedAge),
      p_gender: gender,
      p_limit: limit,
      p_offset: offset,
    });

    if (error) {
      console.error('[API /rankings/state] RPC error:', error.message);
      return NextResponse.json({ error: 'Failed to fetch state rankings' }, { status: 500 });
    }

    return NextResponse.json(data || [], {
      headers: {
        'Cache-Control': 'public, s-maxage=120, stale-while-revalidate=300',
      },
    });
  } catch (err) {
    console.error('[API /rankings/state] Unexpected error:', err);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
