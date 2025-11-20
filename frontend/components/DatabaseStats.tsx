'use client';

import { useDbStats } from '@/lib/hooks';

/**
 * DatabaseStats component displays total games and ranked teams from the database
 * Used on the homepage to show the scale of data being tracked
 */
export function DatabaseStats() {
  const { data: stats, isLoading, isError } = useDbStats();

  if (isLoading) {
    return (
      <div className="flex items-center gap-6 text-sm sm:text-base font-medium tracking-wide opacity-80">
        <span className="animate-pulse">Loading stats...</span>
      </div>
    );
  }

  if (isError || !stats) {
    return null; // Gracefully hide on error
  }

  // Format numbers with commas
  const formatNumber = (num: number) => num.toLocaleString();

  return (
    <div className="flex flex-wrap items-center gap-4 sm:gap-6 text-sm sm:text-base font-medium tracking-wide">
      <div className="flex items-center gap-2">
        <span className="text-2xl sm:text-3xl font-bold text-accent">
          {formatNumber(stats.total_games)}
        </span>
        <span className="opacity-80">Games Tracked</span>
      </div>
      <div className="hidden sm:block w-px h-6 bg-primary-foreground/30" aria-hidden="true" />
      <div className="flex items-center gap-2">
        <span className="text-2xl sm:text-3xl font-bold text-accent">
          {formatNumber(stats.total_teams)}
        </span>
        <span className="opacity-80">Teams Ranked</span>
      </div>
    </div>
  );
}
