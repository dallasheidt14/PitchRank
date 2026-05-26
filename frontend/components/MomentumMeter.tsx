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
  totalGames: number;
}

function interpolateMomentumColor(score: number): string {
  if (score < 22) return 'hsl(0, 70%, 35%)';
  if (score < 42) return 'hsl(0, 65%, 50%)';
  if (score < 58) return 'hsl(0, 0%, 50%)';
  if (score < 78) return 'hsl(120, 50%, 45%)';
  return 'hsl(120, 70%, 32%)';
}

// Per-game score lookup: [result][overperformance category]
// Result drives the sign; overperformance shifts magnitude within it.
// A win is always net-positive (min +0.2), a loss always net-negative (max -0.2).
const PER_GAME_SCORE: Record<string, Record<string, number>> = {
  W: { green: 1.0, neutral: 0.5, red: 0.2 },
  D: { green: 0.15, neutral: 0.0, red: -0.15 },
  L: { green: -0.2, neutral: -0.5, red: -1.0 },
};

function calculateMomentum(teamId: string, games: GameWithTeams[], numberOfGames: number = 8): MomentumResult {
  const recentGames = games.slice(0, numberOfGames);

  if (recentGames.length === 0) {
    return { score: 50, totalGames: 0 };
  }

  let totalPoints = 0;
  let counted = 0;

  for (const game of recentGames) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore === null || oppScore === null) continue;

    const result = teamScore > oppScore ? 'W' : teamScore < oppScore ? 'L' : 'D';

    let perfCat = 'neutral';
    if (game.ml_overperformance !== null && game.ml_overperformance !== undefined) {
      const delta = isHome ? game.ml_overperformance : -game.ml_overperformance;
      if (delta >= PERFORMANCE_THRESHOLD) perfCat = 'green';
      else if (delta <= -PERFORMANCE_THRESHOLD) perfCat = 'red';
    }

    totalPoints += PER_GAME_SCORE[result][perfCat];
    counted++;
  }

  if (counted === 0) {
    return { score: 50, totalGames: 0 };
  }

  const avg = totalPoints / counted;
  const score = Math.max(0, Math.min(100, 50 + avg * 50));

  return { score, totalGames: counted };
}

/**
 * MomentumMeter component - displays team momentum based on recent performance
 */
export function MomentumMeter({ teamId }: MomentumMeterProps) {
  // Use same limit as GameHistoryTable (100) so React Query serves from shared cache
  // instead of firing a separate Supabase request. MomentumMeter only reads the first 8 games.
  const {
    data: gamesData,
    isLoading: gamesLoading,
    isError: gamesError,
    error: gamesErrorObj,
    refetch,
  } = useTeamGames(teamId, 100);

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
    if (score >= 78) return 'Hot Streak';
    if (score >= 58) return 'Building Momentum';
    if (score >= 42) return 'As Expected';
    if (score >= 22) return 'Struggling';
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
          <ErrorDisplay
            error={gamesErrorObj}
            retry={refetch}
            fallback={
              <div className="h-20 flex items-center justify-center text-muted-foreground">
                <p>Insufficient data to calculate momentum</p>
              </div>
            }
          />
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
              <p className="text-xs mb-2">
                Blends recent results (wins, losses, draws) with how the team performed relative to expectations.
              </p>
              <div className="text-xs space-y-1">
                <p>Wins push momentum up, losses pull it down.</p>
                <p>
                  <span className="text-green-600 font-semibold">Dominant</span> wins boost it further;{' '}
                  <span className="text-red-600 font-semibold">close</span> wins still count positively.
                </p>
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
