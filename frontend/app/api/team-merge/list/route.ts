import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * GET /api/team-merge/list
 *
 * Returns list of recent team merges for admin display
 */
export async function GET() {
  try {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseAnonKey) {
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    const supabase = createClient(supabaseUrl, supabaseAnonKey);

    // Fetch from merged_teams_view which includes all relevant info
    const { data, error } = await supabase
      .from('merged_teams_view')
      .select('*')
      .order('merged_at', { ascending: false })
      .limit(50);

    if (error) {
      console.error('[team-merge/list] Error fetching merges:', error);
      return NextResponse.json(
        { error: 'Failed to fetch merges' },
        { status: 500 }
      );
    }

    return NextResponse.json({
      merges: data || [],
      count: data?.length || 0,
    });
  } catch (error) {
    console.error('[team-merge/list] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
