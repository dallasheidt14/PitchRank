import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { makeRankingRow } from '@/test/fixtures';
import type { RankingRow } from '@/types/RankingRow';

const { mockUseRankings } = vi.hoisted(() => ({
  mockUseRankings: vi.fn(),
}));

vi.mock('@/hooks/useRankings', () => ({
  useRankings: mockUseRankings,
}));

vi.mock('@/lib/hooks', () => {
  const prefetch = vi.fn();
  return { usePrefetchTeam: () => prefetch };
});

vi.mock('@/lib/events', () => ({
  trackRankingsViewed: vi.fn(),
  trackSortUsed: vi.fn(),
  trackTeamRowClicked: vi.fn(),
}));

import { RankingsTable } from './RankingsTable';
import { TooltipProvider } from '@/components/ui/tooltip';

const COHORT = 'national|u13|M';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function cohort(size: number): RankingRow[] {
  return Array.from({ length: size }, (_, i) =>
    makeRankingRow({
      team_id_master: `team-${i}`,
      team_name: `Test FC ${i}`,
      rank_in_cohort_final: i + 1,
    })
  );
}

function setRankings(rows: RankingRow[]) {
  mockUseRankings.mockReturnValue({
    data: rows,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });
}

function tableElement(gender: 'M' | 'F') {
  return React.createElement(
    TooltipProvider,
    null,
    React.createElement(RankingsTable, { region: null, ageGroup: 'u13', gender })
  );
}

async function renderTable(rows: RankingRow[], gender: 'M' | 'F' = 'M') {
  setRankings(rows);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(tableElement(gender)));
}

async function rerenderWith(rows: RankingRow[]) {
  setRankings(rows);
  await act(async () => root!.render(tableElement('M')));
}

function rows(): HTMLAnchorElement[] {
  return Array.from(container!.querySelectorAll('[data-testid^="rankings-row-"]'));
}

function rowName(row: Element): string {
  return row.children[1].querySelector('span')!.textContent!;
}

function caption(): string {
  return container!.querySelector('[data-testid="rankings-showing-count"]')!.textContent!.replace(/\s+/g, ' ');
}

function showMoreButton(): HTMLButtonElement | null {
  return container!.querySelector('[data-testid="rankings-show-more"]');
}

function savedView() {
  return window.history.state?.__pitchrankRankingsView;
}

function setScrollY(y: number) {
  Object.defineProperty(window, 'scrollY', { value: y, configurable: true, writable: true });
}

/** How far the page can scroll, as a browser clamps a scroll past the end of a short page. */
let maxScrollY = Infinity;

/** Holds requestAnimationFrame callbacks until the test runs them. */
function holdFrames() {
  const frames: FrameRequestCallback[] = [];
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation((id) => {
    delete frames[id - 1];
  });
  return () => act(() => frames.splice(0).forEach((frame) => frame?.(0)));
}

/** Places the table box `boxDocumentTop` px down the page and the sticky header line at 117px. */
function stubLayout(boxDocumentTop: number) {
  const sticky = container!.querySelector('[data-testid="rankings-table-header"]')!.parentElement!;
  const box = container!.querySelector('.rankings-body')!.parentElement!;
  box.getBoundingClientRect = () => ({ top: boxDocumentTop - window.scrollY }) as DOMRect;
  const realGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((el) =>
    el === sticky ? ({ top: '117px' } as CSSStyleDeclaration) : realGetComputedStyle(el)
  );
}

async function typeSearch(query: string) {
  const input = container!.querySelector('input[type="search"]') as HTMLInputElement;
  const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setValue.call(input, query);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

async function clickRowWithoutNavigating(row: HTMLAnchorElement) {
  row.addEventListener('click', (event) => event.preventDefault());
  await act(async () => row.click());
}

beforeEach(() => {
  window.history.replaceState({ __NA: true }, '');
  setScrollY(0);
  maxScrollY = Infinity;
  vi.spyOn(window, 'scrollTo').mockImplementation(((options: ScrollToOptions) =>
    setScrollY(Math.min(options.top ?? 0, maxScrollY))) as typeof window.scrollTo);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  mockUseRankings.mockReset();
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.history.replaceState(null, '');
  setScrollY(0);
});

describe('RankingsTable', () => {
  it('shows the top 100 teams and how many there are', async () => {
    await renderTable(cohort(250));

    expect(rows()).toHaveLength(100);
    expect(caption()).toBe('Showing 100 of 250 teams');
    expect(showMoreButton()!.textContent).toBe('Show 100 more');
  });

  it('adds 100 rows per Show more, moves focus to the first new row, and offers only what is left', async () => {
    await renderTable(cohort(250));

    await act(async () => showMoreButton()!.click());

    expect(rows()).toHaveLength(200);
    expect(caption()).toBe('Showing 200 of 250 teams');
    expect(showMoreButton()!.textContent).toBe('Show 50 more');
    expect(document.activeElement?.getAttribute('data-testid')).toBe('rankings-row-100');

    await act(async () => showMoreButton()!.click());

    expect(rows()).toHaveLength(250);
    expect(showMoreButton()).toBeNull();
  });

  it('goes back to 100 rows when the search changes', async () => {
    await renderTable(cohort(250));
    await act(async () => showMoreButton()!.click());
    expect(rows()).toHaveLength(200);

    await typeSearch('test fc');

    expect(rows()).toHaveLength(100);
    expect(caption()).toBe('Showing 100 of 250 matches');
  });

  it('links a girls row to the girls board', async () => {
    await renderTable(cohort(1), 'F');

    expect(rows()[0].getAttribute('href')).toBe('/teams/team-0?region=national&ageGroup=u13&gender=female');
  });

  it('prints the 7-day movement number in the rank cell', async () => {
    await renderTable([makeRankingRow({ rank_in_cohort_final: 12, rank_change_7d: -7 })]);

    const rankCell = rows()[0].firstElementChild!;
    expect(rankCell.textContent).toBe('#127');
    expect(rankCell.querySelector('span span')!.className).not.toContain('hidden');
  });

  it('shows, labels, sorts and publishes a team by its display name, not a placeholder name', async () => {
    const placeholder = makeRankingRow({
      team_id_master: 'team-a',
      team_name: 'unknown_4482913',
      club_name: 'Aardvark SC',
      rank_in_cohort_final: 2,
    });
    const registered = makeRankingRow({
      team_id_master: 'team-b',
      team_name: 'Bravo 2014',
      club_name: 'Bravo FC',
      rank_in_cohort_final: 1,
    });
    await renderTable([registered, placeholder]);

    expect(rowName(rows()[1])).toBe('Aardvark SC');
    expect(rows()[1].getAttribute('aria-label')).toBe('View Aardvark SC team details');
    const schema = Array.from(container!.querySelectorAll('script[type="application/ld+json"]'))
      .map((script) => script.textContent)
      .join('');
    expect(schema).toContain('"Aardvark SC"');
    expect(schema).not.toContain('unknown_4482913');

    await act(async () => (container!.querySelector('[aria-label="Sort by Team"]') as HTMLButtonElement).click());

    expect(rows().map(rowName)).toEqual(['Aardvark SC', 'Bravo 2014']);
  });

  it('publishes a girls board as girls in its structured data', async () => {
    await renderTable(cohort(3), 'F');

    const schema = Array.from(container!.querySelectorAll('script[type="application/ld+json"]'))
      .map((script) => script.textContent)
      .join('');
    expect(schema).toContain('/u13/female');
    expect(schema).toContain('Girls');
  });

  describe('saving the view on the history entry', () => {
    it('saves the count after Show more', async () => {
      await renderTable(cohort(250));

      await act(async () => showMoreButton()!.click());

      expect(savedView()).toEqual({
        version: 1,
        cohort: COHORT,
        count: 200,
        sortField: 'rank',
        sortDirection: 'asc',
        scrollY: 0,
      });
    });

    it('saves the new sort when a column is sorted', async () => {
      await renderTable(cohort(10));

      await act(async () => (container!.querySelector('[aria-label="Sort by Team"]') as HTMLButtonElement).click());

      expect(savedView()).toMatchObject({ sortField: 'team', sortDirection: 'asc' });
    });

    it('saves the scroll position when a row is opened', async () => {
      await renderTable(cohort(10));
      setScrollY(777);

      await clickRowWithoutNavigating(rows()[3]);

      expect(savedView()).toMatchObject({ count: 100, scrollY: 777 });
    });

    it('saves the scroll position once, 150ms after the last scroll event', async () => {
      await renderTable(cohort(10));
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const replaceState = vi.spyOn(window.history, 'replaceState');

      setScrollY(500);
      window.dispatchEvent(new Event('scroll'));
      vi.advanceTimersByTime(100);
      setScrollY(1500);
      window.dispatchEvent(new Event('scroll'));
      vi.advanceTimersByTime(149);
      expect(replaceState).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);

      expect(replaceState).toHaveBeenCalledTimes(1);
      expect(savedView()).toMatchObject({ scrollY: 1500 });
    });

    it('saves one page and no deeper than the list top while a search is active', async () => {
      await renderTable(cohort(250));
      stubLayout(600);
      setScrollY(1000);
      await typeSearch('test fc');
      setScrollY(1000);
      await act(async () => showMoreButton()!.click());

      // list top = box document top - sticky line = 600 - 117
      expect(savedView()).toMatchObject({ count: 100, scrollY: 483 });
    });

    it('keeps the real position during a search when the list top is further down', async () => {
      await renderTable(cohort(250));
      stubLayout(1300);
      setScrollY(1000);
      await typeSearch('test fc');
      await act(async () => showMoreButton()!.click());

      expect(savedView()).toMatchObject({ count: 100, scrollY: 1000 });
    });

    it('does not write once the address is no longer the board it belongs to', async () => {
      await renderTable(cohort(250));
      const boardUrl = window.location.pathname + window.location.search;
      window.history.replaceState({ __NA: true }, '', '/upgrade');
      try {
        await rerenderWith(cohort(250));
        await act(async () => showMoreButton()!.click());

        expect(savedView()).toBeUndefined();
      } finally {
        window.history.replaceState({ __NA: true }, '', boardUrl);
      }
    });
  });

  describe('restoring the view on Back', () => {
    function saveView(cohort = COHORT) {
      window.history.replaceState(
        {
          __NA: true,
          __pitchrankRankingsView: {
            version: 1,
            cohort,
            count: 300,
            sortField: 'team',
            sortDirection: 'desc',
            scrollY: 5000,
          },
        },
        ''
      );
    }

    it('restores the count and sort, then scrolls to the saved position', async () => {
      saveView();
      const runFrames = holdFrames();

      await renderTable(cohort(400));

      expect(rows()).toHaveLength(300);
      expect(caption()).toBe('Showing 300 of 400 teams');
      expect(rowName(rows()[0])).toBe('Test FC 99');
      runFrames();
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 5000, behavior: 'instant' });
    });

    it.each(['wheel', 'touchstart', 'keydown', 'pointerdown'])(
      'does not scroll once the visitor has acted (%s)',
      async (event) => {
        saveView();
        const runFrames = holdFrames();
        await renderTable(cohort(400));

        window.dispatchEvent(new Event(event));
        runFrames();

        expect(window.scrollTo).not.toHaveBeenCalled();
      }
    );

    it('tries again when more rows arrive, until the position is reached', async () => {
      saveView();
      maxScrollY = 3000;
      const runFrames = holdFrames();
      await renderTable(cohort(150));
      runFrames();
      expect(window.scrollY).toBe(3000);

      maxScrollY = Infinity;
      await rerenderWith(cohort(400));
      runFrames();

      expect(rows()).toHaveLength(300);
      expect(window.scrollY).toBe(5000);
      expect(window.scrollTo).toHaveBeenCalledTimes(2);
    });

    it('stops once the position is reached', async () => {
      saveView();
      const runFrames = holdFrames();
      await renderTable(cohort(150));
      runFrames();
      expect(window.scrollY).toBe(5000);

      setScrollY(100);
      await rerenderWith(cohort(400));
      runFrames();

      expect(window.scrollTo).toHaveBeenCalledTimes(1);
    });

    it('stops once every saved row has rendered, even if the page is too short', async () => {
      saveView();
      maxScrollY = 3000;
      const runFrames = holdFrames();
      await renderTable(cohort(400));
      runFrames();
      expect(window.scrollTo).toHaveBeenCalledTimes(1);

      await act(async () => showMoreButton()!.click());
      runFrames();

      expect(rows()).toHaveLength(400);
      expect(window.scrollTo).toHaveBeenCalledTimes(1);
    });

    it('does not scroll once the address has moved on to another page', async () => {
      saveView();
      const runFrames = holdFrames();
      await renderTable(cohort(150));
      const boardUrl = window.location.pathname + window.location.search;
      window.history.replaceState(window.history.state, '', '/upgrade');
      try {
        runFrames();

        expect(window.scrollTo).not.toHaveBeenCalled();
      } finally {
        window.history.replaceState(window.history.state, '', boardUrl);
      }
    });

    it('ignores a view saved for another board', async () => {
      saveView('az|u13|M');
      const runFrames = holdFrames();

      await renderTable(cohort(400));
      runFrames();

      expect(rows()).toHaveLength(100);
      expect(window.scrollTo).not.toHaveBeenCalled();
    });
  });

  describe('keeping the search bar in view', () => {
    it('scrolls the list top up to the sticky line when the bar is stuck', async () => {
      await renderTable(cohort(250));
      stubLayout(600);
      setScrollY(1000);

      await typeSearch('test');

      expect(window.scrollTo).toHaveBeenCalledWith({ top: 483, behavior: 'instant' });
    });

    it('does the same when the table is re-sorted', async () => {
      await renderTable(cohort(250));
      stubLayout(600);
      setScrollY(1000);

      await act(async () => (container!.querySelector('[aria-label="Sort by Team"]') as HTMLButtonElement).click());

      expect(window.scrollTo).toHaveBeenCalledWith({ top: 483, behavior: 'instant' });
    });

    it('leaves the page alone when the list is still below the sticky line', async () => {
      await renderTable(cohort(250));
      stubLayout(1300);
      setScrollY(1000);

      await typeSearch('test');

      expect(window.scrollTo).not.toHaveBeenCalled();
    });
  });
});
