import { HomeLeaderboard } from '@/components/HomeLeaderboard';
import { RecentMovers } from '@/components/RecentMovers';
import { DatabaseStats } from '@/components/DatabaseStats';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { dehydrate, HydrationBoundary, QueryClient } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import { normalizeAgeGroup } from '@/lib/utils';
import { api } from '@/lib/api';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Prefetch rankings data on the server
 * This function runs on the server and fetches data before the page is sent to the client
 */
async function prefetchRankingsData() {
  const queryClient = new QueryClient();

  // Prefetch rankings data for HomeLeaderboard and RecentMovers
  await queryClient.prefetchQuery({
    queryKey: ['rankings', null, 'u12', 'M'],
    queryFn: async () => {
      // This mirrors the logic from useRankings hook
      const normalizedAge = normalizeAgeGroup('u12');

      let query = supabase
        .from('rankings_view')
        .select('*')
        .eq('status', 'Active');

      if (normalizedAge !== null) {
        query = query.eq('age', normalizedAge);
      }

      query = query.eq('gender', 'M');
      query = query.order('power_score_final', { ascending: false });

      const { data, error } = await query;

      if (error) {
        throw error;
      }

      return (data || []) as RankingRow[];
    },
    staleTime: 5 * 60 * 1000,
  });

  // Prefetch database stats for DatabaseStats component
  await queryClient.prefetchQuery({
    queryKey: ['db-stats'],
    queryFn: async () => {
      // Query total games count
      const { count: gamesCount, error: gamesError } = await supabase
        .from('games')
        .select('*', { count: 'exact', head: true });

      if (gamesError) {
        throw gamesError;
      }

      // Query total active ranked teams count
      const { count: teamsCount, error: teamsError } = await supabase
        .from('rankings_view')
        .select('*', { count: 'exact', head: true })
        .eq('status', 'Active');

      if (teamsError) {
        throw teamsError;
      }

      return {
        total_games: gamesCount || 0,
        total_teams: teamsCount || 0,
      };
    },
    staleTime: 60 * 60 * 1000, // 1 hour
  });

  return dehydrate(queryClient);
}

// Helper function to format numbers with commas (e.g., 16649 -> "16,649")
function formatStatNumber(num: number): string {
  return num.toLocaleString('en-US');
}

export default async function Home() {
  // Prefetch data on the server
  const dehydratedState = await prefetchRankingsData();

  // Fetch database stats
  let totalGames = 0;
  let totalTeams = 0;
  try {
    const stats = await api.getDbStats();
    totalGames = stats.total_games;
    totalTeams = stats.total_teams;
  } catch (error) {
    console.error('Error fetching db stats:', error);
    // Fall back to estimates if fetch fails
    totalGames = 16000;
    totalTeams = 2800;
  }

  return (
    <HydrationBoundary state={dehydratedState}>
      {/* Hero Section - Athletic Editorial Style */}
      <div className="relative bg-gradient-to-br from-primary via-primary to-[oklch(0.28_0.08_163)] text-primary-foreground py-16 sm:py-24 overflow-hidden">
        {/* Diagonal slash accent */}
        <div className="absolute left-0 top-0 w-3 h-full bg-accent -skew-x-12" aria-hidden="true" />

        <div className="container mx-auto px-4 sm:px-6 relative">
          <div className="max-w-4xl">
            <h1 className="font-display text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold uppercase leading-tight mb-4">
              America&apos;s{' '}
              <span className="relative inline-block">
                <span className="text-accent">Definitive</span>
                <span className="absolute bottom-0 left-0 w-full h-1 sm:h-1.5 bg-accent" aria-hidden="true" />
              </span>
              <br />
              Youth Soccer Rankings
            </h1>
            <p className="text-lg sm:text-xl md:text-2xl font-light tracking-wide mb-8">
              Data-driven performance analytics for U10-U18 boys and girls nationwide
            </p>

            {/* Stats Row */}
            <div className="grid grid-cols-3 gap-4 sm:gap-8 mb-8 max-w-2xl">
              <div className="text-center">
                <div className="font-mono text-3xl sm:text-4xl md:text-5xl font-bold text-accent">{formatStatNumber(totalGames)}</div>
                <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">Games Analyzed</div>
              </div>
              <div className="text-center">
                <div className="font-mono text-3xl sm:text-4xl md:text-5xl font-bold text-accent">{formatStatNumber(totalTeams)}</div>
                <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">Teams Ranked</div>
              </div>
              <div className="text-center">
                <div className="font-mono text-3xl sm:text-4xl md:text-5xl font-bold text-accent">50</div>
                <div className="text-xs sm:text-sm uppercase tracking-wide text-primary-foreground/80">States Covered</div>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button size="lg" variant="secondary" asChild className="font-semibold uppercase tracking-wide">
                <Link href="/rankings">
                  View Rankings
                </Link>
              </Button>
              <Button size="lg" variant="outline" asChild className="font-semibold uppercase tracking-wide bg-transparent border-primary-foreground text-primary-foreground hover:bg-primary-foreground hover:text-primary">
                <Link href="/methodology">
                  Our Methodology
                </Link>
              </Button>
            </div>
          </div>
        </div>

        {/* Decorative gradient overlay */}
        <div className="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t from-background to-transparent pointer-events-none" />
      </div>

      {/* Main Content */}
      <div className="container mx-auto py-8 sm:py-12 px-4 sm:px-6">
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Main Column - Leaderboard (takes 2 columns) */}
          <div className="lg:col-span-2">
            <HomeLeaderboard />
          </div>

          {/* Sidebar Column */}
          <div className="space-y-6">
            <RecentMovers />

            <Card className="border-l-4 border-l-accent">
              <CardHeader>
                <CardTitle className="text-xl">Quick Links</CardTitle>
                <CardDescription>Navigate to key sections</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button variant="outline" className="w-full justify-start font-semibold hover:bg-accent hover:text-accent-foreground transition-colors" asChild>
                  <Link href="/compare">
                    Compare Teams
                  </Link>
                </Button>
                <Button variant="outline" className="w-full justify-start font-semibold hover:bg-accent hover:text-accent-foreground transition-colors" asChild>
                  <Link href="/rankings/state">
                    State Rankings
                  </Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </HydrationBoundary>
  );
}
