import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';

export const RANKINGS_PAGE_SIZE = 100;
export const RANKINGS_SORT_FIELDS = ['rank', 'team', 'powerScore', 'sosRank'] as const;
export type RankingsSortField = (typeof RANKINGS_SORT_FIELDS)[number];
export type SortDirection = 'asc' | 'desc';

const HISTORY_KEY = '__pitchrankRankingsView';
const MAX_SAVED_COUNT = 50_000;

export interface RankingsView {
  count: number;
  sortField: RankingsSortField;
  sortDirection: SortDirection;
}

export interface SavedRankingsView extends RankingsView {
  version: 1;
  /** `region|ageGroup|gender` */
  cohort: string;
  scrollY: number;
}

export function readSavedView(state: unknown, cohort: string): SavedRankingsView | null {
  const saved = (state as Record<string, unknown> | null)?.[HISTORY_KEY] as Partial<SavedRankingsView> | undefined;
  if (!saved || saved.version !== 1 || saved.cohort !== cohort) return null;
  const { count, sortField, sortDirection, scrollY } = saved;
  if (!Number.isInteger(count) || count! < RANKINGS_PAGE_SIZE || count! > MAX_SAVED_COUNT) return null;
  if (!RANKINGS_SORT_FIELDS.includes(sortField as RankingsSortField)) return null;
  if (sortDirection !== 'asc' && sortDirection !== 'desc') return null;
  if (typeof scrollY !== 'number' || !Number.isFinite(scrollY) || scrollY < 0) return null;
  return saved as SavedRankingsView;
}

/**
 * Stores the view on the current history entry, so Back/Forward restore it and a fresh visit
 * (a new entry) does not. Skipped for entries Next.js did not create: Back to an entry without
 * `__NA` makes the App Router hard-reload the page.
 */
export function writeSavedView(view: SavedRankingsView): void {
  const current = window.history.state as Record<string, unknown> | null;
  if (!current?.__NA) return;
  try {
    window.history.replaceState({ ...current, [HISTORY_KEY]: view }, '');
  } catch {
    // Safari throttles replaceState; the next scroll saves again.
  }
}

function currentUrl(): string {
  return window.location.pathname + window.location.search;
}

const INTERACTION_EVENTS = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const;

/**
 * Keeps the rankings list's expanded count, sort and scroll position on its history entry and
 * restores them on Back/Forward. Returns `persistView`, which saves now; pass any field the same
 * handler just set as an override, since the hook still holds the previous render's view.
 *
 * Count and sort are restored in a layout effect, so the list is full-height in the commit that
 * handles popstate. WebKit then restores the scroll itself; Chromium and Firefox did not in
 * testing, so a frame callback scrolls to the saved position, retrying as more rows render (a
 * reload shows the server seed before the rest of a large cohort arrives) until the position is
 * reached, every saved row has rendered, the address leaves the board, or the visitor touches,
 * clicks, wheels or presses a key.
 */
export function useRankingsViewState({
  cohort,
  view,
  searchActive,
  listTopScrollY,
  rowCount,
  onRestore,
}: {
  cohort: string;
  view: RankingsView;
  searchActive: boolean;
  /** Scroll position that puts the top of the list under the sticky header, if measurable. */
  listTopScrollY: () => number | null;
  rowCount: number;
  onRestore: (saved: SavedRankingsView) => void;
}) {
  const latestRef = useRef({ view, searchActive, listTopScrollY, onRestore });
  useLayoutEffect(() => {
    latestRef.current = { view, searchActive, listTopScrollY, onRestore };
  });

  // While Back is still loading the destination page, this board stays mounted under the
  // destination's URL and history entry; it must not write its view there.
  const ownUrlRef = useRef<string | null>(null);

  const persistView = useCallback(
    (overrides?: Partial<RankingsView>) => {
      if (currentUrl() !== ownUrlRef.current) return;
      const latest = latestRef.current;
      const scrollY = Math.round(window.scrollY);
      // A search is not restored, so keep one page and no position deeper than the list top.
      const listTop = latest.searchActive ? latest.listTopScrollY() : null;
      writeSavedView({
        ...latest.view,
        ...overrides,
        ...(latest.searchActive && { count: RANKINGS_PAGE_SIZE }),
        version: 1,
        cohort,
        scrollY: listTop === null ? scrollY : Math.min(scrollY, listTop),
      });
    },
    [cohort]
  );

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onScroll = () => {
      clearTimeout(timer);
      timer = setTimeout(() => persistView(), 150);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      clearTimeout(timer);
      window.removeEventListener('scroll', onScroll);
    };
  }, [persistView]);

  const restoreRef = useRef<{ scrollY: number; count: number; finish: () => void } | null>(null);

  useLayoutEffect(() => {
    ownUrlRef.current = currentUrl();
    const saved = readSavedView(window.history.state, cohort);
    if (!saved) return;
    const finish = () => {
      restoreRef.current = null;
      INTERACTION_EVENTS.forEach((event) => window.removeEventListener(event, finish));
    };
    restoreRef.current = { scrollY: saved.scrollY, count: saved.count, finish };
    INTERACTION_EVENTS.forEach((event) => window.addEventListener(event, finish, { passive: true }));
    latestRef.current.onRestore(saved);
    return finish;
  }, [cohort]);

  useLayoutEffect(() => {
    if (restoreRef.current === null || rowCount === 0) return;
    const frame = requestAnimationFrame(() => {
      const restore = restoreRef.current;
      if (restore === null) return;
      if (currentUrl() !== ownUrlRef.current) return restore.finish();
      if (Math.abs(window.scrollY - restore.scrollY) > 2) {
        window.scrollTo({ top: restore.scrollY, behavior: 'instant' });
      }
      // Once every saved row has rendered, only the visitor can add more, so stop even if the
      // page is still too short to reach the saved position.
      if (Math.abs(window.scrollY - restore.scrollY) <= 2 || rowCount >= restore.count) restore.finish();
    });
    return () => cancelAnimationFrame(frame);
  }, [rowCount]);

  return persistView;
}
