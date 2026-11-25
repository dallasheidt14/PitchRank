import { describe, expect, it } from 'vitest';
import { hasPremiumPlan } from './plan';

describe('hasPremiumPlan', () => {
  it.each([
    ['premium', true],
    ['admin', true],
    ['free', false],
    [null, false],
    [undefined, false],
    ['', false],
  ])('reads %s as %s', (plan, expected) => {
    expect(hasPremiumPlan(plan)).toBe(expected);
  });
});
