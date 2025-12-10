import { createServerSupabase } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

/**
 * POST /api/watchlist/add
 *
 * Adds a team to the user's default watchlist.
 * Creates the watchlist if it doesn't exist.
 *
 * Body: { teamIdMaster: string }
 */
export async function POST(req: Request) {
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

    // Parse request body
    const body = await req.json();
    const { teamIdMaster } = body;

    if (!teamIdMaster || typeof teamIdMaster !== "string") {
      return NextResponse.json(
        { error: "teamIdMaster is required" },
        { status: 400 }
      );
    }

    // Validate team exists
    const { data: team, error: teamError } = await supabase
      .from("teams")
      .select("team_id_master, team_name")
      .eq("team_id_master", teamIdMaster)
      .single();

    if (teamError || !team) {
      return NextResponse.json({ error: "Team not found" }, { status: 404 });
    }

    // Get or create default watchlist
    let watchlistId: string;

    const { data: existingWatchlist, error: fetchError } = await supabase
      .from("watchlists")
      .select("id")
      .eq("user_id", user.id)
      .eq("is_default", true)
      .single();

    if (fetchError && fetchError.code !== "PGRST116") {
      console.error("Error fetching watchlist:", fetchError);
      return NextResponse.json(
        { error: "Failed to fetch watchlist" },
        { status: 500 }
      );
    }

    if (existingWatchlist) {
      watchlistId = existingWatchlist.id;
    } else {
      // Create default watchlist
      const { data: newWatchlist, error: createError } = await supabase
        .from("watchlists")
        .insert({
          user_id: user.id,
          name: "My Watchlist",
          is_default: true,
        })
        .select("id")
        .single();

      if (createError || !newWatchlist) {
        console.error("Error creating watchlist:", createError);
        return NextResponse.json(
          { error: "Failed to create watchlist" },
          { status: 500 }
        );
      }

      watchlistId = newWatchlist.id;
    }

    // Add team to watchlist (upsert to handle duplicates gracefully)
    const { error: addError } = await supabase.from("watchlist_items").upsert(
      {
        watchlist_id: watchlistId,
        team_id_master: teamIdMaster,
      },
      {
        onConflict: "watchlist_id,team_id_master",
        ignoreDuplicates: true,
      }
    );

    if (addError) {
      console.error("Error adding team to watchlist:", addError);
      return NextResponse.json(
        { error: "Failed to add team to watchlist" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      success: true,
      message: `Added ${team.team_name} to watchlist`,
      teamIdMaster,
    });
  } catch (error) {
    console.error("Watchlist add error:", error);
    return NextResponse.json(
      { error: "Failed to add team to watchlist" },
      { status: 500 }
    );
  }
}
