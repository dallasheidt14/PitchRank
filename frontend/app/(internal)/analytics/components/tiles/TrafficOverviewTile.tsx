'use client';
import { useQuery } from '@tanstack/react-query';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Row = { date: string; sessions: number; activeUsers: number; screenPageViews: number };
type Resp = {
  rows: Row[];
  totals: { sessions: number; activeUsers: number; screenPageViews: number };
  row_count: number;
  warnings: string[];
};

export function TrafficOverviewTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['ga4_overview', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/overview?range=${range}`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError) state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: 'empty', suggestion: 'Try a wider date range.' };
  else if (q.data) state = { status: 'success' };

  return (
    <TileShell title="Traffic" description="Sessions, users, pageviews" state={state}>
      {q.data && (
        <div className="space-y-3">
          <div className="flex gap-6 text-sm">
            <div>
              <div className="text-muted-foreground">Sessions</div>
              <div className="text-xl font-semibold">{q.data.totals.sessions.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-muted-foreground">Users</div>
              <div className="text-xl font-semibold">{q.data.totals.activeUsers.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-muted-foreground">Views</div>
              <div className="text-xl font-semibold">{q.data.totals.screenPageViews.toLocaleString()}</div>
            </div>
          </div>
          <div className="h-32">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={q.data.rows}>
                <XAxis dataKey="date" hide />
                <YAxis hide />
                <Tooltip />
                <Line dataKey="sessions" type="monotone" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </TileShell>
  );
}
