import { describe, it, expect } from 'vitest';
import { BUSINESS_TIMEZONE, startOfMonth, wallClockDate } from '../timezone';

describe('BUSINESS_TIMEZONE', () => {
  it('matches the property timezone the analytics queries report in', () => {
    // Hardcoded rather than imported so a change on either side is a visible
    // decision: the dashboards would otherwise silently disagree about "this
    // month" while both looked correct in isolation.
    expect(BUSINESS_TIMEZONE).toBe('America/Phoenix');
  });
});

describe('wallClockDate', () => {
  it('reads the local calendar day, not the UTC one', () => {
    // 00:33 UTC on Sept 6 — the instant the dashboard was reported showing the
    // 6th while it was still the evening of the 5th locally.
    expect(wallClockDate(new Date('2026-09-06T00:33:00Z'))).toEqual({ year: 2026, month: 9, day: 5 });
  });

  it('agrees with UTC once the local day has caught up', () => {
    expect(wallClockDate(new Date('2026-09-06T18:00:00Z'))).toEqual({ year: 2026, month: 9, day: 6 });
  });

  it('rolls the year back at the turn of January', () => {
    expect(wallClockDate(new Date('2027-01-01T05:00:00Z'))).toEqual({ year: 2026, month: 12, day: 31 });
  });
});

describe('startOfMonth', () => {
  it('starts the month at local midnight, seven hours after the UTC one', () => {
    expect(new Date(startOfMonth(2026, 9)).toISOString()).toBe('2026-09-01T07:00:00.000Z');
  });

  it('handles a month index that wraps into the next year', () => {
    expect(new Date(startOfMonth(2027, 1)).toISOString()).toBe('2027-01-01T07:00:00.000Z');
  });

  it('holds the offset across a month when other US zones would shift', () => {
    // Phoenix does not observe DST, so March and November open at the same
    // offset. This is the assertion that fails first if the constant moves to a
    // DST-observing zone without the refinement pass in startOfMonth.
    expect(new Date(startOfMonth(2026, 3)).toISOString()).toBe('2026-03-01T07:00:00.000Z');
    expect(new Date(startOfMonth(2026, 11)).toISOString()).toBe('2026-11-01T07:00:00.000Z');
  });

  it('names an instant whose own local date is the first of that month', () => {
    for (const month of [1, 2, 6, 9, 12]) {
      expect(wallClockDate(new Date(startOfMonth(2026, month)))).toEqual({ year: 2026, month, day: 1 });
    }
  });
});
