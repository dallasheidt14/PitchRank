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
  console.log("[Watchlist API] GET request received");
  try {
    const supabase = await createServerSupabase();

    // Get authenticated user
    const {
      data: { user },
      error: authError,
    } = await supabase.auth.getUser();

    console.log("[Watchlist API] Auth check:", {
      hasUser: !!user,
      userId: user?.id,
      error: authError?.message,
    });

    if (!user) {
      console.log("[Watchlist API] No user, returning 401");
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    // Get user profile to check premium status
    const { data: profile, error: profileError } = await supabase
      .from("user_profiles")
      .select("plan")
      .eq("id", user.id)
      .single();

    console.log("[Watchlist API] Profile check:", {
      plan: profile?.plan,
      error: profileError?.message,
    });

    if (profileError) {
      console.error("[Watchlist API] Error fetching profile:", profileError);
      return NextResponse.json(
        { error: "Failed to fetch user profile" },
        { status: 500 }
      );
    }

    // Check if profile exists (user may not have a profile row yet)
    if (!profile) {
      console.log("[Watchlist API] No profile found for user");
      return NextResponse.json({ error: "Profile not found" }, { status: 404 });
    }

    // Enforce premium access
    if (profile.plan !== "premium" && profile.plan !== "admin") {
      console.log("[Watchlist API] Not premium, returning 403");
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
      console.log("[Watchlist API] No watchlist found for user, returning empty");
      return NextResponse.json({
        watchlist: null,
        teams: [],
      });
    }

    console.log("[Watchlist API] Found watchlist:", watchlist.id);

    // Get watchlist items
    const { data: items, error: itemsError } = await supabase
      .from("watchlist_items")
      .select("team_id_master, created_at")
      .eq("watchlist_id", watchlist.id);

    console.log("[Watchlist API] Watchlist items:", {
      count: items?.length ?? 0,
      error: itemsError?.message,
    });

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

    // First fetch basic team data from teams table (this has ALL teams)
    // This ensures we return all watched teams, even those without rankings
    const { data: teamsData, error: teamsError } = await supabase
      .from("teams")
      .select("team_id_master, team_name, club_name, state, age, gender")
      .in("team_id_master", teamIds);

    if (teamsError) {
      console.error("Error fetching teams:", teamsError);
      return NextResponse.json(
        { error: "Failed to fetch team data" },
        { status: 500 }
      );
    }

    console.log("[Watchlist API] Teams found:", teamsData?.length ?? 0, "of", teamIds.length);

    // Fetch ranking data from rankings_view (may not have all teams)
    const { data: rankingsData, error: rankingsError } = await supabase
      .from("rankings_view")
      .select("*")
      .in("team_id_master", teamIds);

    if (rankingsError) {
      console.error("Error fetching rankings:", rankingsError);
      // Continue with partial data - teams can still be shown without rankings
    }

    // Create a map of rankings by team_id_master for quick lookup
    const rankingsMap = new Map(
      ((rankingsData || []) as RankingRow[]).map((r: RankingRow) => [r.team_id_master, r])
    );

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

    // Define type for team data from teams table
    type TeamRow = {
      team_id_master: string;
      team_name: string;
      club_name: string | null;
      state: string | null;
      age: number | null;
      gender: string;
    };

    // Build response teams array using teamsData as base (ensures ALL watched teams appear)
    // Then enrich with ranking data where available
    const teams: WatchlistTeam[] = ((teamsData || []) as TeamRow[]).map((team: TeamRow) => {
      const ranking = rankingsMap.get(team.team_id_master);

      return {
        team_id_master: team.team_id_master,
        team_name: team.team_name,
        club_name: team.club_name,
        state: team.state,
        age: team.age,
        gender: team.gender as "M" | "F" | "B" | "G",
        // Ranking data (may be null if team has no rankings yet)
        rank_in_cohort_final: ranking?.rank_in_cohort_final ?? null,
        rank_in_state_final: stateRankMap.get(team.team_id_master) ?? null,
        power_score_final: ranking?.power_score_final ?? null,
        sos_norm: ranking?.sos_norm ?? null,
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
        watchlist_added_at: itemMap.get(team.team_id_master) || "",
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
    console.error("Watchlist GET error:", error);
    return NextResponse.json(
      { error: "Failed to fetch watchlist" },
      { status: 500 }
    );
  }
}
