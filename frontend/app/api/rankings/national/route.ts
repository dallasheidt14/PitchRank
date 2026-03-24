import { createServerSupabase } from "@/lib/supabase/server";
import { NextRequest, NextResponse } from "next/server";
import { normalizeAgeGroup } from "@/lib/utils";

/**
 * GET /api/rankings/national?age=u12&gender=M&limit=1000&offset=0
 *
 * Returns national rankings for a specific (age, gender) cohort.
 * Queries rankings_view server-side with Vercel edge caching, so parallel
 * browser requests (e.g. Playwright suite) hit the cache instead of each
 * independently querying the complex view.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;

  const ageParam = searchParams.get("age");
  const gender = searchParams.get("gender");
  const limit = parseInt(searchParams.get("limit") || "1000", 10);
  const offset = parseInt(searchParams.get("offset") || "0", 10);

  // Validate required params
  if (!ageParam || !gender) {
    return NextResponse.json(
      { error: "Missing required parameters: age, gender" },
      { status: 400 }
    );
  }

  // Normalize age group (e.g., "u12" -> 12)
  const normalizedAge = normalizeAgeGroup(ageParam);
  if (normalizedAge === null) {
    return NextResponse.json(
      { error: `Invalid age group: ${ageParam}` },
      { status: 400 }
    );
  }

  // Validate limit/offset
  if (isNaN(limit) || limit < 1 || limit > 5000) {
    return NextResponse.json(
      { error: "limit must be between 1 and 5000" },
      { status: 400 }
    );
  }
  if (isNaN(offset) || offset < 0) {
    return NextResponse.json(
      { error: "offset must be >= 0" },
      { status: 400 }
    );
  }

  try {
    const supabase = await createServerSupabase();

    const { data, error } = await supabase
      .from("rankings_view")
      .select("*")
      .in("status", ["Active", "Not Enough Ranked Games"])
      .eq("age", normalizedAge)
      .eq("gender", gender)
      .order("power_score_final", { ascending: false })
      .range(offset, offset + limit - 1);

    if (error) {
      console.error("[API /rankings/national] Query error:", error.message);
      return NextResponse.json(
        { error: "Failed to fetch national rankings" },
        { status: 500 }
      );
    }

    return NextResponse.json(data || [], {
      headers: {
        "Cache-Control": "public, s-maxage=120, stale-while-revalidate=300",
      },
    });
  } catch (err) {
    console.error("[API /rankings/national] Unexpected error:", err);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
