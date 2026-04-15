import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { resolveDateRange, previousPeriod, detectFreshness, rangeDays, todayInPropertyTz } from '../dates';

describe('resolveDateRange', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Phoenix is UTC-7, so 2026-04-14 12:00 UTC = 2026-04-14 05:00 Phoenix
    vi.setSystemTime(new Date('2026-04-14T12:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  it("resolves 'today' to a single-day range in property timezone", () => {
    const r = resolveDateRange('today', 'America/Phoenix');
    expect(r).toEqual({ start: '2026-04-14', end: '2026-04-14', preset: 'today' });
  });

  it("resolves 'last_7_days' as the 7 days ending today (inclusive)", () => {
    const r = resolveDateRange('last_7_days', 'America/Phoenix');
    expect(r).toEqual({ start: '2026-04-08', end: '2026-04-14', preset: 'last_7_days' });
  });

  it("resolves 'last_28_days' as the 28 days ending today (inclusive)", () => {
    const r = resolveDateRange('last_28_days', 'America/Phoenix');
    expect(r).toEqual({ start: '2026-03-18', end: '2026-04-14', preset: 'last_28_days' });
  });

  it("resolves 'mtd' from the 1st through today", () => {
    const r = resolveDateRange('mtd', 'America/Phoenix');
    expect(r).toEqual({ start: '2026-04-01', end: '2026-04-14', preset: 'mtd' });
  });

  it('passes through explicit ranges unchanged', () => {
    const r = resolveDateRange({ start: '2026-01-01', end: '2026-01-31' }, 'America/Phoenix');
    expect(r).toEqual({ start: '2026-01-01', end: '2026-01-31' });
  });
});

describe('previousPeriod', () => {
  it('returns the prior window of equal length immediately preceding', () => {
    expect(previousPeriod({ start: '2026-04-07', end: '2026-04-13' })).toEqual({
      start: '2026-03-31',
      end: '2026-04-06',
    });
  });

  it('returns the prior single day for a 1-day range', () => {
    expect(previousPeriod({ start: '2026-04-14', end: '2026-04-14' })).toEqual({
      start: '2026-04-13',
      end: '2026-04-13',
    });
  });

  it('crosses year boundaries correctly', () => {
    expect(previousPeriod({ start: '2026-01-01', end: '2026-01-07' })).toEqual({
      start: '2025-12-25',
      end: '2025-12-31',
    });
  });
});

describe('rangeDays', () => {
  it('counts days inclusively', () => {
    expect(rangeDays({ start: '2026-04-07', end: '2026-04-13' })).toBe(7);
    expect(rangeDays({ start: '2026-04-14', end: '2026-04-14' })).toBe(1);
  });
});

describe('detectFreshness', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-14T12:00:00Z'));
  });
  afterEach(() => vi.useRealTimers());

  it('flags GSC ranges within 2 days of today as partial', () => {
    const f = detectFreshness('gsc', { start: '2026-04-07', end: '2026-04-13' }, 'America/Phoenix');
    expect(f.freshness).toBe('partial');
    expect(f.warnings[0]).toContain('GSC data has a 2-3 day lag');
  });

  it('marks GA4 ranges ending today as partial', () => {
    const f = detectFreshness('ga4', { start: '2026-04-14', end: '2026-04-14' }, 'America/Phoenix');
    expect(f.freshness).toBe('partial');
  });

  it('marks complete when end date is well-aged', () => {
    const f = detectFreshness('gsc', { start: '2026-03-01', end: '2026-04-10' }, 'America/Phoenix');
    expect(f.freshness).toBe('complete');
    expect(f.warnings).toEqual([]);
  });
});

describe('todayInPropertyTz', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-14T01:30:00Z')); // 2026-04-13 18:30 Phoenix
  });
  afterEach(() => vi.useRealTimers());

  it('returns yesterday in UTC when Phoenix is still on the prior date', () => {
    expect(todayInPropertyTz('America/Phoenix')).toBe('2026-04-13');
  });
});
