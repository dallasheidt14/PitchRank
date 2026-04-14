'use client';
import { useQuery } from '@tanstack/react-query';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Resp = {
  totals: { upgradeViews: number; totalSessions: number };
  derived: { conversion_rate: number; conversion_rate_delta?: number; upgrade_views_delta?: number };
  row_count: number;
};

export function UpgradeViewsTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['ga4_upgrade_views', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/upgrade-views?range=${range}&compare=1`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError) state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.totals.upgradeViews === 0) state = { status: 'empty' };
  else if (q.data) state = { status: 'success' };

  return (
    <TileShell title="/upgrade Views" description="Pageviews + conversion rate" state={state}>
      {q.data && (
        <div className="space-y-2">
          <div className="text-3xl font-semibold">{q.data.totals.upgradeViews.toLocaleString()}</div>
          <div className="text-sm text-muted-foreground">
            {(q.data.derived.conversion_rate * 100).toFixed(2)}% of sessions
            {q.data.derived.upgrade_views_delta !== undefined && (
              <span
                className={`ml-2 ${q.data.derived.upgrade_views_delta >= 0 ? 'text-emerald-600' : 'text-destructive'}`}
              >
                {q.data.derived.upgrade_views_delta >= 0 ? '▲' : '▼'}{' '}
                {Math.abs(q.data.derived.upgrade_views_delta * 100).toFixed(0)}%
              </span>
            )}
          </div>
        </div>
      )}
    </TileShell>
  );
}
