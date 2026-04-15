'use client';
import { useQuery } from '@tanstack/react-query';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Row = { event: string; label: string; users: number };
type Resp = {
  rows: Row[];
  totals: { viewed: number; plan_selected: number; checkout_initiated: number; subscribed: number };
  derived: { view_to_plan: number; plan_to_checkout: number; checkout_to_subscribe: number; overall: number };
  row_count: number;
  warnings: string[];
};

export function ConversionFunnelTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['ga4_conversion_funnel', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/conversion-funnel?range=${range}`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError) state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.totals.viewed === 0) state = { status: 'empty', suggestion: 'Try a wider date range.' };
  else if (q.data) state = { status: 'success' };

  const max = q.data?.rows[0]?.users ?? 0;

  return (
    <TileShell title="Upgrade Funnel" description="Unique users per step" state={state}>
      {q.data && (
        <div className="space-y-2">
          {q.data.rows.map((row, i) => {
            const width = max === 0 ? 0 : Math.max(4, (row.users / max) * 100);
            const stepRate =
              i === 0
                ? null
                : row.users === 0 || q.data!.rows[i - 1].users === 0
                  ? 0
                  : row.users / q.data!.rows[i - 1].users;
            return (
              <div key={row.event} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">{row.label}</span>
                  <span className="font-medium">
                    {row.users.toLocaleString()}
                    {stepRate !== null && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        {(stepRate * 100).toFixed(1)}% from prev
                      </span>
                    )}
                  </span>
                </div>
                <div className="h-2 bg-muted rounded">
                  <div className="h-full bg-primary rounded" style={{ width: `${width}%` }} />
                </div>
              </div>
            );
          })}
          <div className="pt-2 text-xs text-muted-foreground">
            Overall: {(q.data.derived.overall * 100).toFixed(2)}% viewed → subscribed
          </div>
        </div>
      )}
    </TileShell>
  );
}
