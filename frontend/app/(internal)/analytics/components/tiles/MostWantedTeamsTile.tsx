'use client';
import { useQuery } from '@tanstack/react-query';
import { TileShell, type TileState } from './TileShell';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

type Row = {
  team_id: string;
  team_name?: string;
  paywall_impressions: number;
};

type Resp = {
  rows: Row[];
  row_count: number;
  totals: { paywall_impressions: number };
  warnings?: string[];
};

export function MostWantedTeamsTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ['ga4_most_wanted_teams', range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/most-wanted-teams?range=${range}&limit=10`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? 'Request failed');
      return r.json();
    },
  });

  let state: TileState = { status: 'loading' };
  if (q.isError)
    state = { status: 'error', message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: 'empty' };
  else if (q.data) state = { status: 'success' };

  return (
    <TileShell
      title="Most Wanted Teams"
      description="Teams non-premium users try to access most"
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
                <th>Team</th>
                <th className="text-right">Impressions</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r, i) => (
                <tr key={`${r.team_id}-${i}`} className="border-t">
                  <td className="py-1 truncate max-w-[180px]" title={r.team_id}>
                    {r.team_name ?? r.team_id}
                  </td>
                  <td className="text-right">{r.paywall_impressions.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </TileShell>
  );
}
