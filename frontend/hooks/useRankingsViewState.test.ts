import { afterEach, describe, expect, it } from 'vitest';
import { readSavedView, writeSavedView, type SavedRankingsView } from './useRankingsViewState';

const COHORT = 'national|u13|M';

function view(overrides: Partial<SavedRankingsView> = {}): SavedRankingsView {
  return {
    version: 1,
    cohort: COHORT,
    count: 300,
    sortField: 'team',
    sortDirection: 'desc',
    scrollY: 1234,
    ...overrides,
  };
}

afterEach(() => {
  window.history.replaceState(null, '');
});

describe('writeSavedView / readSavedView', () => {
  it('round-trips a view through the history entry and keeps Next.js state beside it', () => {
    window.history.replaceState({ __NA: true, other: 'kept' }, '');

    writeSavedView(view());

    expect(window.history.state.__NA).toBe(true);
    expect(window.history.state.other).toBe('kept');
    expect(readSavedView(window.history.state, COHORT)).toEqual({
      version: 1,
      cohort: 'national|u13|M',
      count: 300,
      sortField: 'team',
      sortDirection: 'desc',
      scrollY: 1234,
    });
  });

  it('does not write to an entry Next.js did not create', () => {
    window.history.replaceState({ other: 'kept' }, '');

    writeSavedView(view());

    expect(window.history.state).toEqual({ other: 'kept' });
  });

  it('ignores a view saved for another cohort', () => {
    expect(readSavedView({ __pitchrankRankingsView: view() }, 'az|u13|M')).toBeNull();
  });

  it.each([
    ['an unknown version', { version: 2 }],
    ['a count below one page', { count: 99 }],
    ['a count above the cap', { count: 50_001 }],
    ['a fractional count', { count: 150.5 }],
    ['a sort field with no sort', { sortField: 'gamesPlayed' }],
    ['an unknown direction', { sortDirection: 'up' }],
    ['a negative scroll position', { scrollY: -1 }],
    ['a non-numeric scroll position', { scrollY: '12' }],
  ])('rejects %s', (_label, overrides) => {
    const state = { __pitchrankRankingsView: { ...view(), ...overrides } };
    expect(readSavedView(state, COHORT)).toBeNull();
  });

  it('accepts the default view: one page, rank ascending, at the top', () => {
    const saved = view({ count: 100, sortField: 'rank', sortDirection: 'asc', scrollY: 0 });
    expect(readSavedView({ __pitchrankRankingsView: saved }, COHORT)).toEqual(saved);
  });

  it('returns null for an entry with no saved view', () => {
    expect(readSavedView(null, COHORT)).toBeNull();
    expect(readSavedView({ __NA: true }, COHORT)).toBeNull();
  });
});
