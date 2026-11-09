import { TableSkeleton } from '@/components/ui/skeletons';
import { useIsClient } from '@/hooks/useIsClient';

/**
 * RankingsTableSkeleton - Loading skeleton for rankings table
 *
 * Renders a plain spacer during SSR (no animate-pulse) to avoid
 * Google's Soft 404 classifier flagging the page as broken.
 * The pulsing skeleton only appears after client hydration.
 */
export function RankingsTableSkeleton({ rows = 10 }: { rows?: number }) {
  const isClient = useIsClient();

  if (!isClient) return <div className="min-h-[660px]" />;

  return <TableSkeleton rows={rows} />;
}
