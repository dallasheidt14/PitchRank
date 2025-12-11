"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  Star,
  Trophy,
  Filter,
  ArrowUpDown,
  Trash2,
  Square,
  CheckSquare,
  MapPin,
  Users,
  ChevronRight,
  Sparkles,
  AlertCircle,
  Brain,
  Zap,
  CalendarDays,
  RefreshCw,
  Crown,
} from "lucide-react";
import { fetchWatchlist, removeFromSupabaseWatchlist, initWatchlist } from "@/lib/watchlist";
import type { WatchlistResponse } from "@/app/api/watchlist/route";
import { formatPowerScore, formatSOSIndex, cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { InsightModal, DeltaIndicator } from "@/components/insights";
import { useUser, hasPremiumAccess } from "@/hooks/useUser";
import { useWatchlistMigration } from "@/hooks/useWatchlistMigration";

// Sort options
type SortOption = "rank" | "power" | "name" | "record" | "movers" | "activity";

export default function WatchlistPage() {
  const { user, profile, isLoading: userLoading } = useUser();
  const queryClient = useQueryClient();

  // Run localStorage migration for premium users
  useWatchlistMigration(profile, user?.id ?? null);

  // State
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filterAge, setFilterAge] = useState<string>("all");
  const [filterState, setFilterState] = useState<string>("all");
  const [filterGender, setFilterGender] = useState<string>("all");
  const [sortBy, setSortBy] = useState<SortOption>("rank");
  const [insightModalTeam, setInsightModalTeam] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const isPremium = hasPremiumAccess(profile);

  // Debug logging - remove after fixing
  console.log("[Watchlist Page] State:", {
    userLoading,
    hasUser: !!user,
    userId: user?.id,
    profile: profile ? { plan: profile.plan } : null,
    isPremium,
    queryEnabled: isPremium && !!user,
  });

  // Initialize watchlist on mount for premium users
  useEffect(() => {
    if (isPremium && user) {
      initWatchlist();
    }
  }, [isPremium, user]);

  // Fetch watchlist from Supabase
  const {
    data: watchlistData,
    isLoading: watchlistLoading,
    isFetching: watchlistFetching,
    error: watchlistError,
    refetch: refetchWatchlist,
    status: queryStatus,
    fetchStatus,
  } = useQuery<WatchlistResponse | null>({
    queryKey: ["watchlist"],
    queryFn: fetchWatchlist,
    enabled: isPremium && !!user,
    staleTime: 2 * 60 * 1000, // 2 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  });

  // Debug query status
  console.log("[Watchlist Page] Query:", {
    queryStatus,
    fetchStatus,
    watchlistLoading,
    watchlistFetching,
    hasData: !!watchlistData,
    teamsCount: watchlistData?.teams?.length ?? 0,
    error: watchlistError?.message,
  });

  const teams = useMemo(() => watchlistData?.teams ?? [], [watchlistData?.teams]);

  // Filter and sort teams
  const filteredTeams = useMemo(() => {
    let result = [...teams];

    // Apply filters
    if (filterAge !== "all") {
      const age = parseInt(filterAge);
      result = result.filter((t) => t.age === age);
    }
    if (filterState !== "all") {
      result = result.filter((t) => t.state === filterState);
    }
    if (filterGender !== "all") {
      result = result.filter((t) => t.gender === filterGender);
    }

    // Apply sort
    switch (sortBy) {
      case "rank":
        result.sort(
          (a, b) => (a.rank_in_cohort_final ?? 999) - (b.rank_in_cohort_final ?? 999)
        );
        break;
      case "power":
        result.sort((a, b) => (b.power_score_final ?? 0) - (a.power_score_final ?? 0));
        break;
      case "name":
        result.sort((a, b) => a.team_name.localeCompare(b.team_name));
        break;
      case "record":
        result.sort((a, b) => {
          const aWinPct =
            a.games_played > 0 ? (a.wins + a.draws * 0.5) / a.games_played : 0;
          const bWinPct =
            b.games_played > 0 ? (b.wins + b.draws * 0.5) / b.games_played : 0;
          return bWinPct - aWinPct;
        });
        break;
      case "movers":
        // Sort by absolute rank change (biggest movers first)
        result.sort((a, b) => {
          const aChange = Math.abs(a.rank_change_7d ?? 0);
          const bChange = Math.abs(b.rank_change_7d ?? 0);
          return bChange - aChange;
        });
        break;
      case "activity":
        // Sort by recent games count
        result.sort((a, b) => (b.new_games_count ?? 0) - (a.new_games_count ?? 0));
        break;
    }

    return result;
  }, [teams, filterAge, filterState, filterGender, sortBy]);

  // Get unique values for filter options
  const availableStates = useMemo(() => {
    const states = new Set(teams.map((t) => t.state).filter(Boolean));
    return Array.from(states).sort() as string[];
  }, [teams]);

  const availableAges = useMemo(() => {
    const ages = new Set(teams.map((t) => t.age).filter(Boolean));
    return Array.from(ages).sort((a, b) => (a ?? 0) - (b ?? 0)) as number[];
  }, [teams]);

  // Calculate dashboard stats
  const dashboardStats = useMemo(() => {
    const bigMovers = teams.filter(
      (t) => t.rank_change_7d !== null && Math.abs(t.rank_change_7d) >= 5
    ).length;
    const recentlyActive = teams.filter((t) => t.new_games_count > 0).length;
    const topTenTeams = teams.filter(
      (t) => t.rank_in_cohort_final !== null && t.rank_in_cohort_final <= 10
    ).length;

    return { bigMovers, recentlyActive, topTenTeams };
  }, [teams]);

  // Selection handlers
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(filteredTeams.map((t) => t.team_id_master)));
  }, [filteredTeams]);

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const removeTeams = useCallback(
    async (teamIds: string[]) => {
      for (const id of teamIds) {
        await removeFromSupabaseWatchlist(id);
      }
      // Refetch watchlist
      queryClient.invalidateQueries({ queryKey: ["watchlist"] });
      setSelectedIds(new Set());
    },
    [queryClient]
  );

  const removeSelected = useCallback(() => {
    removeTeams(Array.from(selectedIds));
  }, [removeTeams, selectedIds]);

  const removeSingle = useCallback(
    (id: string) => {
      removeTeams([id]);
    },
    [removeTeams]
  );

  // Rank badge styling
  const getRankBadgeClass = (rank: number | null | undefined) => {
    if (!rank) return "bg-muted text-muted-foreground";
    if (rank === 1) return "badge-gold";
    if (rank === 2) return "badge-silver";
    if (rank === 3) return "badge-bronze";
    if (rank <= 10) return "bg-primary text-primary-foreground";
    if (rank <= 25) return "bg-primary/80 text-primary-foreground";
    return "bg-muted text-foreground";
  };

  // Gender display
  const getGenderDisplay = (gender: string) => {
    switch (gender) {
      case "M":
      case "B":
        return "Boys";
      case "F":
      case "G":
        return "Girls";
      default:
        return gender;
    }
  };

  // Loading state
  if (userLoading) {
    return (
      <div className="min-h-screen bg-background">
        <div className="container px-4 py-12">
          <div className="animate-pulse space-y-8">
            <div className="h-32 bg-muted rounded-xl" />
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="h-48 bg-muted rounded-xl" />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Not authenticated
  if (!user) {
    return (
      <div className="min-h-screen bg-background">
        <div className="container px-4 py-16">
          <div className="text-center max-w-md mx-auto">
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-full bg-muted mb-6">
              <Crown className="h-10 w-10 text-muted-foreground" />
            </div>
            <h1 className="text-2xl font-display mb-3">Sign In Required</h1>
            <p className="text-muted-foreground mb-6">
              Please sign in to access your Season Dashboard.
            </p>
            <Link href="/login">
              <Button size="lg">Sign In</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Not premium
  if (!isPremium) {
    return (
      <div className="min-h-screen bg-background">
        <div className="container px-4 py-16">
          <div className="text-center max-w-md mx-auto">
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 mb-6">
              <Crown className="h-10 w-10 text-white" />
            </div>
            <h1 className="text-2xl font-display mb-3">Premium Feature</h1>
            <p className="text-muted-foreground mb-6">
              Upgrade to Premium to access your Season Dashboard with persistent
              watchlists, team insights, and more.
            </p>
            <Link href="/upgrade">
              <Button size="lg" className="gap-2">
                <Sparkles className="h-5 w-5" />
                Upgrade to Premium
              </Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Hero Section */}
      <section className="relative overflow-hidden bg-gradient-to-br from-primary via-primary to-primary/90 py-12 sm:py-16">
        {/* Diagonal stripe pattern */}
        <div className="absolute inset-0 bg-diagonal-stripes opacity-10" />

        {/* Accent diagonal */}
        <div
          className="absolute -right-20 -top-20 w-96 h-96 bg-accent/20 rotate-12 transform"
          style={{ clipPath: "polygon(0 0, 100% 0, 100% 100%, 20% 100%)" }}
        />

        <div className="container relative px-4">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="p-3 bg-accent rounded-xl">
                <Trophy className="h-8 w-8 text-accent-foreground" />
              </div>
              <div>
                <h1 className="text-3xl sm:text-4xl md:text-5xl font-display text-primary-foreground tracking-tight">
                  My Season Dashboard
                </h1>
                <p className="text-primary-foreground/80 font-sans text-sm sm:text-base mt-1">
                  {teams.length} {teams.length === 1 ? "team" : "teams"} in your watchlist
                </p>
              </div>
            </div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => refetchWatchlist()}
              disabled={watchlistFetching}
              className="gap-1.5"
            >
              <RefreshCw className={cn("h-4 w-4", watchlistFetching && "animate-spin")} />
              {watchlistFetching ? "Refreshing..." : "Refresh"}
            </Button>
          </div>

          {/* Dashboard Stats */}
          {teams.length > 0 && (
            <div className="grid grid-cols-3 gap-4 max-w-xl">
              <div className="bg-white/10 backdrop-blur rounded-lg p-3 text-center">
                <Zap className="h-5 w-5 text-amber-300 mx-auto mb-1" />
                <p className="text-2xl font-bold text-primary-foreground">
                  {dashboardStats.bigMovers}
                </p>
                <p className="text-xs text-primary-foreground/70">Big Movers</p>
              </div>
              <div className="bg-white/10 backdrop-blur rounded-lg p-3 text-center">
                <CalendarDays className="h-5 w-5 text-green-300 mx-auto mb-1" />
                <p className="text-2xl font-bold text-primary-foreground">
                  {dashboardStats.recentlyActive}
                </p>
                <p className="text-xs text-primary-foreground/70">Active This Week</p>
              </div>
              <div className="bg-white/10 backdrop-blur rounded-lg p-3 text-center">
                <Crown className="h-5 w-5 text-yellow-300 mx-auto mb-1" />
                <p className="text-2xl font-bold text-primary-foreground">
                  {dashboardStats.topTenTeams}
                </p>
                <p className="text-xs text-primary-foreground/70">Top 10 Teams</p>
              </div>
            </div>
          )}
        </div>
      </section>

      <div className="container px-4 py-8">
        {watchlistLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[...Array(6)].map((_, i) => (
              <div
                key={i}
                className="h-56 bg-muted rounded-xl animate-pulse"
                style={{ animationDelay: `${i * 100}ms` }}
              />
            ))}
          </div>
        ) : watchlistError ? (
          <div className="text-center py-12">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <h2 className="text-xl font-semibold mb-2">Error Loading Watchlist</h2>
            <p className="text-muted-foreground mb-4">
              There was a problem loading your watchlist.
            </p>
            <Button onClick={() => refetchWatchlist()}>Try Again</Button>
          </div>
        ) : teams.length === 0 ? (
          // Empty State
          <div className="text-center py-16 sm:py-24">
            <div className="inline-flex items-center justify-center w-24 h-24 rounded-full bg-muted mb-6 animate-in fade-in zoom-in duration-500">
              <Star className="h-12 w-12 text-muted-foreground" />
            </div>
            <h2 className="text-2xl sm:text-3xl font-display text-foreground mb-3">
              No Teams Yet
            </h2>
            <p className="text-muted-foreground font-sans max-w-md mx-auto mb-8">
              Start building your dashboard by adding teams from the rankings.
              Track their performance, get insights, and never miss a move.
            </p>
            <Link href="/rankings">
              <Button size="lg" className="gap-2 font-semibold">
                <Sparkles className="h-5 w-5" />
                Explore Rankings
              </Button>
            </Link>
          </div>
        ) : (
          <>
            {/* Controls Bar */}
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 mb-8">
              {/* Filters */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Filter className="h-4 w-4" />
                  <span className="font-medium">Filter:</span>
                </div>

                <Select value={filterAge} onValueChange={setFilterAge}>
                  <SelectTrigger className="w-[100px]">
                    <SelectValue placeholder="Age" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Ages</SelectItem>
                    {availableAges.map((age) => (
                      <SelectItem key={age} value={age.toString()}>
                        U{age}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select value={filterGender} onValueChange={setFilterGender}>
                  <SelectTrigger className="w-[100px]">
                    <SelectValue placeholder="Gender" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All</SelectItem>
                    <SelectItem value="M">Boys</SelectItem>
                    <SelectItem value="F">Girls</SelectItem>
                  </SelectContent>
                </Select>

                <Select value={filterState} onValueChange={setFilterState}>
                  <SelectTrigger className="w-[100px]">
                    <SelectValue placeholder="State" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All States</SelectItem>
                    {availableStates.map((state) => (
                      <SelectItem key={state} value={state}>
                        {state}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {/* Sort */}
                <div className="flex items-center gap-2 ml-2">
                  <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
                  <Select
                    value={sortBy}
                    onValueChange={(v) => setSortBy(v as SortOption)}
                  >
                    <SelectTrigger className="w-[130px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="rank">By Rank</SelectItem>
                      <SelectItem value="power">By Power</SelectItem>
                      <SelectItem value="name">By Name</SelectItem>
                      <SelectItem value="record">By Record</SelectItem>
                      <SelectItem value="movers">Big Movers</SelectItem>
                      <SelectItem value="activity">Recent Activity</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {/* Batch Actions */}
              <div className="flex items-center gap-3">
                {selectedIds.size > 0 ? (
                  <>
                    <span className="text-sm text-muted-foreground">
                      {selectedIds.size} selected
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={deselectAll}
                      className="text-xs"
                    >
                      Deselect
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={removeSelected}
                      className="gap-1"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Remove
                    </Button>
                  </>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={selectAll}
                    disabled={filteredTeams.length === 0}
                    className="text-xs"
                  >
                    Select All
                  </Button>
                )}
              </div>
            </div>

            {/* Results Info */}
            {filteredTeams.length !== teams.length && (
              <p className="text-sm text-muted-foreground mb-4">
                Showing {filteredTeams.length} of {teams.length} teams
              </p>
            )}

            {/* Team Grid */}
            {filteredTeams.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-muted-foreground">No teams match your filters.</p>
                <Button
                  variant="link"
                  onClick={() => {
                    setFilterAge("all");
                    setFilterState("all");
                    setFilterGender("all");
                  }}
                  className="mt-2"
                >
                  Clear filters
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {filteredTeams.map((team, index) => (
                  <Card
                    key={team.team_id_master}
                    className={cn(
                      "group relative overflow-hidden transition-all duration-300 hover:shadow-lg hover:-translate-y-1",
                      "animate-in fade-in slide-in-from-bottom-4",
                      selectedIds.has(team.team_id_master) && "ring-2 ring-primary"
                    )}
                    style={{
                      animationDelay: `${index * 50}ms`,
                      animationFillMode: "backwards",
                    }}
                  >
                    {/* Selection checkbox */}
                    <button
                      onClick={() => toggleSelect(team.team_id_master)}
                      className="absolute top-3 right-3 z-10 p-1 rounded hover:bg-muted/80 transition-colors"
                      aria-label={
                        selectedIds.has(team.team_id_master)
                          ? "Deselect team"
                          : "Select team"
                      }
                    >
                      {selectedIds.has(team.team_id_master) ? (
                        <CheckSquare className="h-5 w-5 text-primary" />
                      ) : (
                        <Square className="h-5 w-5 text-muted-foreground group-hover:text-foreground transition-colors" />
                      )}
                    </button>

                    {/* New games badge */}
                    {team.new_games_count > 0 && (
                      <div className="absolute top-3 left-3 z-10">
                        <span className="inline-flex items-center gap-1 text-xs font-medium bg-green-500/20 text-green-700 dark:text-green-400 px-2 py-0.5 rounded-full">
                          <CalendarDays className="h-3 w-3" />
                          {team.new_games_count} new
                        </span>
                      </div>
                    )}

                    <CardContent className="p-5 pt-10">
                      {/* Rank Badge & Team Info */}
                      <div className="flex items-start gap-4 mb-4">
                        <div className="flex flex-col items-center gap-1">
                          <div
                            className={cn(
                              "flex items-center justify-center w-12 h-12 rounded-lg font-display text-lg font-bold flex-shrink-0",
                              getRankBadgeClass(team.rank_in_cohort_final)
                            )}
                          >
                            {team.rank_in_cohort_final ?? "—"}
                          </div>
                          {/* Rank delta */}
                          <DeltaIndicator value={team.rank_change_7d} inverse />
                        </div>
                        <div className="flex-1 min-w-0">
                          <h3 className="font-display text-lg leading-tight truncate">
                            {team.team_name}
                          </h3>
                          {team.club_name && (
                            <p className="text-sm text-muted-foreground truncate">
                              {team.club_name}
                            </p>
                          )}
                          <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <Users className="h-3 w-3" />
                              U{team.age} {getGenderDisplay(team.gender)}
                            </span>
                            {team.state && (
                              <span className="flex items-center gap-1">
                                <MapPin className="h-3 w-3" />
                                {team.state}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Stats Grid */}
                      <div className="grid grid-cols-3 gap-3 mb-4">
                        <div className="text-center p-2 bg-muted/50 rounded-lg">
                          <p className="text-xs text-muted-foreground uppercase tracking-wide">
                            Power
                          </p>
                          <p className="font-mono font-semibold text-sm">
                            {formatPowerScore(team.power_score_final)}
                          </p>
                        </div>
                        <div className="text-center p-2 bg-muted/50 rounded-lg">
                          <p className="text-xs text-muted-foreground uppercase tracking-wide">
                            SOS
                          </p>
                          <p className="font-mono font-semibold text-sm">
                            {formatSOSIndex(team.sos_norm)}
                          </p>
                        </div>
                        <div className="text-center p-2 bg-muted/50 rounded-lg">
                          <p className="text-xs text-muted-foreground uppercase tracking-wide">
                            Record
                          </p>
                          <p className="font-mono font-semibold text-sm">
                            {team.wins}-{team.losses}-{team.draws}
                          </p>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center justify-between pt-3 border-t">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => removeSingle(team.team_id_master)}
                          className="text-destructive hover:text-destructive hover:bg-destructive/10 text-xs gap-1"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Remove
                        </Button>
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              setInsightModalTeam({
                                id: team.team_id_master,
                                name: team.team_name,
                              })
                            }
                            className="text-xs gap-1 text-primary hover:text-primary"
                          >
                            <Brain className="h-3.5 w-3.5" />
                            Insights
                          </Button>
                          <Link href={`/teams/${team.team_id_master}`}>
                            <Button variant="ghost" size="sm" className="text-xs gap-1">
                              View
                              <ChevronRight className="h-3.5 w-3.5" />
                            </Button>
                          </Link>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Insight Modal */}
      {insightModalTeam && (
        <InsightModal
          isOpen={!!insightModalTeam}
          onClose={() => setInsightModalTeam(null)}
          teamId={insightModalTeam.id}
          teamName={insightModalTeam.name}
        />
      )}
    </div>
  );
}
