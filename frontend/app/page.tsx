import { HomeLeaderboard } from '@/components/HomeLeaderboard';
import { RecentMovers } from '@/components/RecentMovers';
import { HomeStats } from '@/components/HomeStats';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { dehydrate, HydrationBoundary, QueryClient } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import { normalizeAgeGroup } from '@/lib/utils';
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

  return dehydrate(queryClient);
}

export default async function Home() {
  // Prefetch rankings data on the server
  let dehydratedState;

  try {
    dehydratedState = await prefetchRankingsData();
  } catch (error) {
    console.error('Error prefetching data:', error);
    dehydratedState = dehydrate(new QueryClient());
  }

  return (
    <HydrationBoundary state={dehydratedState}>
      {/* Hero Section - Athletic Editorial Style */}
      <div className="relative bg-gradient-to-br from-primary via-primary to-[oklch(0.28_0.08_163)] text-primary-foreground py-16 sm:py-24 overflow-hidden">
        {/* Diagonal stripe pattern overlay */}
        <div className="absolute inset-0 bg-diagonal-stripes opacity-50" aria-hidden="true" />
        {/* Diagonal slash accent */}
        <div className="absolute left-0 top-0 w-3 h-full bg-accent -skew-x-12" aria-hidden="true" />

        <div className="container mx-auto px-4 sm:px-6 relative">
          <div className="max-w-4xl">
            <h1 className="font-display text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-bold uppercase leading-tight mb-4">
              <span className="text-gradient-athletic">America&apos;s</span>{' '}
              <span className="relative inline-block">
                <span className="text-accent">Definitive</span>
                <span className="absolute bottom-0 left-0 w-full h-1 sm:h-1.5 bg-accent" aria-hidden="true" />
              </span>
              <br />
              <span className="text-gradient-athletic">Youth Soccer Rankings</span>
            </h1>
            <p className="text-lg sm:text-xl md:text-2xl font-light tracking-wide mb-8">
              Data-driven performance analytics for U10-U18 boys and girls nationwide
            </p>

            {/* Stats Row - Client component for reliable data fetching */}
            <HomeStats />

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
        <div className="grid gap-4 sm:gap-6 lg:grid-cols-3">
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
