'use client';

import { useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer } from 'recharts';
import { useTeamUpcomingGames } from '@/lib/hooks';

const DAYS_AHEAD = 14;

interface UpcomingGamesTableProps {
  teamId: string;
}

function localDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function UpcomingGamesTable({ teamId }: UpcomingGamesTableProps) {
  // Bump fetch limit so a busy team's 14-day window isn't truncated upstream.
  const { data, isLoading, isError, error, refetch } = useTeamUpcomingGames(teamId, 100);
  const games = data?.games;

  const { bars, total } = useMemo(() => {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const buckets = Array.from({ length: DAYS_AHEAD }, (_, i) => {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      return {
        key: localDateKey(d),
        label: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        weekday: d.toLocaleDateString('en-US', { weekday: 'short' }),
        count: 0,
      };
    });
    const idx = new Map(buckets.map((b, i) => [b.key, i] as const));
    let inWindow = 0;
    for (const g of games ?? []) {
      const i = idx.get(g.game_date);
      if (i !== undefined) {
        buckets[i].count++;
        inWindow++;
      }
    }
    return { bars: buckets, total: inWindow };
  }, [games]);

  const Header = (
    <CardHeader>
      <CardTitle className="font-display uppercase tracking-wide">Upcoming Games</CardTitle>
      <CardDescription>Next {DAYS_AHEAD} days</CardDescription>
    </CardHeader>
  );

  if (isLoading) {
    return (
      <Card>
        {Header}
        <CardContent>
          <ChartSkeleton />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        {Header}
        <CardContent>
          <ErrorDisplay
            error={error}
            retry={refetch}
            fallback={
              <div className="text-center py-6 text-muted-foreground text-sm">
                <p>No upcoming games scheduled</p>
              </div>
            }
          />
        </CardContent>
      </Card>
    );
  }

  if (total === 0) {
    return (
      <Card>
        {Header}
        <CardContent>
          <div className="text-center py-6 text-muted-foreground text-sm">
            <p>No upcoming games scheduled</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-l-4 border-l-primary overflow-hidden">
      {Header}
      <CardContent>
        <p className="text-sm text-muted-foreground mb-2">
          {total === 1 ? '1 scheduled match' : `${total} scheduled matches`}
        </p>
        <div className="h-48 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={0} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
              <RechartsTooltip
                cursor={{ fill: 'rgba(0,0,0,0.04)' }}
                contentStyle={{ fontSize: 12 }}
                labelFormatter={(_label, payload) => {
                  const p = payload?.[0]?.payload as { weekday?: string; label?: string } | undefined;
                  return p ? `${p.weekday}, ${p.label}` : '';
                }}
                formatter={(value) => {
                  const n = typeof value === 'number' ? value : Number(value ?? 0);
                  return [n === 1 ? '1 game' : `${n} games`, 'Scheduled'];
                }}
              />
              <Bar dataKey="count" fill="currentColor" className="text-primary" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
