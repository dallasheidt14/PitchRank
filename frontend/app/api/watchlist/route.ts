import { createServerSupabase } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

/**
 * Watchlist item with team data and insights preview
 */
export interface WatchlistTeam {
  team_id_master: string;
  team_name: string;
  club_name: string | null;
  state: string | null;
  age: number | null;
  gender: "M" | "F" | "B" | "G";
  // Rankings
  rank_in_cohort_final: number | null;
  rank_in_state_final: number | null;
  power_score_final: number | null;
  sos_norm: number | null;
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
    const supabase = await createServerSupabase();

    // Get authenticated user
    const {
      data: { user },
    } = await supabase.auth.getUser();

    if (!user) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    // Get user profile to check premium status
    const { data: profile, error: profileError } = await supabase
      .from("user_profiles")
      .select("plan")
      .eq("id", user.id)
      .single();

    if (profileError) {
      console.error("Error fetching profile:", profileError);
      return NextResponse.json(
        { error: "Failed to fetch user profile" },
        { status: 500 }
      );
    }

    // Enforce premium access
    if (profile.plan !== "premium" && profile.plan !== "admin") {
      return NextResponse.json({ error: "Premium required" }, { status: 403 });
    }

    // Get user's default watchlist
    const { data: watchlist, error: watchlistError } = await supabase
      .from("watchlists")
      .select("*")
      .eq("user_id", user.id)
      .eq("is_default", true)
      .single();

    if (watchlistError && watchlistError.code !== "PGRST116") {
      console.error("Error fetching watchlist:", watchlistError);
      return NextResponse.json(
        { error: "Failed to fetch watchlist" },
        { status: 500 }
      );
    }

    // No watchlist exists - return empty response
    if (!watchlist) {
      return NextResponse.json({
        watchlist: null,
        teams: [],
      });
    }

    // Get watchlist items
    const { data: items, error: itemsError } = await supabase
      .from("watchlist_items")
      .select("team_id_master, created_at")
      .eq("watchlist_id", watchlist.id);

    if (itemsError) {
      console.error("Error fetching watchlist items:", itemsError);
      return NextResponse.json(
        { error: "Failed to fetch watchlist items" },
        { status: 500 }
      );
    }

    // Define types for database responses
    type WatchlistItem = {
      team_id_master: string;
      created_at: string;
    };

    type StateRankRow = {
      team_id_master: string;
      rank_in_state_final: number | null;
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

    // Get team IDs
    const typedItems = items as WatchlistItem[];
    const teamIds = typedItems.map((item: WatchlistItem) => item.team_id_master);
    const itemMap = new Map(
      typedItems.map((item: WatchlistItem) => [item.team_id_master, item.created_at])
    );

    // Fetch full team data from rankings_view
    const { data: rankingsData, error: rankingsError } = await supabase
      .from("rankings_view")
      .select("*")
      .in("team_id_master", teamIds);

    if (rankingsError) {
      console.error("Error fetching rankings:", rankingsError);
      // Continue with partial data
    }

    // Fetch state rankings for state rank
    const { data: stateRankingsData, error: stateRankingsError } = await supabase
      .from("state_rankings_view")
      .select("team_id_master, rank_in_state_final")
      .in("team_id_master", teamIds);

    if (stateRankingsError) {
      console.error("Error fetching state rankings:", stateRankingsError);
    }

    const stateRankMap = new Map(
      ((stateRankingsData || []) as StateRankRow[]).map((sr: StateRankRow) => [
        sr.team_id_master,
        sr.rank_in_state_final,
      ])
    );

    // Calculate new games count (last 7 days) for each team
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
    const sevenDaysAgoStr = sevenDaysAgo.toISOString().split("T")[0];

    // Get recent games for all teams in one query
    const { data: recentGames, error: recentGamesError } = await supabase
      .from("games")
      .select("home_team_master_id, away_team_master_id, game_date")
      .or(
        teamIds
          .map(
            (id) =>
              `home_team_master_id.eq.${id},away_team_master_id.eq.${id}`
          )
          .join(",")
      )
      .gte("game_date", sevenDaysAgoStr);

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
    const teamsWithoutRecentGames = teamIds.filter(
      (id: string) => !lastGameMap.has(id)
    );
    if (teamsWithoutRecentGames.length > 0) {
      const { data: lastGames, error: lastGamesError } = await supabase
        .from("games")
        .select("home_team_master_id, away_team_master_id, game_date")
        .or(
          teamsWithoutRecentGames
            .map(
              (id: string) =>
                `home_team_master_id.eq.${id},away_team_master_id.eq.${id}`
            )
            .join(",")
        )
        .order("game_date", { ascending: false })
        .limit(teamsWithoutRecentGames.length * 3); // Get a few recent games per team

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

    // Build response teams array
    const teams: WatchlistTeam[] = ((rankingsData || []) as RankingRow[]).map((ranking: RankingRow) => ({
      team_id_master: ranking.team_id_master,
      team_name: ranking.team_name,
      club_name: ranking.club_name,
      state: ranking.state,
      age: ranking.age,
      gender: ranking.gender as "M" | "F" | "B" | "G",
      rank_in_cohort_final: ranking.rank_in_cohort_final,
      rank_in_state_final: stateRankMap.get(ranking.team_id_master) ?? null,
      power_score_final: ranking.power_score_final,
      sos_norm: ranking.sos_norm,
      rank_change_7d: ranking.rank_change_7d,
      rank_change_30d: ranking.rank_change_30d,
      wins: ranking.wins || 0,
      losses: ranking.losses || 0,
      draws: ranking.draws || 0,
      games_played: ranking.games_played || 0,
      total_games_played: ranking.total_games_played || 0,
      win_percentage: ranking.win_percentage,
      new_games_count: newGamesMap.get(ranking.team_id_master) || 0,
      last_game_date: lastGameMap.get(ranking.team_id_master) || null,
      watchlist_added_at: itemMap.get(ranking.team_id_master) || "",
    }));

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
    console.error("Watchlist GET error:", error);
    return NextResponse.json(
      { error: "Failed to fetch watchlist" },
      { status: 500 }
    );
  }
}
