'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useTeamGames, useTeam } from '@/lib/hooks';
import { useMemo, useState, useEffect } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { api } from '@/lib/api';
import type { GameWithTeams } from '@/lib/types';

interface MomentumMeterProps {
  teamId: string;
}

// Constants for momentum calculation
const PERFORMANCE_GOAL_SCALE = 5.0; // Expected goal margin per 1.0 power difference
const PERFORMANCE_THRESHOLD = 2.0; // Threshold for over/underperformance

interface MomentumResult {
  score: number;
  greens: number;
  reds: number;
  neutrals: number;
  totalGames: number;
}

/**
 * Interpolate color from red → gray → lime based on score (0-100)
 */
function interpolateMomentumColor(score: number): string {
  if (score < 25) {
    // Red for slumping
    return 'hsl(0, 70%, 45%)';
  } else if (score < 50) {
    // Orange-red for struggling
    const t = (score - 25) / 25;
    return `hsl(${20 * t}, ${70 - 20 * t}%, ${45 + 5 * t}%)`;
  } else if (score < 60) {
    // Gray for as expected
    return 'hsl(0, 0%, 50%)';
  } else if (score < 80) {
    // Yellow-green for building
    const t = (score - 60) / 20;
    return `hsl(${60 + 30 * t}, ${50 + 20 * t}%, 45%)`;
  } else {
    // Green for hot streak
    return 'hsl(120, 70%, 40%)';
  }
}

/**
 * Calculate momentum from recent games using simple green/red/neutral point system
 */
async function calculateMomentum(
  teamId: string,
  teamPower: number | null,
  games: GameWithTeams[],
  numberOfGames: number = 8
): Promise<MomentumResult> {
  const recentGames = games.slice(0, numberOfGames);

  if (recentGames.length === 0) {
    return { score: 50, greens: 0, reds: 0, neutrals: 0, totalGames: 0 };
  }

  // Get opponent team IDs
  const opponentIds = recentGames
    .map(game => {
      const oppId = game.home_team_master_id === teamId
        ? game.away_team_master_id
        : game.home_team_master_id;
      return oppId;
    })
    .filter((id): id is string => id !== null);

  // Fetch opponent rankings
  const opponentRankings = await api.getTeamRankings(opponentIds);

  // Count greens, reds, neutrals
  let greens = 0;
  let reds = 0;
  let neutrals = 0;

  for (const game of recentGames) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;
    const opponentId = isHome ? game.away_team_master_id : game.home_team_master_id;

    if (teamScore === null || oppScore === null || !opponentId) {
      continue;
    }

    const goalDiff = teamScore - oppScore;
    const opponentRanking = opponentRankings.get(opponentId);
    const opponentPower = opponentRanking?.power_score_final ?? null;

    // Calculate performance delta
    let performanceDelta = 0;
    if (teamPower !== null && opponentPower !== null) {
      const powerDiff = teamPower - opponentPower;
      const expectedMargin = PERFORMANCE_GOAL_SCALE * powerDiff;
      performanceDelta = goalDiff - expectedMargin;
    }

    // Categorize based on performance threshold
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
  const { data: gamesData, isLoading: gamesLoading, isError: gamesError, error: gamesErrorObj, refetch } = useTeamGames(teamId, 12);
  const { data: teamData, isLoading: teamLoading } = useTeam(teamId);

  const [animatedScore, setAnimatedScore] = useState(50);
  const [momentumData, setMomentumData] = useState<MomentumResult | null>(null);

  // Calculate momentum when games data is available
  useEffect(() => {
    if (!gamesData?.games || gamesData.games.length === 0) {
      setMomentumData(null);
      return;
    }

    let isMounted = true;
    const teamPower = teamData?.power_score_final ?? null;

    calculateMomentum(teamId, teamPower, gamesData.games, 8)
      .then(result => {
        if (isMounted) {
          setMomentumData(result);
        }
      })
      .catch(error => {
        console.error('Error calculating momentum:', error);
        if (isMounted) {
          setMomentumData(null);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [gamesData, teamData, teamId]);

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

  if (gamesLoading || teamLoading) {
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
