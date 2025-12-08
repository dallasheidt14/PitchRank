/**
 * Team merge resolution utilities for frontend.
 *
 * This module provides utilities for resolving deprecated team IDs
 * to their canonical form, checking merge status, and handling
 * team page redirects.
 *
 * Part of Phase 3 of the team merge implementation.
 */

import { supabase } from './supabaseClient';

/**
 * Team merge mapping from deprecated to canonical team
 */
export interface TeamMergeMapping {
  deprecated_team_id: string;
  canonical_team_id: string;
  merged_at: string;
  merge_reason: string | null;
}

/**
 * Detailed merge information including team names
 */
export interface TeamMergeInfo {
  merge_id: string;
  deprecated_team_id: string;
  deprecated_team_name: string;
  deprecated_club_name: string | null;
  canonical_team_id: string;
  canonical_team_name: string;
  canonical_club_name: string | null;
  merged_at: string;
  merged_by: string;
  merge_reason: string | null;
  confidence_score: number | null;
  games_with_deprecated_id: number;
}

/**
 * Result of checking if a team is deprecated
 */
export interface DeprecationCheckResult {
  is_deprecated: boolean;
  canonical_team_id: string | null;
  merge_info: TeamMergeInfo | null;
}

/**
 * Check if a team ID is deprecated and get its canonical replacement.
 *
 * Use this on team pages to redirect users from deprecated teams.
 *
 * @param teamId - The team ID to check
 * @returns DeprecationCheckResult with redirect info if deprecated
 */
export async function checkTeamDeprecation(
  teamId: string
): Promise<DeprecationCheckResult> {
  try {
    // First check if team exists and is deprecated via teams table
    const { data: team, error: teamError } = await supabase
      .from('teams')
      .select('team_id_master, is_deprecated')
      .eq('team_id_master', teamId)
      .single();

    if (teamError || !team) {
      return {
        is_deprecated: false,
        canonical_team_id: null,
        merge_info: null,
      };
    }

    if (!team.is_deprecated) {
      return {
        is_deprecated: false,
        canonical_team_id: null,
        merge_info: null,
      };
    }

    // Team is deprecated - get merge info from the view
    const { data: mergeInfo, error: mergeError } = await supabase
      .from('merged_teams_view')
      .select('*')
      .eq('deprecated_team_id', teamId)
      .single();

    if (mergeError || !mergeInfo) {
      // Team is marked deprecated but no merge record found
      // This shouldn't happen, but handle gracefully
      return {
        is_deprecated: true,
        canonical_team_id: null,
        merge_info: null,
      };
    }

    return {
      is_deprecated: true,
      canonical_team_id: mergeInfo.canonical_team_id,
      merge_info: mergeInfo as TeamMergeInfo,
    };
  } catch (error) {
    console.error('Error checking team deprecation:', error);
    return {
      is_deprecated: false,
      canonical_team_id: null,
      merge_info: null,
    };
  }
}

/**
 * Resolve a team ID to its canonical form.
 *
 * If the team is deprecated, returns the canonical team ID.
 * Otherwise, returns the original ID.
 *
 * @param teamId - The team ID to resolve
 * @returns The canonical team ID
 */
export async function resolveTeamId(teamId: string): Promise<string> {
  try {
    const { data, error } = await supabase
      .from('team_merge_map')
      .select('canonical_team_id')
      .eq('deprecated_team_id', teamId)
      .single();

    if (error || !data) {
      return teamId; // Not deprecated, return original
    }

    return data.canonical_team_id;
  } catch {
    return teamId; // On error, return original
  }
}

/**
 * Resolve multiple team IDs to their canonical forms in a single query.
 *
 * More efficient than calling resolveTeamId multiple times.
 *
 * @param teamIds - Array of team IDs to resolve
 * @returns Map of original ID to canonical ID
 */
export async function resolveTeamIds(
  teamIds: string[]
): Promise<Map<string, string>> {
  const result = new Map<string, string>();

  // Initialize all IDs to themselves (default if not merged)
  teamIds.forEach(id => result.set(id, id));

  if (teamIds.length === 0) {
    return result;
  }

  try {
    const { data, error } = await supabase
      .from('team_merge_map')
      .select('deprecated_team_id, canonical_team_id')
      .in('deprecated_team_id', teamIds);

    if (error || !data) {
      return result;
    }

    // Update merged teams in the map
    data.forEach(row => {
      result.set(row.deprecated_team_id, row.canonical_team_id);
    });

    return result;
  } catch {
    return result;
  }
}

/**
 * Get all merged teams for admin display.
 *
 * Returns detailed information about all team merges.
 *
 * @returns Array of TeamMergeInfo objects
 */
export async function getMergedTeams(): Promise<TeamMergeInfo[]> {
  try {
    const { data, error } = await supabase
      .from('merged_teams_view')
      .select('*')
      .order('merged_at', { ascending: false });

    if (error || !data) {
      console.error('Error fetching merged teams:', error);
      return [];
    }

    return data as TeamMergeInfo[];
  } catch (error) {
    console.error('Error fetching merged teams:', error);
    return [];
  }
}

/**
 * Get recent merge activity for admin dashboard.
 *
 * @param limit - Maximum number of records to return
 * @returns Array of recent merge activity
 */
export async function getRecentMergeActivity(limit: number = 20): Promise<TeamMergeInfo[]> {
  try {
    const { data, error } = await supabase
      .from('merged_teams_view')
      .select('*')
      .order('merged_at', { ascending: false })
      .limit(limit);

    if (error || !data) {
      console.error('Error fetching merge activity:', error);
      return [];
    }

    return data as TeamMergeInfo[];
  } catch (error) {
    console.error('Error fetching merge activity:', error);
    return [];
  }
}

/**
 * Execute a team merge via the database function.
 *
 * This calls the execute_team_merge() PostgreSQL function which:
 * 1. Validates both teams exist
 * 2. Prevents circular/chain merges
 * 3. Creates the merge record
 * 4. Marks the deprecated team as is_deprecated=true
 * 5. Creates an audit log entry
 *
 * @param deprecatedTeamId - Team ID to deprecate
 * @param canonicalTeamId - Team ID to merge into
 * @param mergedBy - User email performing the merge
 * @param mergeReason - Optional reason for the merge
 * @returns The merge map record ID if successful
 */
export async function executeTeamMerge(
  deprecatedTeamId: string,
  canonicalTeamId: string,
  mergedBy: string,
  mergeReason?: string
): Promise<{ success: boolean; mergeId?: string; error?: string }> {
  try {
    const { data, error } = await supabase.rpc('execute_team_merge', {
      p_deprecated_team_id: deprecatedTeamId,
      p_canonical_team_id: canonicalTeamId,
      p_merged_by: mergedBy,
      p_merge_reason: mergeReason || null,
    });

    if (error) {
      console.error('Error executing team merge:', error);
      return { success: false, error: error.message };
    }

    return { success: true, mergeId: data as string };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('Error executing team merge:', message);
    return { success: false, error: message };
  }
}

/**
 * Revert a team merge via the database function.
 *
 * This calls the revert_team_merge() PostgreSQL function which:
 * 1. Removes the merge map entry
 * 2. Sets is_deprecated=false on the team
 * 3. Creates an audit log entry for the revert
 *
 * @param deprecatedTeamId - The deprecated team ID to restore
 * @param revertedBy - User email performing the revert
 * @param revertReason - Optional reason for the revert
 * @returns Success status
 */
export async function revertTeamMerge(
  deprecatedTeamId: string,
  revertedBy: string,
  revertReason?: string
): Promise<{ success: boolean; error?: string }> {
  try {
    const { error } = await supabase.rpc('revert_team_merge', {
      p_deprecated_team_id: deprecatedTeamId,
      p_reverted_by: revertedBy,
      p_revert_reason: revertReason || null,
    });

    if (error) {
      console.error('Error reverting team merge:', error);
      return { success: false, error: error.message };
    }

    return { success: true };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('Error reverting team merge:', message);
    return { success: false, error: message };
  }
}
