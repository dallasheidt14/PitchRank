'use client';
import { useQuery } from '@tanstack/react-query';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Row = {
  pagePath: string;
  screenPageViews: number;
  activeUsers: number;
  engagementRate: number;
};
type Resp = { rows: Row[]; row_count: number };

export function TopPagesTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['ga4_top_pages', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/top-pages?range=${range}&limit=10`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError) state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: 'empty' };
  else if (q.data) state = { status: 'success' };

  return (
    <TileShell title="Top Pages" description="Most viewed pages" state={state}>
      {q.data && (
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th>Page</th>
              <th className="text-right">Views</th>
              <th className="text-right">Eng.</th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((r) => (
              <tr key={r.pagePath} className="border-t">
                <td className="py-1 truncate max-w-[160px]" title={r.pagePath}>
                  {r.pagePath}
                </td>
                <td className="text-right">{r.screenPageViews.toLocaleString()}</td>
                <td className="text-right">{(r.engagementRate * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </TileShell>
  );
}
