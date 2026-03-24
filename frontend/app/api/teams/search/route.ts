import { NextRequest, NextResponse } from 'next/server';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';

// Module-level singleton — reused across requests within the same serverless
// function instance, avoiding per-request client creation overhead.
// This endpoint serves public data (no auth needed), so cookies are unnecessary.
let _supabase: ReturnType<typeof createClient> | null = null;

function getSupabase() {
  if (!_supabase) {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!url || !key) {
      throw new Error('Missing Supabase environment variables');
    }
    _supabase = createClient(url, key);
  }
  return _supabase;
}

/**
 * Build a fresh Supabase search query. Must be called on every retry attempt
 * because Supabase query builders are consumed after execution.
 */
function buildSearchQuery(
  supabase: SupabaseClient,
  sanitizedQuery: string,
  limit: number,
  filters: { ageGroup: string | null; gender: string | null; stateCode: string | null }
) {
  let query = supabase
    .from('teams')
    .select('team_id_master, team_name, club_name, age_group, gender, state_code, state')
    .eq('is_deprecated', false)
    .or(`team_name.ilike.%${sanitizedQuery}%,club_name.ilike.%${sanitizedQuery}%`)
    .limit(limit);

  if (filters.ageGroup) {
    query = query.eq('age_group', filters.ageGroup);
  }
  if (filters.gender) {
    query = query.eq('gender', filters.gender);
  }
  if (filters.stateCode) {
    query = query.eq('state_code', filters.stateCode);
  }

  return query;
}

const MAX_RETRIES = 3;

/**
 * Search teams by name, club, age group, gender, or state
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const query = searchParams.get('q') || '';
    const ageGroup = searchParams.get('ageGroup');
    const gender = searchParams.get('gender');
    const stateCode = searchParams.get('stateCode');
    const limit = Math.min(parseInt(searchParams.get('limit') || '20', 10), 100);

    if (!query || query.trim().length < 2) {
      return NextResponse.json({ teams: [] });
    }

    // Sanitize query: whitelist alphanumeric, spaces, hyphens, apostrophes
    // The Supabase JS client handles escaping for PostgREST internally —
    // do NOT double apostrophes here as that breaks literal matches (e.g. O'Brien)
    const sanitizedQuery = query
      .replace(/[^a-zA-Z0-9\s\-']/g, '')
      .trim();
    if (sanitizedQuery.length < 2) {
      return NextResponse.json({ teams: [] });
    }

    const supabase = getSupabase();
    const filters = { ageGroup, gender, stateCode };
    const startTime = Date.now();

    // Retry with backoff to absorb transient Supabase connection issues
    let lastError: { message?: string; code?: string; details?: string; hint?: string } | null = null;
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      const teamsQuery = buildSearchQuery(supabase, sanitizedQuery, limit, filters);
      const { data: teams, error } = await teamsQuery;

      if (!error) {
        const duration = Date.now() - startTime;
        if (duration > 2000) {
          console.warn('[teams/search] Slow query:', {
            query: sanitizedQuery,
            duration: `${duration}ms`,
            attempt: attempt + 1,
            resultCount: teams?.length ?? 0,
          });
        }

        return NextResponse.json({ teams: teams || [] }, {
          headers: {
            'Cache-Control': 'public, s-maxage=60, stale-while-revalidate=120',
          },
        });
      }

      lastError = error;
      console.warn(`[teams/search] Supabase attempt ${attempt + 1}/${MAX_RETRIES} failed:`, {
        message: error.message,
        code: error.code,
        details: error.details,
        hint: error.hint,
        query: sanitizedQuery,
      });

      if (attempt < MAX_RETRIES - 1) {
        await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
      }
    }

    // All retries exhausted
    const duration = Date.now() - startTime;
    console.error('[teams/search] All retries failed:', {
      message: lastError?.message,
      code: lastError?.code,
      details: lastError?.details,
      hint: lastError?.hint,
      query: sanitizedQuery,
      duration: `${duration}ms`,
    });
    return NextResponse.json(
      { error: 'Failed to search teams' },
      { status: 500 }
    );
  } catch (error) {
    console.error('[teams/search] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
