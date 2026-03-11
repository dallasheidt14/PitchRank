import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * GET /api/debug-merge?team=<uuid>
 * Diagnostic: check all merge map entries involving a team (as deprecated OR canonical)
 */
export async function GET(request: NextRequest) {
  const teamId = request.nextUrl.searchParams.get('team');
  if (!teamId) {
    return NextResponse.json({ error: 'Missing ?team= param' }, { status: 400 });
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!supabaseUrl || !supabaseAnonKey) {
    return NextResponse.json({ error: 'Missing env' }, { status: 500 });
  }

  const supabase = createClient(supabaseUrl, supabaseAnonKey);

  // Check both directions
  const [asDeprecated, asCanonical, teamInfo] = await Promise.all([
    supabase
      .from('team_merge_map')
      .select('id,deprecated_team_id,canonical_team_id,created_at')
      .eq('deprecated_team_id', teamId),
    supabase
      .from('team_merge_map')
      .select('id,deprecated_team_id,canonical_team_id,created_at')
      .eq('canonical_team_id', teamId),
    supabase
      .from('teams')
      .select('team_id_master,team_name,club_name,is_deprecated')
      .eq('team_id_master', teamId)
      .maybeSingle(),
  ]);

  return NextResponse.json({
    teamId,
    team: teamInfo.data,
    asDeprecated: asDeprecated.data || [],
    asCanonical: asCanonical.data || [],
  });
}
