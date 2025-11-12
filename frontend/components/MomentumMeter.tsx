'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import {
  RadialBarChart,
  RadialBar,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { useTeamTrajectory } from '@/lib/hooks';
import { useMemo, useState, useEffect } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

interface MomentumMeterProps {
  teamId: string;
}

/**
 * Interpolate color from red → gray → lime based on score (0-100)
 */
function interpolateMomentumColor(score: number): string {
  // Red (low) → Gray (mid) → Lime (high)
  if (score < 33) {
    // Red to gray: score 0-33
    const t = score / 33;
    // Red: hsl(0, 70%, 50%) → Gray: hsl(0, 0%, 50%)
    return `hsl(0, ${70 * (1 - t)}%, 50%)`;
  } else if (score < 66) {
    // Gray: score 33-66
    return 'hsl(0, 0%, 50%)';
  } else {
    // Gray to lime: score 66-100
    const t = (score - 66) / 34;
    // Gray: hsl(0, 0%, 50%) → Lime: hsl(120, 70%, 50%)
    return `hsl(${120 * t}, ${70 * t}%, 50%)`;
  }
}

/**
 * MomentumMeter component - displays team momentum using RadialBarChart with animations
 */
export function MomentumMeter({ teamId }: MomentumMeterProps) {
  const { data: trajectory, isLoading, isError } = useTeamTrajectory(teamId, 30);
  const [animatedScore, setAnimatedScore] = useState(0);

  const momentumData = useMemo(() => {
    if (!trajectory || trajectory.length < 2) return null;

    const recent = trajectory[trajectory.length - 1];
    const previous = trajectory[trajectory.length - 2];

    const winPercentageChange = recent.win_percentage - previous.win_percentage;
    const goalsForChange = recent.avg_goals_for - previous.avg_goals_for;
    const goalsAgainstChange = previous.avg_goals_against - recent.avg_goals_against; // Inverted (lower is better)

    // Calculate momentum score (0-100)
    const momentumScore = Math.max(
      0,
      Math.min(
        100,
        50 + winPercentageChange * 0.5 + goalsForChange * 10 + goalsAgainstChange * 10
      )
    );

    return {
      score: momentumScore,
      color: interpolateMomentumColor(momentumScore),
    };
  }, [trajectory]);

  // Animate score change
  useEffect(() => {
    if (momentumData) {
      const targetScore = momentumData.score;
      const duration = 1000; // 1 second animation
      const startTime = Date.now();
      const startScore = animatedScore;

      const animate = () => {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease-out animation
        const easeOut = 1 - Math.pow(1 - progress, 3);
        const currentScore = startScore + (targetScore - startScore) * easeOut;
        
        setAnimatedScore(currentScore);

        if (progress < 1) {
          requestAnimationFrame(animate);
        } else {
          setAnimatedScore(targetScore);
        }
      };

      requestAnimationFrame(animate);
    }
  }, [momentumData?.score]);

  const momentumLabel = useMemo(() => {
    if (!momentumData) return 'Neutral';
    const score = momentumData.score;
    if (score >= 70) return 'Strong';
    if (score >= 40) return 'Moderate';
    return 'Weak';
  }, [momentumData]);

  const chartData = useMemo(() => {
    if (!momentumData) return null;
    return [
      {
        name: 'Momentum',
        value: animatedScore,
        fill: momentumData.color,
      },
    ];
  }, [momentumData, animatedScore]);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Momentum</CardTitle>
          <CardDescription>Team performance trend</CardDescription>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={200} />
        </CardContent>
      </Card>
    );
  }

  if (isError || !momentumData || !chartData) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Momentum</CardTitle>
          <CardDescription>Team performance trend</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-48 flex items-center justify-center text-muted-foreground">
            <p>Insufficient data to calculate momentum</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Momentum</CardTitle>
            <CardDescription>Team performance trend</CardDescription>
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
            <TooltipContent>
              <p>Based on recent win percentage and goal trends</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center">
          <ResponsiveContainer width="100%" height={200}>
            <RadialBarChart
              innerRadius="60%"
              outerRadius="90%"
              data={chartData}
              startAngle={90}
              endAngle={-270}
            >
              <RadialBar
                dataKey="value"
                cornerRadius={10}
                isAnimationActive={true}
                animationDuration={1000}
                animationBegin={0}
                animationEasing="ease-out"
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </RadialBar>
            </RadialBarChart>
          </ResponsiveContainer>
          <div className="mt-4 text-center">
            <div className="text-3xl font-bold transition-all duration-300">
              {animatedScore.toFixed(0)}
            </div>
            <div className="text-sm text-muted-foreground">{momentumLabel} Momentum</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

