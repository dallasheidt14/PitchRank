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
} from 'recharts';
import { useTeamTrajectory } from '@/lib/hooks';
import { useMemo } from 'react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

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
      winPercentage: point.win_percentage,
      avgGoalsFor: point.avg_goals_for,
      avgGoalsAgainst: point.avg_goals_against,
      gamesPlayed: point.games_played,
    }));
  }, [trajectory]);

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
          <div>
            <CardTitle>Performance Trajectory</CardTitle>
            <CardDescription>Team performance metrics over time</CardDescription>
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
            <TooltipContent>
              <p>Shows win percentage and goal averages by 30-day periods</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
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
            />
            <RechartsTooltip
              contentStyle={{
                backgroundColor: 'hsl(var(--card))',
                border: '1px solid hsl(var(--border))',
                borderRadius: '0.5rem',
              }}
              labelStyle={{ color: 'hsl(var(--foreground))' }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="winPercentage"
              stroke="hsl(var(--chart-1))"
              strokeWidth={2}
              dot={{ r: 4 }}
              name="Win %"
            />
            <Line
              type="monotone"
              dataKey="avgGoalsFor"
              stroke="hsl(var(--chart-2))"
              strokeWidth={2}
              dot={{ r: 4 }}
              name="Avg Goals For"
            />
            <Line
              type="monotone"
              dataKey="avgGoalsAgainst"
              stroke="hsl(var(--chart-3))"
              strokeWidth={2}
              dot={{ r: 4 }}
              name="Avg Goals Against"
            />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

