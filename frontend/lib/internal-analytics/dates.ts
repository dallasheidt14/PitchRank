// frontend/lib/internal-analytics/dates.ts
import type { DateRange, DateRangePreset, DataFreshness } from './types';

const ISO = (d: Date): string => d.toISOString().slice(0, 10);

function dateInTz(date: Date, timeZone: string): string {
  // en-CA gives YYYY-MM-DD format
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}

export function todayInPropertyTz(timeZone: string): string {
  return dateInTz(new Date(), timeZone);
}

function addDaysISO(iso: string, delta: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + delta);
  return ISO(dt);
}

function startOfMonthISO(iso: string): string {
  return iso.slice(0, 8) + '01';
}

export function resolveDateRange(input: DateRangePreset | DateRange, timeZone: string): DateRange {
  if (typeof input === 'object') return { start: input.start, end: input.end };

  const today = todayInPropertyTz(timeZone);
  const yesterday = addDaysISO(today, -1);

  switch (input) {
    case 'today':
      return { start: today, end: today, preset: 'today' };
    case 'last_7_days':
      return { start: addDaysISO(yesterday, -6), end: yesterday, preset: 'last_7_days' };
    case 'last_28_days':
      return { start: addDaysISO(yesterday, -27), end: yesterday, preset: 'last_28_days' };
    case 'mtd':
      return { start: startOfMonthISO(today), end: today, preset: 'mtd' };
  }
}

export function rangeDays(r: DateRange): number {
  const [y1, m1, d1] = r.start.split('-').map(Number);
  const [y2, m2, d2] = r.end.split('-').map(Number);
  const a = Date.UTC(y1, m1 - 1, d1);
  const b = Date.UTC(y2, m2 - 1, d2);
  return Math.round((b - a) / 86_400_000) + 1;
}

export function previousPeriod(r: DateRange): DateRange {
  const days = rangeDays(r);
  return {
    start: addDaysISO(r.start, -days),
    end: addDaysISO(r.start, -1),
  };
}

export function detectFreshness(
  source: 'ga4' | 'gsc',
  range: DateRange,
  timeZone: string
): { freshness: DataFreshness; warnings: string[] } {
  const today = todayInPropertyTz(timeZone);
  if (source === 'gsc') {
    const cutoff = addDaysISO(today, -2);
    if (range.end >= cutoff) {
      return {
        freshness: 'partial',
        warnings: [`GSC data has a 2-3 day lag; results through ${range.end} are incomplete.`],
      };
    }
  }
  if (source === 'ga4' && range.end >= today) {
    return {
      freshness: 'partial',
      warnings: ['GA4 data for today is still being collected.'],
    };
  }
  return { freshness: 'complete', warnings: [] };
}
