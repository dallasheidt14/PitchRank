'use client';

import Image from 'next/image';
import { PageHeader } from '@/components/PageHeader';
import { HomeLeaderboard } from '@/components/HomeLeaderboard';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { useRankings } from '@/lib/hooks';
import { useMemo } from 'react';
import { ArrowUp, ArrowDown } from 'lucide-react';
import { usePrefetchTeam } from '@/lib/hooks';

export default function Home() {
  const { data: rankings } = useRankings(null, 'u12', 'Male');
  const prefetchTeam = usePrefetchTeam();

  // Calculate recent movers (teams with largest rank changes)
  const recentMovers = useMemo(() => {
    if (!rankings || rankings.length < 10) return [];
    
    // For demo purposes, simulate rank changes by comparing with previous position
    // In a real app, this would come from historical ranking data
    return rankings.slice(0, 20).map((team, index) => {
      const previousRank = index > 0 ? rankings[index - 1].national_rank : null;
      const rankChange = previousRank && team.national_rank
        ? previousRank - team.national_rank
        : 0;
      return { ...team, rankChange };
    }).filter(team => Math.abs(team.rankChange) > 0)
      .sort((a, b) => Math.abs(b.rankChange) - Math.abs(a.rankChange))
      .slice(0, 5);
  }, [rankings]);

  return (
    <div className="container mx-auto py-8 px-4">
      <div className="flex flex-col items-center mb-6 sm:mb-8 w-full">
        <div className="w-full max-w-3xl px-2 sm:px-4 flex justify-center">
          <Image
            src="/logos/pitchrank-wordmark.svg"
            alt="PitchRank"
            width={300}
            height={75}
            priority
            className="w-full h-auto max-w-[300px] sm:max-w-[400px] dark:invert dark:hue-rotate-180"
          />
        </div>
      </div>
      <PageHeader
        title="Welcome to PitchRank"
        description="Comprehensive rankings for youth soccer teams across the United States"
      />
      
      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <HomeLeaderboard />
        
        <Card>
          <CardHeader>
            <CardTitle>Recent Movers</CardTitle>
            <CardDescription>Teams with significant rank changes</CardDescription>
          </CardHeader>
          <CardContent>
            {recentMovers.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recent movers data available</p>
            ) : (
              <div className="space-y-2">
                {recentMovers.map((team) => (
                  <Link
                    key={team.team_id_master}
                    href={`/teams/${team.team_id_master}`}
                    onMouseEnter={() => prefetchTeam(team.team_id_master)}
                    className="flex items-center justify-between p-2 rounded-md hover:bg-accent hover:shadow-sm transition-all duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary"
                    aria-label={`View ${team.team_name} team details`}
                    tabIndex={0}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm truncate">{team.team_name}</div>
                      <div className="text-xs text-muted-foreground">
                        Rank #{team.national_rank}
                      </div>
                    </div>
                    <div className={`flex items-center gap-1 text-xs font-semibold ${
                      team.rankChange > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                    }`}>
                      {team.rankChange > 0 ? (
                        <ArrowUp className="h-3 w-3" />
                      ) : (
                        <ArrowDown className="h-3 w-3" />
                      )}
                      {Math.abs(team.rankChange)}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

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
  );
}
