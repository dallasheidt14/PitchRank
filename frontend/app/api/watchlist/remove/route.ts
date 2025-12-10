import { createServerSupabase } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

/**
 * POST /api/watchlist/remove
 *
 * Removes a team from the user's default watchlist.
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

    // Get user's default watchlist
    const { data: watchlist, error: watchlistError } = await supabase
      .from("watchlists")
      .select("id")
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

    if (!watchlist) {
      // No watchlist exists, nothing to remove
      return NextResponse.json({
        success: true,
        message: "No watchlist exists",
      });
    }

    // Remove team from watchlist
    const { error: removeError } = await supabase
      .from("watchlist_items")
      .delete()
      .eq("watchlist_id", watchlist.id)
      .eq("team_id_master", teamIdMaster);

    if (removeError) {
      console.error("Error removing team from watchlist:", removeError);
      return NextResponse.json(
        { error: "Failed to remove team from watchlist" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      success: true,
      message: "Team removed from watchlist",
      teamIdMaster,
    });
  } catch (error) {
    console.error("Watchlist remove error:", error);
    return NextResponse.json(
      { error: "Failed to remove team from watchlist" },
      { status: 500 }
    );
  }
}
