import { createServerSupabase } from "@/lib/supabase/server";
import { NextResponse } from "next/server";
import {
  generateAllInsights,
  type InsightInputData,
  type TeamInsightsResponse,
} from "@/lib/insights";

/**
 * GET /api/insights/[teamId]
 *
 * Generates team insights based on performance data.
 * Premium-only endpoint.
 *
 * Returns:
 * - Season Truth Summary (narrative)
 * - Consistency Score (0-100)
 * - Persona Label (Giant Killer, Flat Track Bully, Gatekeeper, Wildcard)
 */
export async function GET(
  req: Request,
  { params }: { params: Promise<{ teamId: string }> }
) {
  try {
    const { teamId } = await params;
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

    // Check if profile exists (user may not have a profile row yet)
    if (!profile) {
      console.log("[Insights API] No profile found for user");
      return NextResponse.json({ error: "Profile not found" }, { status: 404 });
    }

    // Enforce premium access
    if (profile.plan !== "premium" && profile.plan !== "admin") {
      return NextResponse.json({ error: "Premium required" }, { status: 403 });
    }

    // Validate team ID format
    const uuidRegex =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(teamId)) {
      return NextResponse.json({ error: "Invalid team ID" }, { status: 400 });
    }

    // Fetch team data
    const { data: team, error: teamError } = await supabase
      .from("teams")
      .select("team_id_master, team_name, state_code, gender")
      .eq("team_id_master", teamId)
      .single();

    if (teamError || !team) {
      return NextResponse.json({ error: "Team not found" }, { status: 404 });
    }

    // Fetch ranking data including v53e metrics (offense_norm, defense_norm, perf_centered)
    const { data: ranking, error: rankingError } = await supabase
      .from("rankings_view")
      .select("*, offense_norm, defense_norm, perf_centered")
      .eq("team_id_master", teamId)
      .single();

    if (rankingError && rankingError.code !== "PGRST116") {
      console.error("Error fetching ranking:", rankingError);
    }

    // Fetch games with opponent rankings
    const { data: games, error: gamesError } = await supabase
      .from("games")
      .select("game_date, home_team_master_id, away_team_master_id, home_score, away_score")
      .or(`home_team_master_id.eq.${teamId},away_team_master_id.eq.${teamId}`)
      .order("game_date", { ascending: false })
      .limit(50);

    if (gamesError) {
      console.error("Error fetching games:", gamesError);
    }

    // Define types for the database responses
    type GameRow = {
      game_date: string;
      home_team_master_id: string | null;
      away_team_master_id: string | null;
      home_score: number | null;
      away_score: number | null;
    };

    type OpponentRankingRow = {
      team_id_master: string;
      rank_in_cohort_final: number | null;
      power_score_final: number | null;
    };

    type RankingHistoryRow = {
      snapshot_date: string;
      rank_in_cohort: number;
      power_score_final: number | null;
    };

    type CohortRow = {
      power_score_final: number | null;
    };

    // Get opponent team IDs for ranking lookup
    const opponentIds = new Set<string>();
    ((games || []) as GameRow[]).forEach((game: GameRow) => {
      const oppId =
        game.home_team_master_id === teamId
          ? game.away_team_master_id
          : game.home_team_master_id;
      if (oppId) opponentIds.add(oppId);
    });

    // Fetch opponent rankings
    const { data: opponentRankings, error: oppRankError } = await supabase
      .from("rankings_view")
      .select("team_id_master, rank_in_cohort_final, power_score_final")
      .in("team_id_master", Array.from(opponentIds));

    if (oppRankError) {
      console.error("Error fetching opponent rankings:", oppRankError);
    }

    const oppRankMap = new Map(
      ((opponentRankings || []) as OpponentRankingRow[]).map((opp: OpponentRankingRow) => [
        opp.team_id_master,
        { rank: opp.rank_in_cohort_final, power: opp.power_score_final },
      ])
    );

    // Fetch ranking history
    const { data: rankingHistory, error: historyError } = await supabase
      .from("ranking_history")
      .select("snapshot_date, rank_in_cohort, power_score_final")
      .eq("team_id", teamId)
      .order("snapshot_date", { ascending: false })
      .limit(30);

    if (historyError && historyError.code !== "PGRST116") {
      console.error("Error fetching ranking history:", historyError);
    }

    // Get cohort statistics for context
    let cohortStats = {
      totalTeams: 100,
      medianPowerScore: 50,
      percentile: 50,
    };

    if (ranking?.age && ranking?.gender) {
      const { data: cohortData, error: cohortError } = await supabase
        .from("rankings_view")
        .select("power_score_final")
        .eq("age", ranking.age)
        .eq("gender", ranking.gender)
        .in("status", ["Active", "Not Enough Ranked Games"])
        .order("power_score_final", { ascending: false });

      if (!cohortError && cohortData && cohortData.length > 0) {
        const scores = (cohortData as CohortRow[])
          .map((d: CohortRow) => d.power_score_final)
          .filter((s: number | null): s is number => s !== null);
        const totalTeams = scores.length;
        const medianPowerScore = scores[Math.floor(scores.length / 2)] || 50;

        // Calculate percentile of current team
        const currentPower = ranking?.power_score_final || 0;
        const teamsBelow = scores.filter((s: number) => s < currentPower).length;
        const percentile = Math.round((teamsBelow / totalTeams) * 100);

        cohortStats = {
          totalTeams,
          medianPowerScore,
          percentile,
        };
      }
    }

    // Build insight input data
    const insightData: InsightInputData = {
      team: {
        team_id_master: team.team_id_master,
        team_name: team.team_name,
        state: team.state_code,
        age: ranking?.age || null,
        gender: (ranking?.gender || team.gender === "Male" ? "M" : "F") as
          | "M"
          | "F"
          | "B"
          | "G",
      },
      ranking: {
        rank_in_cohort_final: ranking?.rank_in_cohort_final ?? null,
        power_score_final: ranking?.power_score_final ?? null,
        sos_norm: ranking?.sos_norm ?? null,
        wins: ranking?.wins ?? 0,
        losses: ranking?.losses ?? 0,
        draws: ranking?.draws ?? 0,
        games_played: ranking?.games_played ?? 0,
        rank_change_7d: ranking?.rank_change_7d ?? null,
        rank_change_30d: ranking?.rank_change_30d ?? null,
        // v53e metrics for improved insights
        offense_norm: ranking?.offense_norm ?? null,
        defense_norm: ranking?.defense_norm ?? null,
        perf_centered: ranking?.perf_centered ?? null,
      },
      games: ((games || []) as GameRow[]).map((game: GameRow) => {
        const oppId =
          game.home_team_master_id === teamId
            ? game.away_team_master_id
            : game.home_team_master_id;
        const oppData = oppId ? oppRankMap.get(oppId) : null;

        return {
          game_date: game.game_date,
          home_team_master_id: game.home_team_master_id,
          away_team_master_id: game.away_team_master_id,
          home_score: game.home_score,
          away_score: game.away_score,
          opponent_rank: oppData?.rank ?? null,
          opponent_power_score: oppData?.power ?? null,
        };
      }),
      rankingHistory: ((rankingHistory || []) as RankingHistoryRow[]).map((h: RankingHistoryRow) => ({
        snapshot_date: h.snapshot_date,
        rank_in_cohort: h.rank_in_cohort,
        power_score_final: h.power_score_final,
      })),
      cohortStats,
    };

    // Generate insights
    const insights: TeamInsightsResponse = generateAllInsights(insightData);

    return NextResponse.json(insights);
  } catch (error) {
    console.error("Insights generation error:", error);
    return NextResponse.json(
      { error: "Failed to generate insights" },
      { status: 500 }
    );
  }
}
