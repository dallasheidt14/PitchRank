'use client';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

const LABELS: Record<DateRangePreset, string> = {
  today: 'Today',
  last_7_days: 'Last 7 days',
  last_28_days: 'Last 28 days',
  mtd: 'Month to date',
};

export function DateContextChip({ range }: { range: DateRangePreset }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
      Using: {LABELS[range]}
    </span>
  );
}
