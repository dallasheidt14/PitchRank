'use client';

import { useTrafficData } from '@/hooks/useAnalytics';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { MetricCard } from './MetricCard';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs.toString().padStart(2, '0')}s`;
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

interface TrafficTabProps {
  range: string;
}

export function TrafficTab({ range }: TrafficTabProps) {
  const { data, isLoading, error, refetch } = useTrafficData(range);

  if (error) {
    return <ErrorDisplay error={error} retry={refetch} />;
  }

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard title="Sessions" value={data ? data.overview.sessions.toLocaleString() : '—'} loading={isLoading} />
        <MetricCard
          title="Unique Users"
          value={data ? data.overview.users.toLocaleString() : '—'}
          loading={isLoading}
        />
        <MetricCard
          title="Page Views"
          value={data ? data.overview.pageviews.toLocaleString() : '—'}
          loading={isLoading}
        />
        <MetricCard
          title="Avg. Session Duration"
          value={data ? formatDuration(data.overview.avgSessionDuration) : '—'}
          loading={isLoading}
        />
      </div>

      {/* Referral sources */}
      <div>
        <h3 className="mb-3 text-lg font-semibold text-white">Referral Sources</h3>
        {isLoading ? (
          <TableSkeleton />
        ) : (
          <div className="rounded-lg border border-white/10 bg-white/5">
            <Table>
              <TableHeader>
                <TableRow className="border-white/10 hover:bg-white/5">
                  <TableHead className="text-gray-400">Source</TableHead>
                  <TableHead className="text-right text-gray-400">Sessions</TableHead>
                  <TableHead className="text-right text-gray-400">Users</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.referrals.map((row) => (
                  <TableRow key={row.source} className="border-white/10 hover:bg-white/5">
                    <TableCell className="text-white">{row.source}</TableCell>
                    <TableCell className="text-right text-gray-300">{row.sessions.toLocaleString()}</TableCell>
                    <TableCell className="text-right text-gray-300">{row.users.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
                {data?.referrals.length === 0 && (
                  <TableRow className="border-white/10">
                    <TableCell colSpan={3} className="text-center text-gray-500">
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
                  <TableHead className="text-right text-gray-400">Page Views</TableHead>
                  <TableHead className="text-right text-gray-400">Users</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.topPages.map((row) => (
                  <TableRow key={row.path} className="border-white/10 hover:bg-white/5">
                    <TableCell className="max-w-[400px] truncate text-white" title={row.path}>
                      {row.path}
                    </TableCell>
                    <TableCell className="text-right text-gray-300">{row.pageviews.toLocaleString()}</TableCell>
                    <TableCell className="text-right text-gray-300">{row.users.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
                {data?.topPages.length === 0 && (
                  <TableRow className="border-white/10">
                    <TableCell colSpan={3} className="text-center text-gray-500">
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
