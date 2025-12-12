import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * Search teams by name, club, age group, gender, or state
 */
export async function GET(request: NextRequest) {
  try {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseAnonKey) {
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    const { searchParams } = new URL(request.url);
    const query = searchParams.get('q') || '';
    const ageGroup = searchParams.get('ageGroup');
    const gender = searchParams.get('gender');
    const stateCode = searchParams.get('stateCode');
    const limit = parseInt(searchParams.get('limit') || '20', 10);

    if (!query || query.trim().length < 2) {
      return NextResponse.json({ teams: [] });
    }

    const supabase = createClient(supabaseUrl, supabaseAnonKey);

    // Build query
    let teamsQuery = supabase
      .from('teams')
      .select('team_id_master, team_name, club_name, age_group, gender, state_code, state')
      .eq('is_deprecated', false) // Only show active teams
      .or(`team_name.ilike.%${query}%,club_name.ilike.%${query}%`)
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
      console.error('[teams/search] Error:', error);
      return NextResponse.json(
        { error: 'Failed to search teams' },
        { status: 500 }
      );
    }

    return NextResponse.json({ teams: teams || [] });
  } catch (error) {
    console.error('[teams/search] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}

