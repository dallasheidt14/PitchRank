'use client';
import { useQuery } from '@tanstack/react-query';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Row = { date: string; clicks: number; impressions: number; ctr: number; position: number };
type Resp = {
  rows: Row[];
  totals: { clicks: number; impressions: number; ctr: number; position: number };
  derived: Record<string, number>;
  row_count: number;
};

export function SearchPerformanceTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['gsc_performance', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/gsc/performance?range=${range}&compare=1`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError) state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: 'empty' };
  else if (q.data) state = { status: 'success' };

  return (
    <TileShell title="Search Performance" description="Clicks · impressions · CTR · position" state={state}>
      {q.data && (
        <div className="space-y-3">
          <div className="grid grid-cols-4 gap-2 text-sm">
            <div>
              <div className="text-muted-foreground">Clicks</div>
              <div className="text-lg font-semibold">{q.data.totals.clicks.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-muted-foreground">Impressions</div>
              <div className="text-lg font-semibold">{q.data.totals.impressions.toLocaleString()}</div>
            </div>
            <div>
              <div className="text-muted-foreground">CTR</div>
              <div className="text-lg font-semibold">{(q.data.totals.ctr * 100).toFixed(2)}%</div>
            </div>
            <div>
              <div className="text-muted-foreground">Pos.</div>
              <div className="text-lg font-semibold">{q.data.totals.position.toFixed(1)}</div>
            </div>
          </div>
          <div className="h-32">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={q.data.rows}>
                <XAxis dataKey="date" hide />
                <YAxis hide />
                <Tooltip />
                <Line dataKey="clicks" type="monotone" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </TileShell>
  );
}
