import Image from 'next/image';
import { PageHeader } from '@/components/PageHeader';
import { HomeLeaderboard } from '@/components/HomeLeaderboard';
import { RecentMovers } from '@/components/RecentMovers';
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

  // Prefetch the same data that HomeLeaderboard and RecentMovers will need
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
  // Prefetch data on the server
  const dehydratedState = await prefetchRankingsData();

  return (
    <HydrationBoundary state={dehydratedState}>
    <div className="container mx-auto py-6 sm:py-8 px-4 sm:px-6">
      <div className="flex flex-col items-center mb-6 sm:mb-8 w-full">
        <div className="w-full max-w-3xl px-2 sm:px-4 flex justify-center">
          <Image
            src="/logos/pitchrank-logo-white.svg"
            alt="PitchRank"
            width={300}
            height={75}
            priority
            className="w-full h-auto max-w-[300px] sm:max-w-[400px] dark:hidden"
          />
          <Image
            src="/logos/pitchrank-logo-black.svg"
            alt="PitchRank"
            width={300}
            height={75}
            priority
            className="w-full h-auto max-w-[300px] sm:max-w-[400px] hidden dark:block"
          />
        </div>
      </div>
      <PageHeader
        title="Welcome to PitchRank"
        description="Comprehensive rankings for youth soccer teams across the United States"
      />
      
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <HomeLeaderboard />

        <RecentMovers />

        <Card>
          <CardHeader>
            <CardTitle>Quick Links</CardTitle>
            <CardDescription>Navigate to key sections</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link href="/rankings">
                View Rankings
              </Link>
            </Button>
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link href="/compare">
                Compare Teams
              </Link>
            </Button>
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link href="/methodology">
                Methodology
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
    </HydrationBoundary>
  );
}
