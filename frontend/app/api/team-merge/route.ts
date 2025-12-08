import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * Team Merge API Endpoints
 *
 * POST: Execute a team merge (deprecate one team, redirect to another)
 * DELETE: Revert a team merge (restore a deprecated team)
 * GET: Get merge information for a team
 */

/**
 * Execute a team merge
 *
 * Calls the execute_team_merge() PostgreSQL function which:
 * 1. Validates both teams exist
 * 2. Prevents circular/chain merges
 * 3. Creates the merge map entry
 * 4. Marks the deprecated team as is_deprecated=true
 * 5. Creates an audit log entry
 */
export async function POST(request: NextRequest) {
  try {
    const serviceKey = process.env.SUPABASE_SERVICE_KEY;
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;

    if (!serviceKey || !supabaseUrl) {
      console.error('[team-merge] Missing environment variables');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    // Parse request body
    let requestBody;
    try {
      requestBody = await request.json();
    } catch {
      return NextResponse.json(
        { error: 'Invalid request body' },
        { status: 400 }
      );
    }

    const {
      deprecatedTeamId,
      canonicalTeamId,
      mergedBy,
      mergeReason,
      confidenceScore,
      suggestionSignals,
    } = requestBody;

    // Validate required fields
    if (!deprecatedTeamId || !canonicalTeamId || !mergedBy) {
      return NextResponse.json(
        { error: 'Missing required fields: deprecatedTeamId, canonicalTeamId, mergedBy' },
        { status: 400 }
      );
    }

    // Validate UUIDs
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(deprecatedTeamId) || !uuidRegex.test(canonicalTeamId)) {
      return NextResponse.json(
        { error: 'Invalid team ID format' },
        { status: 400 }
      );
    }

    // Prevent self-merge
    if (deprecatedTeamId === canonicalTeamId) {
      return NextResponse.json(
        { error: 'Cannot merge a team with itself' },
        { status: 400 }
      );
    }

    const supabase = createClient(supabaseUrl, serviceKey);

    // Execute the merge via PostgreSQL function
    const { data: mergeId, error } = await supabase.rpc('execute_team_merge', {
      p_deprecated_team_id: deprecatedTeamId,
      p_canonical_team_id: canonicalTeamId,
      p_merged_by: mergedBy,
      p_merge_reason: mergeReason || null,
    });

    if (error) {
      console.error('[team-merge] Merge failed:', error);

      // Parse PostgreSQL error messages for user-friendly responses
      const message = error.message || 'Unknown error';

      if (message.includes('already deprecated') || message.includes('already merged')) {
        return NextResponse.json(
          { error: 'This team has already been merged' },
          { status: 409 }
        );
      }

      if (message.includes('circular merge') || message.includes('chain')) {
        return NextResponse.json(
          { error: 'Cannot create circular or chain merges. The canonical team is already deprecated.' },
          { status: 400 }
        );
      }

      if (message.includes('does not exist')) {
        return NextResponse.json(
          { error: 'One or both team IDs do not exist' },
          { status: 404 }
        );
      }

      return NextResponse.json(
        { error: `Merge failed: ${message}` },
        { status: 500 }
      );
    }

    // If confidence score and signals were provided (from Option 8), update the merge record
    if (mergeId && (confidenceScore !== undefined || suggestionSignals)) {
      await supabase
        .from('team_merge_map')
        .update({
          confidence_score: confidenceScore || null,
          suggestion_signals: suggestionSignals || null,
        })
        .eq('id', mergeId);
    }

    // Fetch both team names for the response
    const { data: teams } = await supabase
      .from('teams')
      .select('team_id_master, team_name')
      .in('team_id_master', [deprecatedTeamId, canonicalTeamId]);

    const deprecatedTeam = teams?.find(t => t.team_id_master === deprecatedTeamId);
    const canonicalTeam = teams?.find(t => t.team_id_master === canonicalTeamId);

    return NextResponse.json({
      success: true,
      mergeId,
      deprecatedTeamId,
      canonicalTeamId,
      deprecatedTeamName: deprecatedTeam?.team_name || 'Unknown',
      canonicalTeamName: canonicalTeam?.team_name || 'Unknown',
      message: `Successfully merged "${deprecatedTeam?.team_name}" into "${canonicalTeam?.team_name}"`,
    });
  } catch (error) {
    console.error('[team-merge] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}

/**
 * Revert a team merge
 *
 * Calls the revert_team_merge() PostgreSQL function which:
 * 1. Removes the merge map entry
 * 2. Sets is_deprecated=false on the team
 * 3. Creates an audit log entry for the revert
 */
export async function DELETE(request: NextRequest) {
  try {
    const serviceKey = process.env.SUPABASE_SERVICE_KEY;
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;

    if (!serviceKey || !supabaseUrl) {
      console.error('[team-merge] Missing environment variables');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    // Parse request body
    let requestBody;
    try {
      requestBody = await request.json();
    } catch {
      return NextResponse.json(
        { error: 'Invalid request body' },
        { status: 400 }
      );
    }

    const { deprecatedTeamId, revertedBy, revertReason } = requestBody;

    // Validate required fields
    if (!deprecatedTeamId || !revertedBy) {
      return NextResponse.json(
        { error: 'Missing required fields: deprecatedTeamId, revertedBy' },
        { status: 400 }
      );
    }

    // Validate UUID
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(deprecatedTeamId)) {
      return NextResponse.json(
        { error: 'Invalid team ID format' },
        { status: 400 }
      );
    }

    const supabase = createClient(supabaseUrl, serviceKey);

    // Get the team name before reverting
    const { data: team } = await supabase
      .from('teams')
      .select('team_name')
      .eq('team_id_master', deprecatedTeamId)
      .single();

    // Execute the revert via PostgreSQL function
    const { error } = await supabase.rpc('revert_team_merge', {
      p_deprecated_team_id: deprecatedTeamId,
      p_reverted_by: revertedBy,
      p_revert_reason: revertReason || null,
    });

    if (error) {
      console.error('[team-merge] Revert failed:', error);

      const message = error.message || 'Unknown error';

      if (message.includes('not found') || message.includes('not merged')) {
        return NextResponse.json(
          { error: 'This team is not currently merged' },
          { status: 404 }
        );
      }

      return NextResponse.json(
        { error: `Revert failed: ${message}` },
        { status: 500 }
      );
    }

    return NextResponse.json({
      success: true,
      deprecatedTeamId,
      teamName: team?.team_name || 'Unknown',
      message: `Successfully reverted merge for "${team?.team_name}"`,
    });
  } catch (error) {
    console.error('[team-merge] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}

/**
 * Get merge information for a team
 *
 * Returns merge status and details if the team is deprecated
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
    const teamId = searchParams.get('teamId');

    if (!teamId) {
      return NextResponse.json(
        { error: 'Missing teamId query parameter' },
        { status: 400 }
      );
    }

    // Validate UUID
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(teamId)) {
      return NextResponse.json(
        { error: 'Invalid team ID format' },
        { status: 400 }
      );
    }

    const supabase = createClient(supabaseUrl, supabaseAnonKey);

    // Check if team is deprecated
    const { data: team, error: teamError } = await supabase
      .from('teams')
      .select('team_id_master, team_name, is_deprecated')
      .eq('team_id_master', teamId)
      .single();

    if (teamError || !team) {
      return NextResponse.json(
        { error: 'Team not found' },
        { status: 404 }
      );
    }

    if (!team.is_deprecated) {
      return NextResponse.json({
        teamId,
        teamName: team.team_name,
        isDeprecated: false,
        mergeInfo: null,
      });
    }

    // Get merge info from the view
    const { data: mergeInfo } = await supabase
      .from('merged_teams_view')
      .select('*')
      .eq('deprecated_team_id', teamId)
      .single();

    return NextResponse.json({
      teamId,
      teamName: team.team_name,
      isDeprecated: true,
      mergeInfo: mergeInfo || null,
    });
  } catch (error) {
    console.error('[team-merge] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
