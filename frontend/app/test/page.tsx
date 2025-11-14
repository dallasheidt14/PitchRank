'use client';

import { useRankings } from '@/lib/hooks';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { formatPowerScore } from '@/lib/utils';

// Force dynamic rendering to prevent build-time errors when env vars aren't set
export const dynamic = 'force-dynamic';

/**
 * Test page to verify data layer integration
 * This page demonstrates fetching and displaying data from Supabase
 * using React Query hooks
 */
export default function TestPage() {
  // Fetch rankings (national, all age groups, all genders)
  // This will return teams with their ranking information
  const { data: rankings, isLoading, isError, error } = useRankings();

  return (
    <div className="container mx-auto py-8 px-4">
      <Card>
        <CardHeader>
          <CardTitle>Data Layer Test Page</CardTitle>
          <CardDescription>
            Testing Supabase → React Query integration. This page fetches team
            rankings from the database.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="space-y-4">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          )}

          {isError && (
            <div className="rounded-lg bg-destructive/10 p-4 text-destructive">
              <h3 className="font-semibold mb-2">Error Loading Data</h3>
              <p className="text-sm">
                {error instanceof Error ? error.message : 'Unknown error occurred'}
              </p>
              <p className="text-xs mt-2 text-muted-foreground">
                Check your Supabase connection in .env.local
              </p>
            </div>
          )}

          {rankings && rankings.length > 0 && (
            <div className="space-y-4">
              <div className="text-sm text-muted-foreground">
                Found {rankings.length} teams with rankings
              </div>
              <div className="grid gap-2 max-h-[600px] overflow-y-auto">
                {rankings.slice(0, 50).map((ranking) => (
                  <div
                    key={ranking.team_id_master}
                    className="flex items-center justify-between p-3 rounded-lg border bg-card"
                  >
                    <div className="flex-1">
                      <div className="font-medium">{ranking.team_name}</div>
                      <div className="text-sm text-muted-foreground">
                        {ranking.club_name && (
                          <span>{ranking.club_name} • </span>
                        )}
                        U{ranking.age} {ranking.gender === 'M' ? 'Boys' : ranking.gender === 'F' ? 'Girls' : ranking.gender}
                        {ranking.state && (
                          <span> • {ranking.state}</span>
                        )}
                      </div>
                    </div>
                    <div className="text-right ml-4">
                      {ranking.rank_in_cohort_final && (
                        <div className="font-semibold">#{ranking.rank_in_cohort_final}</div>
                      )}
                      <div className="text-xs text-muted-foreground">
                        Score: {formatPowerScore(ranking.power_score_final)}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {rankings.length > 50 && (
                <div className="text-sm text-muted-foreground text-center pt-2">
                  Showing first 50 of {rankings.length} teams
                </div>
              )}
            </div>
          )}

          {rankings && rankings.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              No rankings data found. Make sure your database is populated.
            </div>
          )}
        </CardContent>
      </Card>

      {/* Debug Info */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="text-sm">Debug Information</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs font-mono space-y-1">
            <div>
              <span className="text-muted-foreground">Status:</span>{' '}
              {isLoading ? 'Loading...' : isError ? 'Error' : 'Success'}
            </div>
            {rankings && (
              <div>
                <span className="text-muted-foreground">Teams loaded:</span>{' '}
                {rankings.length}
              </div>
            )}
            {rankings && rankings.length > 0 && (
              <div>
                <span className="text-muted-foreground">Sample team ID:</span>{' '}
                {rankings[0].team_id_master}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

