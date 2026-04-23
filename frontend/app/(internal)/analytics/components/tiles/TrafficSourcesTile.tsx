'use client';
import { useQuery } from '@tanstack/react-query';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Row = {
  source: string;
  medium: string;
  sessions: number;
  activeUsers: number;
  engagementRate: number;
};
type Resp = { rows: Row[]; row_count: number };

export function TrafficSourcesTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['ga4_traffic_sources', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/traffic-sources?range=${range}&limit=10`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError) state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: 'empty' };
  else if (q.data) state = { status: 'success' };

  return (
    <TileShell title="Traffic Sources" description="Where your visitors come from" state={state}>
      {q.data && (
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th>Source / Medium</th>
              <th className="text-right">Sessions</th>
              <th className="text-right">Users</th>
            </tr>
          </thead>
          <tbody>
            {q.data.rows.map((r, i) => (
              <tr key={`${r.source}-${r.medium}-${i}`} className="border-t">
                <td className="py-1 truncate max-w-[180px]" title={`${r.source} / ${r.medium}`}>
                  {r.source} / {r.medium}
                </td>
                <td className="text-right">{r.sessions.toLocaleString()}</td>
                <td className="text-right">{r.activeUsers.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </TileShell>
  );
}
