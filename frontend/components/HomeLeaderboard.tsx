'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ListSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useRankings } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { usePrefetchTeam } from '@/lib/hooks';
import { useState, useEffect } from 'react';
import { formatPowerScore } from '@/lib/utils';
import { Button } from '@/components/ui/button';

/**
 * Cohort configuration for carousel
 */
interface Cohort {
  age: string;
  gender: 'M' | 'F';
  displayAge: string;
  displayGender: string;
}

const COHORTS: Cohort[] = [
  { age: 'u10', gender: 'M', displayAge: 'U10', displayGender: 'Boys' },
  { age: 'u10', gender: 'F', displayAge: 'U10', displayGender: 'Girls' },
  { age: 'u11', gender: 'M', displayAge: 'U11', displayGender: 'Boys' },
  { age: 'u11', gender: 'F', displayAge: 'U11', displayGender: 'Girls' },
  { age: 'u12', gender: 'M', displayAge: 'U12', displayGender: 'Boys' },
  { age: 'u12', gender: 'F', displayAge: 'U12', displayGender: 'Girls' },
  { age: 'u13', gender: 'M', displayAge: 'U13', displayGender: 'Boys' },
  { age: 'u13', gender: 'F', displayAge: 'U13', displayGender: 'Girls' },
  { age: 'u14', gender: 'M', displayAge: 'U14', displayGender: 'Boys' },
  { age: 'u14', gender: 'F', displayAge: 'U14', displayGender: 'Girls' },
  { age: 'u15', gender: 'M', displayAge: 'U15', displayGender: 'Boys' },
  { age: 'u15', gender: 'F', displayAge: 'U15', displayGender: 'Girls' },
  { age: 'u16', gender: 'M', displayAge: 'U16', displayGender: 'Boys' },
  { age: 'u16', gender: 'F', displayAge: 'U16', displayGender: 'Girls' },
  { age: 'u17', gender: 'M', displayAge: 'U17', displayGender: 'Boys' },
  { age: 'u17', gender: 'F', displayAge: 'U17', displayGender: 'Girls' },
  { age: 'u18', gender: 'M', displayAge: 'U18', displayGender: 'Boys' },
  { age: 'u18', gender: 'F', displayAge: 'U18', displayGender: 'Girls' },
];

/**
 * HomeLeaderboard component - displays featured rankings carousel on the home page
 * Shows top 10 national teams rotating through age groups U10-U18, Male & Female
 * Auto-rotates every 15 seconds, pauses on hover
 */
export function HomeLeaderboard() {
  const [currentIndex, setCurrentIndex] = useState(4); // Start at U12 Male (index 4)
  const [isPaused, setIsPaused] = useState(false);
  const prefetchTeam = usePrefetchTeam();

  const currentCohort = COHORTS[currentIndex];
  const { data: rankings, isLoading, isError, error, refetch } = useRankings(
    null,
    currentCohort.age,
    currentCohort.gender
  );

  // Get top 10 teams
  const topTeams = rankings?.slice(0, 10) || [];

  // Auto-rotation every 15 seconds
  useEffect(() => {
    if (isPaused) return;

    const interval = setInterval(() => {
      setCurrentIndex((prev) => (prev + 1) % COHORTS.length);
    }, 15000);

    return () => clearInterval(interval);
  }, [isPaused]);

  const handlePrevious = () => {
    setCurrentIndex((prev) => (prev - 1 + COHORTS.length) % COHORTS.length);
  };

  const handleNext = () => {
    setCurrentIndex((prev) => (prev + 1) % COHORTS.length);
  };

  return (
    <Card
      className="overflow-hidden border-0 shadow-lg"
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => setIsPaused(false)}
    >
      {/* Header with gradient background */}
      <CardHeader className="bg-gradient-to-r from-primary to-[oklch(0.28_0.08_165)] text-primary-foreground relative overflow-hidden">
        <div className="absolute right-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <div className="flex items-center justify-between">
          <div className="flex-1">
            <CardTitle className="text-2xl sm:text-3xl font-bold uppercase tracking-wide">
              Top 10 Rankings
            </CardTitle>
            <CardDescription className="text-primary-foreground/80 text-base">
              {currentCohort.displayAge} {currentCohort.displayGender} • National • Power Score
            </CardDescription>
          </div>

          {/* Carousel Controls */}
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={handlePrevious}
              className="h-8 w-8 text-primary-foreground hover:bg-primary-foreground/20"
              aria-label="Previous cohort"
            >
              <ChevronLeft className="h-5 w-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleNext}
              className="h-8 w-8 text-primary-foreground hover:bg-primary-foreground/20"
              aria-label="Next cohort"
            >
              <ChevronRight className="h-5 w-5" />
            </Button>
          </div>
        </div>

        {/* Carousel Indicators */}
        <div className="flex gap-1.5 mt-3 justify-center">
          {COHORTS.map((_, index) => (
            <button
              key={index}
              onClick={() => setCurrentIndex(index)}
              className={`h-1.5 rounded-full transition-all ${
                index === currentIndex
                  ? 'w-6 bg-primary-foreground'
                  : 'w-1.5 bg-primary-foreground/30 hover:bg-primary-foreground/50'
              }`}
              aria-label={`Go to ${COHORTS[index].displayAge} ${COHORTS[index].displayGender}`}
            />
          ))}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading && <ListSkeleton items={10} />}

        {isError && (
          <ErrorDisplay error={error} retry={refetch} />
        )}

        {!isLoading && !isError && (
          <div className="divide-y divide-border">
            {topTeams.length === 0 ? (
              <div className="text-sm text-muted-foreground text-center py-8 px-4">
                <p>No rankings data available for this cohort</p>
              </div>
            ) : (
              topTeams.map((team, index) => {
                // Use real historical rank change data (7-day change)
                const rankChange = team.rank_change_7d ?? 0;
                const isTopThree = index < 3;

                // Determine badge style based on rank
                const getBadgeClass = (idx: number) => {
                  if (idx === 0) return 'badge-gold';
                  if (idx === 1) return 'badge-silver';
                  if (idx === 2) return 'badge-bronze';
                  return 'bg-secondary text-secondary-foreground';
                };

                return (
                  <Link
                    key={team.team_id_master}
                    href={`/teams/${team.team_id_master}`}
                    onMouseEnter={() => prefetchTeam(team.team_id_master)}
                    className={`flex items-center justify-between p-4 hover:bg-secondary/50 transition-all duration-300 group ${
                      isTopThree ? 'bg-accent/5' : ''
                    }`}
                    aria-label={`View ${team.team_name} team details`}
                    tabIndex={0}
                  >
                    <div className="flex items-center gap-4 sm:gap-6 flex-1 min-w-0">
                      <div className={`flex-shrink-0 w-10 sm:w-12 h-10 sm:h-12 rounded-full flex items-center justify-center font-bold text-lg sm:text-xl ${getBadgeClass(index)}`}>
                        {team.rank_in_cohort_final || '—'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-base sm:text-lg truncate group-hover:text-primary transition-colors">
                          {team.team_name}
                        </div>
                        <div className="text-sm text-muted-foreground truncate">
                          {team.club_name && <span className="font-medium">{team.club_name}</span>}
                          {team.state && (
                            <span className={team.club_name ? ' • ' : ''}>
                              {team.state}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 sm:gap-6 flex-shrink-0">
                      {rankChange !== 0 && (
                        <div className={`flex items-center gap-1 text-sm font-semibold ${
                          rankChange > 0 ? 'text-green-600' : 'text-red-600'
                        }`}>
                          {rankChange > 0 ? (
                            <ArrowUp className="h-4 w-4" />
                          ) : (
                            <ArrowDown className="h-4 w-4" />
                          )}
                          {Math.abs(rankChange)}
                        </div>
                      )}
                      <div className="text-right">
                        <div className="font-mono font-bold text-base sm:text-lg">
                          {formatPowerScore(team.power_score_final)}
                        </div>
                        <div className="text-xs text-muted-foreground uppercase tracking-wide">Power Score</div>
                      </div>
                    </div>
                  </Link>
                );
              })
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
