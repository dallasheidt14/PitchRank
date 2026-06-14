import { requirePremium } from '@/lib/api/requirePremium';
import { resolveDefaultWatchlist } from '@/lib/api/watchlist';
import { NextResponse } from 'next/server';

/**
 * Watchlist item with team data and insights preview
 */
export interface WatchlistTeam {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  state: string | null;
  age: number | null;
  gender: 'M' | 'F' | 'B' | 'G';
  // Rankings
  rank_in_cohort_final: number | null;
  rank_in_state_final: number | null;
  power_score_final: number | null;
  sos_norm: number | null;
  sos_rank_state: number | null;
  sos_rank_national: number | null;
  // Deltas
  rank_change_7d: number | null;
  rank_change_30d: number | null;
  // Record
  wins: number;
  losses: number;
  draws: number;
  games_played: number;
  total_games_played: number;
  win_percentage: number | null;
  // Recent activity
  new_games_count: number;
  last_game_date: string | null;
  last_5_results: ('W' | 'L' | 'D')[]; // Oldest-first for left-to-right timeline display
  // Added to watchlist
  watchlist_added_at: string;
}

export interface WatchlistResponse {
  watchlist: {
    id: string;
    name: string;
    is_default: boolean;
    created_at: string;
    updated_at: string;
  };
  teams: WatchlistTeam[];
}

/**
 * GET /api/watchlist
 *
 * Returns the user's default watchlist with full team data.
 * Includes ranking deltas, recent games count, and insight previews.
 */
export async function GET() {
  try {
    const auth = await requirePremium();
    if (auth.error) return auth.error;
    const { user, supabase } = auth;

    // Resolve the user's default watchlist (falls back to most-recent).
    const { watchlist, error: watchlistError } = await resolveDefaultWatchlist(supabase, user.id);

    if (watchlistError) {
      console.error('Error fetching watchlist:', watchlistError);
      return NextResponse.json({ error: 'Failed to fetch watchlist' }, { status: 500 });
    }

    // No watchlist exists - return empty response with proper structure
    if (!watchlist) {
      return NextResponse.json({
        watchlist: {
          id: '',
          name: '',
          is_default: true,
          created_at: '',
          updated_at: '',
        },
        teams: [],
      });
    }

    // Get watchlist items for the found watchlist
    const { data: items, error: itemsError } = await supabase
      .from('watchlist_items')
      .select('team_id_master, created_at')
      .eq('watchlist_id', watchlist.id);

    if (itemsError) {
      console.error('[Watchlist API] Error fetching watchlist items:', itemsError);
      return NextResponse.json({ error: 'Failed to fetch watchlist items' }, { status: 500 });
    }

    // Define types for database responses
    type WatchlistItem = {
      team_id_master: string;
      created_at: string;
    };

    type StateRankRow = {
      team_id_master: string;
      rank_in_state_final: number | null;
      sos_rank_state: number | null;
    };

    type RankingRow = {
      team_id_master: string;
      team_name: string;
      club_name: string | null;
      state: string | null;
      age: number | null;
      gender: string;
      rank_in_cohort_final: number | null;
      power_score_final: number | null;
      sos_norm: number | null;
      sos_rank_state: number | null;
      sos_rank_national: number | null;
      rank_change_7d: number | null;
      rank_change_30d: number | null;
      wins: number | null;
      losses: number | null;
      draws: number | null;
      games_played: number | null;
      total_games_played: number | null;
      win_percentage: number | null;
    };

    if (!items || items.length === 0) {
      return NextResponse.json({
        watchlist: {
          id: watchlist.id,
          name: watchlist.name,
          is_default: watchlist.is_default,
          created_at: watchlist.created_at,
          updated_at: watchlist.updated_at,
        },
        teams: [],
      });
    }

    // Get team IDs (may include deprecated team_id_masters from before merges).
    // Resolve to canonical via team_merge_map so rankings/state queries hit the
    // canonical row — otherwise the watchlist card shows stale pre-merge data
    // while the team page (which redirects deprecated → canonical) shows current data.
    const typedItems = items as WatchlistItem[];
    const originalIds = typedItems.map((item: WatchlistItem) => item.team_id_master);

    const { data: mergeData, error: mergeError } = await supabase
      .from('team_merge_map')
      .select('deprecated_team_id, canonical_team_id')
      .in('deprecated_team_id', originalIds);

    if (mergeError) {
      console.error('[Watchlist API] Error fetching merge map:', mergeError);
    }

    const canonicalByDeprecated = new Map<string, string>(
      ((mergeData || []) as { deprecated_team_id: string; canonical_team_id: string }[]).map((m) => [
        m.deprecated_team_id,
        m.canonical_team_id,
      ])
    );

    const resolveId = (id: string) => canonicalByDeprecated.get(id) ?? id;
    const teamIds = Array.from(new Set(originalIds.map(resolveId)));

    // Key itemMap by canonical id so the response carries the canonical team_id_master.
    // If both the deprecated and canonical IDs are in the watchlist, keep the earliest added_at.
    const itemMap = new Map<string, string>();
    for (const item of typedItems) {
      const canonical = resolveId(item.team_id_master);
      const existing = itemMap.get(canonical);
      if (!existing || item.created_at < existing) {
        itemMap.set(canonical, item.created_at);
      }
    }

    // Guard against empty teamIds array
    if (teamIds.length === 0) {
      return NextResponse.json({
        watchlist: {
          id: watchlist.id,
          name: watchlist.name,
          is_default: watchlist.is_default,
          created_at: watchlist.created_at,
          updated_at: watchlist.updated_at,
        },
        teams: [],
      });
    }

    // First fetch basic team data from teams table (this has ALL teams)
    // This ensures we return all watched teams, even those without rankings
    const { data: teamsData, error: teamsError } = await supabase
      .from('teams')
      .select('team_id_master, team_name, club_name, state, age_group, gender')
      .in('team_id_master', teamIds);

    if (teamsError) {
      console.error('Error fetching teams:', teamsError.message);
      return NextResponse.json({ error: 'Failed to fetch team data', details: teamsError.message }, { status: 500 });
    }

    // Fetch ranking data from rankings_view (may not have all teams)
    // Filter by status to match rankings pages (only active teams)
    const { data: rankingsData, error: rankingsError } = await supabase
      .from('rankings_view')
      .select('*')
      .in('team_id_master', teamIds)
      .in('status', ['Active', 'Not Enough Ranked Games']);

    if (rankingsError) {
      console.error('Error fetching rankings:', rankingsError);
      // Continue with partial data - teams can still be shown without rankings
    }

    // Create a map of rankings by team_id_master for quick lookup
    const rankingsMap = new Map(((rankingsData || []) as RankingRow[]).map((r: RankingRow) => [r.team_id_master, r]));

    // Fetch state rankings for state rank (with status filter)
    const { data: stateRankingsData, error: stateRankingsError } = await supabase
      .from('state_rankings_view')
      .select('team_id_master, rank_in_state_final, sos_rank_state')
      .in('team_id_master', teamIds)
      .in('status', ['Active', 'Not Enough Ranked Games']);

    if (stateRankingsError) {
      console.error('Error fetching state rankings:', stateRankingsError);
    }

    const stateRankMap = new Map(
      ((stateRankingsData || []) as StateRankRow[]).map((sr: StateRankRow) => [
        sr.team_id_master,
        sr.rank_in_state_final,
      ])
    );
    const sosRankStateMap = new Map(
      ((stateRankingsData || []) as StateRankRow[]).map((sr: StateRankRow) => [sr.team_id_master, sr.sos_rank_state])
    );

    // Calculate new games count (last 7 days) for each team
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    const sevenDaysAgoStr = sevenDaysAgo.toISOString().split('T')[0];

    // Get recent games for all teams using parallel .in() queries
    // (avoids unbounded .or() that can exceed URL length limits)
    const [homeRecentResult, awayRecentResult] = await Promise.all([
      supabase
        .from('games')
        .select('home_team_master_id, away_team_master_id, game_date')
        .in('home_team_master_id', teamIds)
        .gte('game_date', sevenDaysAgoStr),
      supabase
        .from('games')
        .select('home_team_master_id, away_team_master_id, game_date')
        .in('away_team_master_id', teamIds)
        .gte('game_date', sevenDaysAgoStr),
    ]);

    const recentGamesError = homeRecentResult.error || awayRecentResult.error;

    // Merge and deduplicate by composite key (no unique id on select)
    const recentGamesRaw = [...(homeRecentResult.data || []), ...(awayRecentResult.data || [])];
    const recentGamesSeen = new Set<string>();
    const recentGames = recentGamesRaw.filter((g) => {
      const key = `${g.home_team_master_id}|${g.away_team_master_id}|${g.game_date}`;
      if (recentGamesSeen.has(key)) return false;
      recentGamesSeen.add(key);
      return true;
    });

    // Count new games per team
    const newGamesMap = new Map<string, number>();
    const lastGameMap = new Map<string, string>();

    if (!recentGamesError && recentGames) {
      for (const game of recentGames) {
        const homeId = game.home_team_master_id;
        const awayId = game.away_team_master_id;

        if (homeId && teamIds.includes(homeId)) {
          newGamesMap.set(homeId, (newGamesMap.get(homeId) || 0) + 1);
          const current = lastGameMap.get(homeId);
          if (!current || game.game_date > current) {
            lastGameMap.set(homeId, game.game_date);
          }
        }
        if (awayId && teamIds.includes(awayId)) {
          newGamesMap.set(awayId, (newGamesMap.get(awayId) || 0) + 1);
          const current = lastGameMap.get(awayId);
          if (!current || game.game_date > current) {
            lastGameMap.set(awayId, game.game_date);
          }
        }
      }
    }

    // Also get last game date for teams with no recent games
    const teamsWithoutRecentGames = teamIds.filter((id: string) => !lastGameMap.has(id));
    if (teamsWithoutRecentGames.length > 0) {
      const perTeamLimit = teamsWithoutRecentGames.length * 3;
      const [homeLastResult, awayLastResult] = await Promise.all([
        supabase
          .from('games')
          .select('home_team_master_id, away_team_master_id, game_date')
          .in('home_team_master_id', teamsWithoutRecentGames)
          .order('game_date', { ascending: false })
          .limit(perTeamLimit),
        supabase
          .from('games')
          .select('home_team_master_id, away_team_master_id, game_date')
          .in('away_team_master_id', teamsWithoutRecentGames)
          .order('game_date', { ascending: false })
          .limit(perTeamLimit),
      ]);

      const lastGamesError = homeLastResult.error || awayLastResult.error;

      // Merge and deduplicate
      const lastGamesRaw = [...(homeLastResult.data || []), ...(awayLastResult.data || [])];
      const lastGamesSeen = new Set<string>();
      const lastGames = lastGamesRaw.filter((g) => {
        const key = `${g.home_team_master_id}|${g.away_team_master_id}|${g.game_date}`;
        if (lastGamesSeen.has(key)) return false;
        lastGamesSeen.add(key);
        return true;
      });

      if (!lastGamesError && lastGames) {
        for (const game of lastGames) {
          const homeId = game.home_team_master_id;
          const awayId = game.away_team_master_id;

          if (homeId && !lastGameMap.has(homeId)) {
            lastGameMap.set(homeId, game.game_date);
          }
          if (awayId && !lastGameMap.has(awayId)) {
            lastGameMap.set(awayId, game.game_date);
          }
        }
      }
    }

    // Compute last 5 game results (W/L/D) per team for the form strip.
    // Overshoot the limit so the per-team top-5 survives the home/away merge + dedupe.
    const formLimit = teamIds.length * 12;
    const [formHomeResult, formAwayResult] = await Promise.all([
      supabase
        .from('games')
        .select('home_team_master_id, away_team_master_id, home_score, away_score, game_date')
        .in('home_team_master_id', teamIds)
        .eq('is_excluded', false)
        .not('home_score', 'is', null)
        .not('away_score', 'is', null)
        .order('game_date', { ascending: false })
        .limit(formLimit),
      supabase
        .from('games')
        .select('home_team_master_id, away_team_master_id, home_score, away_score, game_date')
        .in('away_team_master_id', teamIds)
        .eq('is_excluded', false)
        .not('home_score', 'is', null)
        .not('away_score', 'is', null)
        .order('game_date', { ascending: false })
        .limit(formLimit),
    ]);

    const formGamesRaw = [...(formHomeResult.data || []), ...(formAwayResult.data || [])];
    const formSeen = new Set<string>();
    const formGames = formGamesRaw
      .filter((g) => {
        const key = `${g.home_team_master_id}|${g.away_team_master_id}|${g.game_date}`;
        if (formSeen.has(key)) return false;
        formSeen.add(key);
        return true;
      })
      .sort((a, b) => (b.game_date > a.game_date ? 1 : b.game_date < a.game_date ? -1 : 0));

    // Walk most-recent-first; take 5 per team; then reverse so the array is oldest-first.
    const formByTeam = new Map<string, ('W' | 'L' | 'D')[]>();
    const teamIdSet = new Set(teamIds);
    for (const game of formGames) {
      const homeId = game.home_team_master_id;
      const awayId = game.away_team_master_id;
      for (const teamId of [homeId, awayId]) {
        if (!teamId || !teamIdSet.has(teamId)) continue;
        const list = formByTeam.get(teamId) ?? [];
        if (list.length >= 5) continue;
        const isHome = teamId === homeId;
        const myScore = isHome ? game.home_score : game.away_score;
        const opScore = isHome ? game.away_score : game.home_score;
        if (myScore == null || opScore == null) continue;
        const result: 'W' | 'L' | 'D' = myScore > opScore ? 'W' : myScore < opScore ? 'L' : 'D';
        list.push(result);
        formByTeam.set(teamId, list);
      }
    }
    for (const [id, results] of formByTeam) {
      formByTeam.set(id, results.reverse());
    }

    // Define type for team data from teams table
    type TeamRow = {
      team_id_master: string;
      team_name: string;
      club_name: string | null;
      state: string | null;
      age_group: string; // Teams table has age_group, not age
      gender: string;
    };

    // Helper function to convert age_group (e.g., "u12") to age (integer, e.g., 12)
    const ageGroupToAge = (ageGroup: string | null): number | null => {
      if (!ageGroup) return null;
      // If it's already a number (e.g., "12"), cast directly
      if (/^[0-9]+$/.test(ageGroup)) {
        return parseInt(ageGroup, 10);
      }
      // If it starts with 'u' or 'U' followed by digits (e.g., "u12", "U12"), extract the number
      const match = ageGroup.match(/^[uU]([0-9]+)$/);
      if (match) {
        return parseInt(match[1], 10);
      }
      // Try to extract any number from the string as fallback
      const numberMatch = ageGroup.match(/[0-9]+/);
      if (numberMatch) {
        return parseInt(numberMatch[0], 10);
      }
      return null;
    };

    // Build response teams array using teamsData as base (ensures ALL watched teams appear)
    // Then enrich with ranking data where available
    const teams: WatchlistTeam[] = ((teamsData || []) as TeamRow[]).map((team: TeamRow) => {
      const ranking = rankingsMap.get(team.team_id_master);

      // Use age from rankings_view if available (more accurate), otherwise convert from age_group
      const age = ranking?.age ?? ageGroupToAge(team.age_group);

      return {
        team_id_master: team.team_id_master,
        team_name: team.team_name,
        club_name: team.club_name,
        state: team.state,
        age,
        gender: team.gender as 'M' | 'F' | 'B' | 'G',
        // Ranking data (may be null if team has no rankings yet)
        rank_in_cohort_final: ranking?.rank_in_cohort_final ?? null,
        rank_in_state_final: stateRankMap.get(team.team_id_master) ?? null,
        power_score_final: ranking?.power_score_final ?? null,
        sos_norm: ranking?.sos_norm ?? null,
        sos_rank_state: sosRankStateMap.get(team.team_id_master) ?? ranking?.sos_rank_state ?? null,
        sos_rank_national: ranking?.sos_rank_national ?? null,
        rank_change_7d: ranking?.rank_change_7d ?? null,
        rank_change_30d: ranking?.rank_change_30d ?? null,
        wins: ranking?.wins || 0,
        losses: ranking?.losses || 0,
        draws: ranking?.draws || 0,
        games_played: ranking?.games_played || 0,
        total_games_played: ranking?.total_games_played || 0,
        win_percentage: ranking?.win_percentage ?? null,
        new_games_count: newGamesMap.get(team.team_id_master) || 0,
        last_game_date: lastGameMap.get(team.team_id_master) || null,
        last_5_results: formByTeam.get(team.team_id_master) ?? [],
        watchlist_added_at: itemMap.get(team.team_id_master) || '',
      };
    });

    return NextResponse.json({
      watchlist: {
        id: watchlist.id,
        name: watchlist.name,
        is_default: watchlist.is_default,
        created_at: watchlist.created_at,
        updated_at: watchlist.updated_at,
      },
      teams,
    } satisfies WatchlistResponse);
  } catch (error) {
    console.error('Watchlist GET error:', error);
    return NextResponse.json({ error: 'Failed to fetch watchlist' }, { status: 500 });
  }
}
