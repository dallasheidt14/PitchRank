'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Legend,
  Area,
  ComposedChart,
  ReferenceLine,
} from 'recharts';
import { useTeamTrajectory } from '@/lib/hooks';
import { useMemo } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface TeamTrajectoryChartProps {
  teamId: string;
}

/**
 * TeamTrajectoryChart component - displays team performance over time using Recharts
 */
export function TeamTrajectoryChart({ teamId }: TeamTrajectoryChartProps) {
  const { data: trajectory, isLoading, isError, error, refetch } = useTeamTrajectory(teamId, 30);

  const chartData = useMemo(() => {
    if (!trajectory || trajectory.length === 0) return [];

    return trajectory.map((point) => ({
      period: new Date(point.period_start).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      }),
      goalDifferential: point.avg_goals_for - point.avg_goals_against,
      avgGoalsFor: point.avg_goals_for,
      avgGoalsAgainst: point.avg_goals_against,
      gamesPlayed: point.games_played,
      winPercentage: point.win_percentage,
    }));
  }, [trajectory]);

  // Calculate trend: compare first half vs second half of periods
  const trend = useMemo(() => {
    if (chartData.length < 2) return 'neutral';

    const midpoint = Math.floor(chartData.length / 2);
    const firstHalf = chartData.slice(0, midpoint);
    const secondHalf = chartData.slice(midpoint);

    const firstAvg = firstHalf.reduce((sum, d) => sum + d.goalDifferential, 0) / firstHalf.length;
    const secondAvg = secondHalf.reduce((sum, d) => sum + d.goalDifferential, 0) / secondHalf.length;

    const diff = secondAvg - firstAvg;

    if (diff > 0.3) return 'up';
    if (diff < -0.3) return 'down';
    return 'neutral';
  }, [chartData]);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Performance Trajectory</CardTitle>
          <CardDescription>Team performance over time</CardDescription>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={300} />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Performance Trajectory</CardTitle>
          <CardDescription>Team performance over time</CardDescription>
        </CardHeader>
        <CardContent>
          <ErrorDisplay error={error} retry={refetch} fallback={
            <div className="h-64 flex items-center justify-center text-muted-foreground">
              <p>No trajectory data available</p>
            </div>
          } />
        </CardContent>
      </Card>
    );
  }

  if (!trajectory || trajectory.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Performance Trajectory</CardTitle>
          <CardDescription>Team performance over time</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-64 flex items-center justify-center text-muted-foreground">
            <p>No trajectory data available</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div>
              <CardTitle>Goal Differential Trajectory</CardTitle>
              <CardDescription>Average goal margin by 30-day period</CardDescription>
            </div>
            {trend === 'up' && (
              <div className="flex items-center gap-1 text-green-600 dark:text-green-400">
                <TrendingUp size={20} />
                <span className="text-sm font-medium">Improving</span>
              </div>
            )}
            {trend === 'down' && (
              <div className="flex items-center gap-1 text-red-600 dark:text-red-400">
                <TrendingDown size={20} />
                <span className="text-sm font-medium">Declining</span>
              </div>
            )}
            {trend === 'neutral' && (
              <div className="flex items-center gap-1 text-muted-foreground">
                <Minus size={20} />
                <span className="text-sm font-medium">Stable</span>
              </div>
            )}
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="text-xs text-muted-foreground cursor-help focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded"
                aria-label="Trajectory chart information"
              >
                ℹ️
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              <p className="font-semibold mb-1">Goal Differential</p>
              <p className="text-xs">Shows average goal margin (goals for - goals against) per period.</p>
              <p className="text-xs mt-1">Positive values = winning by that margin on average.</p>
              <p className="text-xs">Negative values = losing by that margin on average.</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
            <XAxis
              dataKey="period"
              className="text-xs"
              tick={{ fill: 'currentColor' }}
              stroke="currentColor"
            />
            <YAxis
              className="text-xs"
              tick={{ fill: 'currentColor' }}
              stroke="currentColor"
              label={{
                value: 'Goal Differential',
                angle: -90,
                position: 'insideLeft',
                style: { fontSize: '12px', fill: 'currentColor' }
              }}
            />
            <RechartsTooltip
              content={({ active, payload, label }) => {
                if (!active || !payload || !payload.length) return null;
                const data = payload[0].payload;
                return (
                  <div className="bg-card border border-border rounded-lg p-3 shadow-lg">
                    <p className="font-semibold mb-2">{label}</p>
                    <div className="space-y-1 text-sm">
                      <p className={`font-medium ${data.goalDifferential >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                        Goal Diff: {data.goalDifferential >= 0 ? '+' : ''}{data.goalDifferential.toFixed(2)}
                      </p>
                      <p className="text-muted-foreground">
                        Goals For: {data.avgGoalsFor.toFixed(2)}
                      </p>
                      <p className="text-muted-foreground">
                        Goals Against: {data.avgGoalsAgainst.toFixed(2)}
                      </p>
                      <p className="text-muted-foreground">
                        Win %: {data.winPercentage.toFixed(1)}%
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">
                        ({data.gamesPlayed} games)
                      </p>
                    </div>
                  </div>
                );
              }}
            />
            {/* Reference line at 0 */}
            <ReferenceLine
              y={0}
              stroke="hsl(var(--muted-foreground))"
              strokeDasharray="3 3"
              strokeWidth={1}
            />
            {/* Area fill with gradient for positive/negative zones */}
            <defs>
              <linearGradient id="goalDiffGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="rgb(34, 197, 94)" stopOpacity={0.3} />
                <stop offset="50%" stopColor="rgb(100, 100, 100)" stopOpacity={0.1} />
                <stop offset="100%" stopColor="rgb(239, 68, 68)" stopOpacity={0.3} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="goalDifferential"
              fill="url(#goalDiffGradient)"
              stroke="none"
            />
            {/* Main line */}
            <Line
              type="monotone"
              dataKey="goalDifferential"
              stroke={(data: any) => {
                // This won't work per-point, so we'll use a single color
                return "hsl(var(--primary))";
              }}
              strokeWidth={3}
              dot={(props: any) => {
                const { cx, cy, payload } = props;
                const color = payload.goalDifferential >= 0
                  ? 'rgb(34, 197, 94)'
                  : 'rgb(239, 68, 68)';
                return (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={5}
                    fill={color}
                    stroke="white"
                    strokeWidth={2}
                  />
                );
              }}
              name="Goal Differential"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

