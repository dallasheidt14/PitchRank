'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useTeamGames } from '@/lib/hooks';
import { useMemo, useState, useEffect, useRef } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { GameWithTeams } from '@/lib/types';
import { trackChartViewed } from '@/lib/events';

interface MomentumMeterProps {
  teamId: string;
}

// Threshold for over/underperformance (same as GameHistoryTable)
const PERFORMANCE_THRESHOLD = 2.0;

interface MomentumResult {
  score: number;
  greens: number;
  reds: number;
  neutrals: number;
  totalGames: number;
}

/**
 * Get color based on momentum score
 * Uses shades of green for positive momentum, red for negative
 */
function interpolateMomentumColor(score: number): string {
  if (score < 25) {
    // Dark red for slumping
    return 'hsl(0, 70%, 35%)';
  } else if (score < 50) {
    // Light red for struggling
    return 'hsl(0, 65%, 50%)';
  } else if (score < 60) {
    // Gray for as expected
    return 'hsl(0, 0%, 50%)';
  } else if (score < 80) {
    // Light green for building momentum
    return 'hsl(120, 50%, 45%)';
  } else {
    // Dark green for hot streak
    return 'hsl(120, 70%, 32%)';
  }
}

/**
 * Calculate momentum from recent games using ml_overperformance from game data
 * Uses the same data as GameHistoryTable for consistency
 */
function calculateMomentum(
  teamId: string,
  games: GameWithTeams[],
  numberOfGames: number = 8
): MomentumResult {
  const recentGames = games.slice(0, numberOfGames);

  if (recentGames.length === 0) {
    return { score: 50, greens: 0, reds: 0, neutrals: 0, totalGames: 0 };
  }

  // Count greens, reds, neutrals based on ml_overperformance
  let greens = 0;
  let reds = 0;
  let neutrals = 0;

  for (const game of recentGames) {
    const isHome = game.home_team_master_id === teamId;

    // Get ml_overperformance from team's perspective (same as GameHistoryTable)
    // Database stores from home team's perspective, so flip sign for away team
    let performanceDelta = 0;
    if (game.ml_overperformance !== null && game.ml_overperformance !== undefined) {
      performanceDelta = isHome ? game.ml_overperformance : -game.ml_overperformance;
    }

    // Categorize based on performance threshold (same as GameHistoryTable: ±2)
    if (performanceDelta >= PERFORMANCE_THRESHOLD) {
      greens++;
    } else if (performanceDelta <= -PERFORMANCE_THRESHOLD) {
      reds++;
    } else {
      neutrals++;
    }
  }

  // Calculate points: green = +1, red = -1, neutral = 0
  const points = greens - reds;

  // Cap at ±4 for realistic scoring
  const cappedPoints = Math.max(-4, Math.min(4, points));

  // Convert to 0-100 scale: 50 + (points × 12.5)
  const score = Math.max(0, Math.min(100, 50 + (cappedPoints * 12.5)));

  return {
    score,
    greens,
    reds,
    neutrals,
    totalGames: greens + reds + neutrals,
  };
}

/**
 * MomentumMeter component - displays team momentum based on recent performance
 */
export function MomentumMeter({ teamId }: MomentumMeterProps) {
  // Use same limit as GameHistoryTable (100) so React Query serves from shared cache
  // instead of firing a separate Supabase request. MomentumMeter only reads the first 8 games.
  const { data: gamesData, isLoading: gamesLoading, isError: gamesError, error: gamesErrorObj, refetch } = useTeamGames(teamId, 100);

  const [animatedScore, setAnimatedScore] = useState(50);
  const [momentumData, setMomentumData] = useState<MomentumResult | null>(null);
  const hasTrackedView = useRef(false);

  // Track chart view when momentum data is available
  useEffect(() => {
    if (momentumData && momentumData.totalGames > 0 && !hasTrackedView.current) {
      hasTrackedView.current = true;
      trackChartViewed({
        chart_type: 'momentum',
        team_id_master: teamId,
      });
    }
  }, [momentumData, teamId]);

  // Calculate momentum when games data is available
  useEffect(() => {
    if (!gamesData?.games || gamesData.games.length === 0) {
      setMomentumData(null);
      return;
    }

    const result = calculateMomentum(teamId, gamesData.games, 8);
    setMomentumData(result);
  }, [gamesData, teamId]);

  // Animate score change
  useEffect(() => {
    if (!momentumData) return;

    const targetScore = momentumData.score;
    const duration = 800;
    const startTime = Date.now();
    const startScore = animatedScore;
    let animationId: number | null = null;

    const animate = () => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const easeOut = 1 - Math.pow(1 - progress, 3);
      const currentScore = startScore + (targetScore - startScore) * easeOut;

      setAnimatedScore(currentScore);

      if (progress < 1) {
        animationId = requestAnimationFrame(animate);
      } else {
        setAnimatedScore(targetScore);
      }
    };

    if (Math.abs(targetScore - startScore) > 0.1) {
      animationId = requestAnimationFrame(animate);
    } else {
      setAnimatedScore(targetScore);
    }

    return () => {
      if (animationId !== null) {
        cancelAnimationFrame(animationId);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [momentumData?.score]);

  const momentumLabel = useMemo(() => {
    if (!momentumData) return 'As Expected';
    const score = momentumData.score;
    if (score >= 80) return 'Hot Streak';
    if (score >= 60) return 'Building Momentum';
    if (score >= 50) return 'As Expected';
    if (score >= 25) return 'Struggling';
    return 'Slumping';
  }, [momentumData]);

  const momentumColor = useMemo(() => {
    return interpolateMomentumColor(animatedScore);
  }, [animatedScore]);

  if (gamesLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Momentum</CardTitle>
          <CardDescription>Performance trend over last 8 games</CardDescription>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={80} />
        </CardContent>
      </Card>
    );
  }

  if (gamesError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Momentum</CardTitle>
          <CardDescription>Performance trend over last 8 games</CardDescription>
        </CardHeader>
        <CardContent>
          <ErrorDisplay error={gamesErrorObj} retry={refetch} fallback={
            <div className="h-20 flex items-center justify-center text-muted-foreground">
              <p>Insufficient data to calculate momentum</p>
            </div>
          } />
        </CardContent>
      </Card>
    );
  }

  if (!momentumData || momentumData.totalGames === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Momentum</CardTitle>
          <CardDescription>Performance trend over last 8 games</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-20 flex items-center justify-center text-muted-foreground">
            <p>Insufficient data to calculate momentum</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const { totalGames } = momentumData;

  return (
    <Card className="border-l-4 border-l-accent">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="font-display uppercase tracking-wide">Recent Momentum</CardTitle>
            <CardDescription>Performance trend over last {totalGames} games</CardDescription>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="text-xs text-muted-foreground cursor-help focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded"
                aria-label="Momentum calculation information"
              >
                ℹ️
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              <p className="font-semibold mb-1">How Momentum is Calculated:</p>
              <p className="text-xs mb-2">Based on performance vs expectations in recent games.</p>
              <div className="text-xs space-y-1">
                <p><span className="text-green-600 font-semibold">Green</span> = Overperformed (beat expectations by 2+ goals)</p>
                <p><span className="text-red-600 font-semibold">Red</span> = Underperformed (missed expectations by 2+ goals)</p>
                <p><span className="text-muted-foreground">Neutral</span> = Performed as expected</p>
              </div>
            </TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex justify-center">
          <div
            className="px-6 py-3 rounded-lg text-lg font-bold text-white transition-all duration-300 shadow-md"
            style={{ backgroundColor: momentumColor }}
          >
            {momentumLabel}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
