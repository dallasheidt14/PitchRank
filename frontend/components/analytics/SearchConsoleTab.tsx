'use client';

import { useSearchConsole } from '@/hooks/useAnalytics';
import { MetricCard } from './MetricCard';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';

function formatCtr(ctr: number): string {
  return `${(ctr * 100).toFixed(1)}%`;
}

function formatPosition(pos: number): string {
  return pos.toFixed(1);
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-full bg-white/10" />
      ))}
    </div>
  );
}

interface SearchConsoleTabProps {
  range: string;
}

export function SearchConsoleTab({ range }: SearchConsoleTabProps) {
  const { data, isLoading, error } = useSearchConsole(range);

  if (error) {
    return <p className="text-red-400">Failed to load Search Console data: {error.message}</p>;
  }

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard title="Total Clicks" value={data ? data.totals.clicks.toLocaleString() : '—'} loading={isLoading} />
        <MetricCard
          title="Total Impressions"
          value={data ? data.totals.impressions.toLocaleString() : '—'}
          loading={isLoading}
        />
        <MetricCard title="Average CTR" value={data ? formatCtr(data.totals.ctr) : '—'} loading={isLoading} />
        <MetricCard
          title="Average Position"
          value={data ? formatPosition(data.totals.position) : '—'}
          loading={isLoading}
        />
      </div>

      {/* Top queries */}
      <div>
        <h3 className="mb-3 text-lg font-semibold text-white">Top Queries</h3>
        {isLoading ? (
          <TableSkeleton />
        ) : (
          <div className="rounded-lg border border-white/10 bg-white/5">
            <Table>
              <TableHeader>
                <TableRow className="border-white/10 hover:bg-white/5">
                  <TableHead className="text-gray-400">Query</TableHead>
                  <TableHead className="text-right text-gray-400">Clicks</TableHead>
                  <TableHead className="text-right text-gray-400">Impressions</TableHead>
                  <TableHead className="text-right text-gray-400">CTR</TableHead>
                  <TableHead className="text-right text-gray-400">Position</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.topQueries.map((row) => (
                  <TableRow key={row.query} className="border-white/10 hover:bg-white/5">
                    <TableCell className="text-white">{row.query}</TableCell>
                    <TableCell className="text-right text-gray-300">{row.clicks.toLocaleString()}</TableCell>
                    <TableCell className="text-right text-gray-300">{row.impressions.toLocaleString()}</TableCell>
                    <TableCell className="text-right text-gray-300">{formatCtr(row.ctr)}</TableCell>
                    <TableCell className="text-right text-gray-300">{formatPosition(row.position)}</TableCell>
                  </TableRow>
                ))}
                {data?.topQueries.length === 0 && (
                  <TableRow className="border-white/10">
                    <TableCell colSpan={5} className="text-center text-gray-500">
                      No data for this period
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Top pages */}
      <div>
        <h3 className="mb-3 text-lg font-semibold text-white">Top Pages</h3>
        {isLoading ? (
          <TableSkeleton />
        ) : (
          <div className="rounded-lg border border-white/10 bg-white/5">
            <Table>
              <TableHeader>
                <TableRow className="border-white/10 hover:bg-white/5">
                  <TableHead className="text-gray-400">Page</TableHead>
                  <TableHead className="text-right text-gray-400">Clicks</TableHead>
                  <TableHead className="text-right text-gray-400">Impressions</TableHead>
                  <TableHead className="text-right text-gray-400">CTR</TableHead>
                  <TableHead className="text-right text-gray-400">Position</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.topPages.map((row) => (
                  <TableRow key={row.page} className="border-white/10 hover:bg-white/5">
                    <TableCell className="max-w-[300px] truncate text-white" title={row.page}>
                      {row.page.replace('https://www.pitchrank.io', '')}
                    </TableCell>
                    <TableCell className="text-right text-gray-300">{row.clicks.toLocaleString()}</TableCell>
                    <TableCell className="text-right text-gray-300">{row.impressions.toLocaleString()}</TableCell>
                    <TableCell className="text-right text-gray-300">{formatCtr(row.ctr)}</TableCell>
                    <TableCell className="text-right text-gray-300">{formatPosition(row.position)}</TableCell>
                  </TableRow>
                ))}
                {data?.topPages.length === 0 && (
                  <TableRow className="border-white/10">
                    <TableCell colSpan={5} className="text-center text-gray-500">
                      No data for this period
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
