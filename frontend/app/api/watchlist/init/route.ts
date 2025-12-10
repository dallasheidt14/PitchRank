import { createServerSupabase } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

/**
 * POST /api/watchlist/init
 *
 * Initializes a user's default watchlist if one doesn't exist.
 * Creates a new "My Watchlist" if the user is premium and has no watchlist.
 *
 * Returns: { watchlist: Watchlist } or { error: string }
 */
export async function POST() {
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
      return NextResponse.json(
        { error: "Premium required" },
        { status: 403 }
      );
    }

    // Check if user already has a default watchlist
    const { data: existingWatchlist, error: fetchError } = await supabase
      .from("watchlists")
      .select("*")
      .eq("user_id", user.id)
      .eq("is_default", true)
      .single();

    if (fetchError && fetchError.code !== "PGRST116") {
      // PGRST116 = no rows returned, which is expected if no watchlist exists
      console.error("Error fetching watchlist:", fetchError);
      return NextResponse.json(
        { error: "Failed to fetch watchlist" },
        { status: 500 }
      );
    }

    // If watchlist exists, return it
    if (existingWatchlist) {
      return NextResponse.json({ watchlist: existingWatchlist });
    }

    // Create default watchlist
    const { data: newWatchlist, error: createError } = await supabase
      .from("watchlists")
      .insert({
        user_id: user.id,
        name: "My Watchlist",
        is_default: true,
      })
      .select()
      .single();

    if (createError) {
      console.error("Error creating watchlist:", createError);
      return NextResponse.json(
        { error: "Failed to create watchlist" },
        { status: 500 }
      );
    }

    return NextResponse.json({ watchlist: newWatchlist });
  } catch (error) {
    console.error("Watchlist init error:", error);
    return NextResponse.json(
      { error: "Failed to initialize watchlist" },
      { status: 500 }
    );
  }
}
