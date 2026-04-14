import { describe, it, expect } from 'vitest';
import { computeTrend, pctDelta } from '../trend';

describe('computeTrend', () => {
  it('reports up for monotonically increasing series', () => {
    const t = computeTrend([1, 2, 3, 4, 5]);
    expect(t.trend_direction).toBe('up');
    expect(t.trend_strength).toBeGreaterThan(0);
  });

  it('reports down for monotonically decreasing series', () => {
    const t = computeTrend([5, 4, 3, 2, 1]);
    expect(t.trend_direction).toBe('down');
  });

  it('reports flat for noise around constant', () => {
    const t = computeTrend([10, 10, 10, 10, 10]);
    expect(t.trend_direction).toBe('flat');
    expect(t.trend_strength).toBe(0);
  });

  it('returns flat for empty or single-point series', () => {
    expect(computeTrend([]).trend_direction).toBe('flat');
    expect(computeTrend([42]).trend_direction).toBe('flat');
  });
});

describe('pctDelta', () => {
  it('returns positive percent for growth', () => {
    expect(pctDelta(120, 100)).toBeCloseTo(0.2);
  });
  it('returns 0 when previous is 0 and current is 0', () => {
    expect(pctDelta(0, 0)).toBe(0);
  });
  it('returns Infinity-safe value when previous is 0 and current is positive', () => {
    expect(pctDelta(5, 0)).toBe(1); // saturate at +100% to avoid Infinity
  });
});
