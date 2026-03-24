import { NextRequest, NextResponse } from 'next/server';
import { createServerSupabase } from '@/lib/supabase/server';

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

    const supabase = await createServerSupabase();

    // Build query using sanitized input to prevent PostgREST filter injection
    let teamsQuery = supabase
      .from('teams')
      .select('team_id_master, team_name, club_name, age_group, gender, state_code, state')
      .eq('is_deprecated', false) // Only show active teams
      .or(`team_name.ilike.%${sanitizedQuery}%,club_name.ilike.%${sanitizedQuery}%`)
      .limit(limit);

    // Add filters if provided
    if (ageGroup) {
      teamsQuery = teamsQuery.eq('age_group', ageGroup);
    }
    if (gender) {
      teamsQuery = teamsQuery.eq('gender', gender);
    }
    if (stateCode) {
      teamsQuery = teamsQuery.eq('state_code', stateCode);
    }

    const { data: teams, error } = await teamsQuery;

    if (error) {
      console.error('[teams/search] Supabase query error:', {
        message: error.message,
        code: error.code,
        details: error.details,
        hint: error.hint,
        query: sanitizedQuery,
      });
      return NextResponse.json(
        { error: 'Failed to search teams' },
        { status: 500 }
      );
    }

    return NextResponse.json({ teams: teams || [] }, {
      headers: {
        'Cache-Control': 'public, s-maxage=60, stale-while-revalidate=120',
      },
    });
  } catch (error) {
    console.error('[teams/search] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}

