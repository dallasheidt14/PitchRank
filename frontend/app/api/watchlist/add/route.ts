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
      error: authError,
    } = await supabase.auth.getUser();

    console.log("[Watchlist Add] Auth check:", user?.id || "no user", authError?.message || "no error");

    if (!user) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    // Get user profile to check premium status
    const { data: profile, error: profileError } = await supabase
      .from("user_profiles")
      .select("plan")
      .eq("id", user.id)
      .single();

    console.log("[Watchlist Add] Profile check:", profile?.plan || "no profile", profileError?.message || "no error");

    if (profileError) {
      console.error("[Watchlist Add] Error fetching profile:", profileError);
      return NextResponse.json(
        { error: "Failed to fetch user profile" },
        { status: 500 }
      );
    }

    // Check if profile exists (user may not have a profile row yet)
    if (!profile) {
      console.log("[Watchlist Add] No profile found for user");
      return NextResponse.json({ error: "Profile not found" }, { status: 404 });
    }

    // Enforce premium access
    if (profile.plan !== "premium" && profile.plan !== "admin") {
      console.log("[Watchlist Add] User not premium:", profile.plan);
      return NextResponse.json({ error: "Premium required" }, { status: 403 });
    }

    // Parse request body
    const body = await req.json();
    const { teamIdMaster } = body;
    console.log("[Watchlist Add] Team ID:", teamIdMaster);

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

    console.log("[Watchlist Add] Team lookup:", team?.team_name || "not found", teamError?.message || "no error");

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

    console.log("[Watchlist Add] Existing watchlist:", existingWatchlist?.id || "none", fetchError?.code || "no error");

    if (fetchError && fetchError.code !== "PGRST116") {
      console.error("[Watchlist Add] Error fetching watchlist:", fetchError);
      return NextResponse.json(
        { error: "Failed to fetch watchlist" },
        { status: 500 }
      );
    }

    if (existingWatchlist) {
      watchlistId = existingWatchlist.id;
    } else {
      // Create default watchlist
      console.log("[Watchlist Add] Creating new watchlist for user:", user.id);
      const { data: newWatchlist, error: createError } = await supabase
        .from("watchlists")
        .insert({
          user_id: user.id,
          name: "My Watchlist",
          is_default: true,
        })
        .select("id")
        .single();

      console.log("[Watchlist Add] New watchlist:", newWatchlist?.id || "failed", createError?.message || "no error");

      if (createError || !newWatchlist) {
        console.error("[Watchlist Add] Error creating watchlist:", createError);
        return NextResponse.json(
          { error: "Failed to create watchlist" },
          { status: 500 }
        );
      }

      watchlistId = newWatchlist.id;
    }

    // Add team to watchlist (upsert to handle duplicates gracefully)
    console.log("[Watchlist Add] Upserting item:", watchlistId, teamIdMaster);
    const { data: upsertData, error: addError } = await supabase.from("watchlist_items").upsert(
      {
        watchlist_id: watchlistId,
        team_id_master: teamIdMaster,
      },
      {
        onConflict: "watchlist_id,team_id_master",
        ignoreDuplicates: false, // Changed to false to see if item was actually inserted
      }
    ).select();

    console.log("[Watchlist Add] Upsert result:", {
      data: upsertData,
      error: addError?.message,
      errorCode: addError?.code,
    });

    if (addError) {
      console.error("[Watchlist Add] Error adding team to watchlist:", addError);
      return NextResponse.json(
        { error: "Failed to add team to watchlist" },
        { status: 500 }
      );
    }

    // Verify the item was actually added
    const { data: verifyItem, error: verifyError } = await supabase
      .from("watchlist_items")
      .select("*")
      .eq("watchlist_id", watchlistId)
      .eq("team_id_master", teamIdMaster)
      .single();

    console.log("[Watchlist Add] Verification query:", {
      found: !!verifyItem,
      item: verifyItem,
      error: verifyError?.message,
    });

    console.log("[Watchlist Add] Success! Added", team.team_name);
    return NextResponse.json({
      success: true,
      message: `Added ${team.team_name} to watchlist`,
      teamIdMaster,
      watchlistId,
      debug: {
        upsertData: upsertData ? { count: upsertData.length, items: upsertData } : null,
        verifyItem: verifyItem ? { found: true, teamId: verifyItem.team_id_master } : { found: false },
        verifyError: verifyError?.message || null,
      },
    });
  } catch (error) {
    console.error("Watchlist add error:", error);
    return NextResponse.json(
      { error: "Failed to add team to watchlist" },
      { status: 500 }
    );
  }
}
