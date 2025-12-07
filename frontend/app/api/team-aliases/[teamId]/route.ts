import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * Get all aliases for a team from team_alias_map
 * Returns provider info and alias details
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ teamId: string }> }
) {
  try {
    const { teamId } = await params;

    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseAnonKey) {
      console.error('[team-aliases] Missing environment variables');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    const supabase = createClient(supabaseUrl, supabaseAnonKey);

    // Fetch all aliases for this team with provider info
    const { data: aliases, error } = await supabase
      .from('team_alias_map')
      .select(`
        id,
        provider_team_id,
        match_method,
        match_confidence,
        review_status,
        created_at,
        provider:providers(id, name)
      `)
      .eq('team_id_master', teamId)
      .eq('review_status', 'approved')
      .order('created_at', { ascending: false });

    if (error) {
      console.error('[team-aliases] Error fetching aliases:', error);
      return NextResponse.json(
        { error: 'Failed to fetch team aliases' },
        { status: 500 }
      );
    }

    return NextResponse.json({
      success: true,
      aliases: aliases || [],
    });
  } catch (error) {
    console.error('[team-aliases] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
