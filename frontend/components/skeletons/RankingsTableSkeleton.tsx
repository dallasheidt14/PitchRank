import { TableSkeleton } from '@/components/ui/skeletons';

/**
 * RankingsTableSkeleton - Loading skeleton for rankings table
 * Reuses the existing TableSkeleton component
 */
export function RankingsTableSkeleton({ rows = 10 }: { rows?: number }) {
  return <TableSkeleton rows={rows} />;
}

