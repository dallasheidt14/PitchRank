'use client';
import { useQuery } from '@tanstack/react-query';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Row = { query: string; clicks: number; impressions: number; ctr: number; position: number };
type Resp = { rows: Row[]; row_count: number };

export function TopQueriesTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['gsc_top_queries', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/gsc/top-queries?range=${range}&limit=10`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError) state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: 'empty' };
  else if (q.data) state = { status: 'success' };

  return (
    <TileShell title="Top Queries" description="Most-clicked search terms" state={state}>
      {q.data && (
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th>Query</th>
              <th className="text-right">Clicks</th>
              <th className="text-right">Pos.</th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((r) => (
              <tr key={r.query} className="border-t">
                <td className="py-1 truncate max-w-[180px]" title={r.query}>
                  {r.query}
                </td>
                <td className="text-right">{r.clicks.toLocaleString()}</td>
                <td className="text-right">{r.position.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </TileShell>
  );
}
