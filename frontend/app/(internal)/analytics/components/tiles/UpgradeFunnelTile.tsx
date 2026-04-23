'use client';
import { useQuery } from '@tanstack/react-query';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type FunnelRow = {
  step: string;
  label: string;
  count: number;
  pct_of_top: number;
};

type Derived = {
  conversion_rate: number;
  cart_abandonment: number;
};

type Resp = {
  rows: FunnelRow[];
  row_count: number;
  derived: Derived;
  warnings?: string[];
};

export function UpgradeFunnelTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['ga4_upgrade_funnel', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/upgrade-funnel?range=${range}`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError) state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: 'empty' };
  else if (q.data) state = { status: 'success' };

  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;

  return (
    <TileShell title="Upgrade Funnel" description="4-step conversion from page view to subscription" state={state}>
      {q.data && (
        <div className="space-y-3">
          {q.data.rows.map((row) => (
            <div key={row.step}>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-muted-foreground">{row.label}</span>
                <span className="font-medium tabular-nums">{row.count.toLocaleString()}</span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.max(row.pct_of_top * 100, row.count > 0 ? 2 : 0)}%` }}
                />
              </div>
            </div>
          ))}
          <div className="pt-2 border-t flex gap-4 text-xs text-muted-foreground">
            <span>
              Conversion: <span className="text-foreground font-medium">{fmtPct(q.data.derived.conversion_rate)}</span>
            </span>
            <span>
              Cart abandonment:{' '}
              <span className="text-foreground font-medium">{fmtPct(q.data.derived.cart_abandonment)}</span>
            </span>
          </div>
        </div>
      )}
    </TileShell>
  );
}
