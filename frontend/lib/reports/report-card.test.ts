import { describe, it, expect } from 'vitest';
import { formatRankMovement, formatRecentRecord, topPercent } from './report-card';

describe('topPercent', () => {
  it('puts a team near the top of a large cohort in the top 1%', () => {
    expect(topPercent(20, 5578)).toBe(1);
  });

  it('rounds up, so a team is never placed above its rank', () => {
    // 60 of 5,578 is 1.08%: rounding to nearest would claim the top 1%.
    expect(topPercent(60, 5578)).toBe(2);
  });

  it('keeps an exact percent exact', () => {
    expect(topPercent(7, 100)).toBe(7);
  });

  it('puts the last team in the top 100%', () => {
    expect(topPercent(5578, 5578)).toBe(100);
  });
});

describe('formatRankMovement', () => {
  it('reads a positive change as a climb', () => {
    expect(formatRankMovement(293)).toBe('Up 293 spots in the last 30 days');
  });

  it('reads a negative change as a drop', () => {
    expect(formatRankMovement(-5)).toBe('Down 5 spots in the last 30 days');
  });

  it('uses the singular for one spot', () => {
    expect(formatRankMovement(1)).toBe('Up 1 spot in the last 30 days');
  });

  it('says nothing when the rank did not move or is unknown', () => {
    expect(formatRankMovement(0)).toBeNull();
    expect(formatRankMovement(null)).toBeNull();
  });
});

describe('formatRecentRecord', () => {
  it('formats the ranked-games record, not the all-time one', () => {
    expect(formatRecentRecord({ wins: 25, losses: 4, draws: 1 })).toBe('25-4-1');
  });

  it('treats missing fields as 0', () => {
    expect(formatRecentRecord({})).toBe('0-0-0');
  });
});
