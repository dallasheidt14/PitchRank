import { describe, expect, it } from 'vitest';
import { classifyTrajectoryTrend } from './TeamTrajectoryChart';

const p = (goalDifferential: number, gamesPlayed = 5) => ({ goalDifferential, gamesPlayed });

describe('classifyTrajectoryTrend', () => {
  it('returns neutral when no periods have enough games', () => {
    expect(classifyTrajectoryTrend([p(3, 1), p(-3, 2)])).toBe('neutral');
  });

  it('returns neutral when only one reliable period exists', () => {
    expect(classifyTrajectoryTrend([p(3, 2), p(2, 4)])).toBe('neutral');
  });

  it('returns up when the second half is clearly higher than the first half', () => {
    expect(classifyTrajectoryTrend([p(-1), p(-1), p(2), p(2)])).toBe('up');
  });

  it('returns down when the second half is clearly lower than the first half', () => {
    expect(classifyTrajectoryTrend([p(3), p(3), p(0), p(0)])).toBe('down');
  });

  it('returns neutral when the swing is inside the threshold', () => {
    expect(classifyTrajectoryTrend([p(1.0), p(1.0), p(1.4), p(1.4)])).toBe('neutral');
  });

  it('drops the middle period on odd counts so halves stay balanced', () => {
    // Without dropping the middle: firstHalf=[3], secondHalf=[-5,1,1] → avg -1 vs 3 → down
    // With dropping the middle (index 2 = -5): paired=[3,3,1,1] → avg 1 vs 3 → down (consistent)
    // Pick a case where the middle would flip the verdict:
    // [3, 3, -10, 3, 3] — with middle dropped: [3,3,3,3] → 0 diff → neutral.
    expect(classifyTrajectoryTrend([p(3), p(3), p(-10), p(3), p(3)])).toBe('neutral');
  });

  it('ignores low-game periods when computing halves', () => {
    // Fifth period is a single blowout loss that used to tank the trend.
    const periods = [p(2, 6), p(2, 6), p(2, 6), p(2, 6), p(-10, 1)];
    expect(classifyTrajectoryTrend(periods)).toBe('neutral');
  });
});
