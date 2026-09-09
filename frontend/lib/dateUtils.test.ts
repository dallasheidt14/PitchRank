import { describe, expect, it } from 'vitest';
import { formatShortDate } from './dateUtils';

describe('formatShortDate', () => {
  it('carries the year so the same day in two seasons reads differently', () => {
    expect(formatShortDate('2025-10-18')).toBe('Oct 18, 25');
    expect(formatShortDate('2026-10-18')).toBe('Oct 18, 26');
  });

  it('renders an em dash for an unparseable date', () => {
    expect(formatShortDate('not-a-date')).toBe('—');
  });
});
