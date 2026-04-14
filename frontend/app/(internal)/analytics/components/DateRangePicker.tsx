'use client';
import { useRouter, useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { DATE_RANGE_PRESETS, DEFAULT_PRESET } from '@/lib/internal-analytics/constants';
import type { DateRangePreset } from '@/lib/internal-analytics/types';

const LABELS: Record<DateRangePreset, string> = {
  today: 'Today',
  last_7_days: 'Last 7 days',
  last_28_days: 'Last 28 days',
  mtd: 'Month to date',
};

export function DateRangePicker() {
  const router = useRouter();
  const params = useSearchParams();
  const current = (params.get('range') as DateRangePreset) ?? DEFAULT_PRESET;

  const setRange = (preset: DateRangePreset) => {
    const next = new URLSearchParams(params.toString());
    next.set('range', preset);
    router.push(`?${next.toString()}`, { scroll: false });
  };

  return (
    <div className="flex gap-2 flex-wrap">
      {DATE_RANGE_PRESETS.map((p) => (
        <Button key={p} variant={p === current ? 'default' : 'outline'} size="sm" onClick={() => setRange(p)}>
          {LABELS[p]}
        </Button>
      ))}
    </div>
  );
}
