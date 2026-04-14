'use client';
import { useQuery } from '@tanstack/react-query';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Row = {
  source: string;
  views: number;
  subscriptions: number;
  conversion_rate: number;
};

type Resp = {
  rows: Row[];
  row_count: number;
  totals: { views: number; subscriptions: number };
  derived: { conversion_rate: number };
  warnings?: string[];
};

export function UpgradeSourcesTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['ga4_upgrade_sources', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/upgrade-sources?range=${range}&limit=10`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError)
    state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: 'empty' };
  else if (q.data) state = { status: 'success' };

  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;

  return (
    <TileShell
      title="Upgrade Sources"
      description="Where upgrade views and subscriptions come from"
      state={state}
    >
      {q.data && (
        <>
          {q.data.warnings && q.data.warnings.length > 0 && (
            <p className="text-xs text-amber-600 mb-2">{q.data.warnings[0]}</p>
          )}
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th>Source</th>
                <th className="text-right">Views</th>
                <th className="text-right">Subs</th>
                <th className="text-right">Conv.</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r, i) => (
                <tr key={`${r.source}-${i}`} className="border-t">
                  <td className="py-1 truncate max-w-[140px]" title={r.source}>
                    {r.source}
                  </td>
                  <td className="text-right">{r.views.toLocaleString()}</td>
                  <td className="text-right">{r.subscriptions.toLocaleString()}</td>
                  <td className="text-right">{fmtPct(r.conversion_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </TileShell>
  );
}
