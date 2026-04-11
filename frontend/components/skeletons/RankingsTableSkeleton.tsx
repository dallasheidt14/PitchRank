import { useSyncExternalStore } from 'react';
import { TableSkeleton } from '@/components/ui/skeletons';

const emptySubscribe = () => () => {};

/**
 * RankingsTableSkeleton - Loading skeleton for rankings table
 *
 * Renders a plain spacer during SSR (no animate-pulse) to avoid
 * Google's Soft 404 classifier flagging the page as broken.
 * The pulsing skeleton only appears after client hydration.
 */
export function RankingsTableSkeleton({ rows = 10 }: { rows?: number }) {
  const isClient = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );

  if (!isClient) return <div className="min-h-[480px]" />;

  return <TableSkeleton rows={rows} />;
}
