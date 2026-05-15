'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import { useRankHistory } from '@/lib/hooks';
import { useMemo, useEffect, useRef } from 'react';
import { TrendingUp } from 'lucide-react';
import { trackChartViewed } from '@/lib/events';

interface RankHistoryChartProps {
  teamId: string;
}

/**
 * Compact rank history line chart showing Monday snapshots over the last 12 months.
 * Y-axis is inverted (rank #1 at top). Displays above MomentumMeter on team detail page.
 */
export function RankHistoryChart({ teamId }: RankHistoryChartProps) {
  const { data: history, isLoading, isError, error: _error, refetch } = useRankHistory(teamId);
  const hasTrackedView = useRef(false);

  useEffect(() => {
    if (history && history.length > 0 && !hasTrackedView.current) {
      hasTrackedView.current = true;
      trackChartViewed({
        chart_type: 'rank_history',
        team_id_master: teamId,
      });
    }
  }, [history, teamId]);

  const chartData = useMemo(() => {
    if (!history || history.length === 0) return [];

    return history.map((point) => {
      const d = new Date(point.snapshot_date + 'T00:00:00Z');
      const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
      const day = d.getUTCDate();
      const year = d.getUTCFullYear();
      // Append 2-digit year on January labels so the Dec→Jan boundary is unambiguous.
      const label = month === 'Jan' ? `${month} ${day} '${String(year).slice(2)}` : `${month} ${day}`;
      return {
        label,
        fullDate: point.snapshot_date,
        displayDate: `${month} ${day}, ${year}`,
        rank: point.rank,
      };
    });
  }, [history]);

  // One tick per month (first snapshot of each calendar month) — ~12 ticks for a year.
  const monthTicks = useMemo(() => {
    const seen = new Set<string>();
    const ticks: string[] = [];
    for (const d of chartData) {
      const key = d.fullDate.slice(0, 7); // YYYY-MM
      if (!seen.has(key)) {
        seen.add(key);
        ticks.push(d.label);
      }
    }
    return ticks;
  }, [chartData]);

  // Calculate Y-axis domain: pad slightly beyond min/max rank
  const yDomain = useMemo(() => {
    if (chartData.length === 0) return [1, 50];
    const ranks = chartData.map((d) => d.rank);
    const minRank = Math.min(...ranks);
    const maxRank = Math.max(...ranks);
    // Pad 10% on each side, minimum 1 at top
    const padding = Math.max(2, Math.ceil((maxRank - minRank) * 0.1));
    return [Math.max(1, minRank - padding), maxRank + padding];
  }, [chartData]);

  // Widen Y-axis when ranks have more digits so #1234 doesn't clip.
  const yAxisWidth = useMemo(() => {
    const maxDigits = String(yDomain[1]).length;
    return Math.max(40, maxDigits * 9 + 16);
  }, [yDomain]);

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Ranking History
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ChartSkeleton height={180} />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Ranking History
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ErrorDisplay error="Unable to load ranking history" retry={() => refetch()} />
        </CardContent>
      </Card>
    );
  }

  // Not enough data to chart
  if (chartData.length < 2) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Ranking History
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-4">
            Not enough data yet — ranking history builds each Monday
          </p>
        </CardContent>
      </Card>
    );
  }

  // Summary: current vs earliest rank
  const currentRank = chartData[chartData.length - 1].rank;
  const earliestRank = chartData[0].rank;
  const rankDelta = earliestRank - currentRank; // positive = improved

  const trendText =
    rankDelta > 0 ? `improved by ${rankDelta}` : rankDelta < 0 ? `declined by ${Math.abs(rankDelta)}` : 'unchanged';
  const ariaLabel = `Ranking history. Currently rank #${currentRank}, ${trendText} since ${chartData[0].displayDate}.`;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="font-display uppercase tracking-wide text-base flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Ranking History
          </CardTitle>
          <div className="flex items-center gap-2 text-sm">
            <span className="font-mono font-semibold">#{currentRank}</span>
            {rankDelta !== 0 && (
              <span
                className={
                  rankDelta > 0
                    ? 'text-green-600 dark:text-green-400 text-xs'
                    : 'text-red-600 dark:text-red-400 text-xs'
                }
              >
                {rankDelta > 0 ? `+${rankDelta}` : rankDelta}
              </span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="h-[180px] w-full" role="img" aria-label={ariaLabel}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                ticks={monthTicks}
                interval={0}
                className="fill-muted-foreground"
              />
              <YAxis
                reversed
                domain={yDomain}
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v: number) => `#${v}`}
                className="fill-muted-foreground"
                width={yAxisWidth}
                allowDecimals={false}
              />
              <RechartsTooltip
                content={({
                  active,
                  payload,
                }: {
                  active?: boolean;
                  payload?: ReadonlyArray<{ payload?: (typeof chartData)[0] }>;
                }) => {
                  if (!active || !payload?.[0]?.payload) return null;
                  const d = payload[0].payload;
                  return (
                    <div className="rounded-lg border bg-background p-2 shadow-md text-xs">
                      <p className="font-medium">{d.displayDate}</p>
                      <p className="text-primary font-mono font-semibold">Rank #{d.rank}</p>
                    </div>
                  );
                }}
              />
              {yDomain[0] <= 1 && (
                <ReferenceLine y={1} stroke="var(--muted-foreground)" strokeDasharray="3 3" strokeWidth={1} />
              )}
              <Line
                type="monotone"
                dataKey="rank"
                stroke="var(--primary)"
                strokeWidth={2}
                dot={chartData.length <= 16}
                activeDot={{ r: 4, strokeWidth: 2 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
