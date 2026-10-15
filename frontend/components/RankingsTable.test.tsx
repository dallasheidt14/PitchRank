import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { makeRankingRow } from '@/test/fixtures';
import type { RankingRow } from '@/types/RankingRow';

const { mockUseRankings, mockTrackSortUsed } = vi.hoisted(() => ({
  mockUseRankings: vi.fn(),
  mockTrackSortUsed: vi.fn(),
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
  trackSortUsed: mockTrackSortUsed,
  trackTeamRowClicked: vi.fn(),
}));

// The divider states the engine's games threshold; 37 is a value no copy would hard-code in its place.
vi.mock('@/lib/constants', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/constants')>()),
  MIN_RANKED_GAMES: 37,
}));

import { RankingsTable } from './RankingsTable';
import { TooltipProvider } from '@/components/ui/tooltip';
import { markIfOpenedFromRankings } from '@/hooks/useRankingsViewState';

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
  mockTrackSortUsed.mockReset();
  vi.restoreAllMocks();
  vi.useRealTimers();
  window.history.replaceState(null, '');
  markIfOpenedFromRankings();
  setScrollY(0);
});

describe('RankingsTable', () => {
  it('shows the top 100 teams and how many there are', async () => {
    await renderTable(cohort(250));

    expect(rows()).toHaveLength(100);
    expect(caption()).toBe('Showing 100 of 250 teams · 250 ranked');
    expect(showMoreButton()!.textContent).toBe('Show 100 more');
  });

  it('adds 100 rows per Show more, moves focus to the first new row, and offers only what is left', async () => {
    await renderTable(cohort(250));

    await act(async () => showMoreButton()!.click());

    expect(rows()).toHaveLength(200);
    expect(caption()).toBe('Showing 200 of 250 teams · 250 ranked');
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
    expect(rows()[1].getAttribute('aria-label')).toContain(', Aardvark SC,');
    expect(rows()[1].getAttribute('aria-label')).not.toContain('unknown_4482913');
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

  describe('marking the team page a row opens', () => {
    it('lets the team page a row opens mark itself, so its Back to Rankings returns to this entry', async () => {
      await renderTable(cohort(10));
      const row = rows()[5];
      const boardUrl = window.location.pathname + window.location.search;

      await clickRowWithoutNavigating(row);
      window.history.replaceState({ __NA: true }, '', row.getAttribute('href'));
      try {
        markIfOpenedFromRankings();

        expect(window.history.state).toEqual({ __NA: true, __pitchrankFromRankings: true, __pitchrankTeamSeen: true });
      } finally {
        window.history.replaceState({ __NA: true }, '', boardUrl);
      }
    });

    it('notes nothing for a row tapped while a Back is loading another page under the board', async () => {
      await renderTable(cohort(10));
      const row = rows()[5];
      const boardUrl = window.location.pathname + window.location.search;

      window.history.replaceState({ __NA: true }, '', '/teams/earlier?region=national&ageGroup=u13&gender=male');
      try {
        await clickRowWithoutNavigating(row);
        window.history.replaceState({ __NA: true }, '', row.getAttribute('href'));
        markIfOpenedFromRankings();

        expect(window.history.state).toEqual({ __NA: true, __pitchrankTeamSeen: true });
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
      expect(caption()).toBe('Showing 300 of 400 teams · 400 ranked');
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

  describe('sorting by PowerScore', () => {
    // Lopsided on purpose: rank order, PowerScore high-to-low and PowerScore low-to-high are three different orders.
    const BOARD = [
      makeRankingRow({ team_id_master: 'team-a', team_name: 'Alpha', rank_in_cohort_final: 1, power_score_final: 0.5 }),
      makeRankingRow({ team_id_master: 'team-b', team_name: 'Bravo', rank_in_cohort_final: 2, power_score_final: 0.9 }),
      makeRankingRow({
        team_id_master: 'team-c',
        team_name: 'Charlie',
        rank_in_cohort_final: 3,
        power_score_final: 0.1,
      }),
    ];

    function powerScoreSortButton(): HTMLButtonElement {
      return container!.querySelector('[aria-label="Sort by PowerScore"]')!;
    }

    it('puts the strongest team first on the first tap, and saves and reports that direction', async () => {
      await renderTable(BOARD);
      expect(rows().map(rowName)).toEqual(['Alpha', 'Bravo', 'Charlie']);

      await act(async () => powerScoreSortButton().click());

      expect(rows().map(rowName)).toEqual(['Bravo', 'Alpha', 'Charlie']);
      expect(savedView()).toMatchObject({ sortField: 'powerScore', sortDirection: 'desc' });
      expect(mockTrackSortUsed).toHaveBeenCalledWith(
        expect.objectContaining({ column: 'powerScore', direction: 'desc' })
      );
    });

    it('flips to weakest first on the second tap', async () => {
      await renderTable(BOARD);

      await act(async () => powerScoreSortButton().click());
      await act(async () => powerScoreSortButton().click());

      expect(rows().map(rowName)).toEqual(['Charlie', 'Alpha', 'Bravo']);
      expect(savedView()).toMatchObject({ sortField: 'powerScore', sortDirection: 'asc' });
    });

    it('still starts every other column low to high', async () => {
      await renderTable(BOARD);

      await act(async () => (container!.querySelector('[aria-label="Sort by Team"]') as HTMLButtonElement).click());

      expect(rows().map(rowName)).toEqual(['Alpha', 'Bravo', 'Charlie']);
      expect(savedView()).toMatchObject({ sortField: 'team', sortDirection: 'asc' });
    });
  });

  describe('for screen readers', () => {
    it('reads each row as rank, movement, team, club, state and PowerScore', async () => {
      await renderTable([
        makeRankingRow({
          team_id_master: 'team-a',
          team_name: 'Phoenix United 2014 Elite',
          club_name: 'Phoenix United',
          state: 'AZ',
          rank_in_cohort_final: 3,
          rank_change_7d: 2,
          power_score_final: 0.5812,
        }),
        makeRankingRow({
          team_id_master: 'team-b',
          team_name: 'Tucson Rush 2014',
          club_name: 'Tucson Rush',
          state: 'AZ',
          rank_in_cohort_final: undefined,
          rank_change_7d: null,
          power_score_final: 0.2,
        }),
      ]);

      expect(rows()[0].getAttribute('aria-label')).toBe(
        'Rank 3, up 2 in the last 7 days, Phoenix United 2014 Elite, Phoenix United, AZ, PowerScore 58.12'
      );
      expect(rows()[1].getAttribute('aria-label')).toBe(
        'Not ranked yet, Tucson Rush 2014, Tucson Rush, AZ, PowerScore 20.00'
      );
    });

    it('reads a fall, and leaves out a missing club and state', async () => {
      await renderTable([
        makeRankingRow({
          team_id_master: 'team-a',
          team_name: 'Mesa FC 2014',
          club_name: null,
          state: null,
          rank_in_cohort_final: 5,
          rank_change_7d: -3,
          power_score_final: 0.41,
        }),
      ]);

      expect(rows()[0].getAttribute('aria-label')).toBe(
        'Rank 5, down 3 in the last 7 days, Mesa FC 2014, PowerScore 41.00'
      );
    });

    it('names every sort button after its column', async () => {
      await renderTable(cohort(2));

      expect(container!.querySelector('[aria-label="Sort by PowerScore"]')).not.toBeNull();
      expect(container!.querySelector('[aria-label="Sort by SOS Rank"]')).not.toBeNull();
      expect(container!.querySelector('[aria-label="Sort by Sort"]')).toBeNull();
    });
  });

  describe('teams without a rank yet', () => {
    const BOARD = [
      makeRankingRow({ team_id_master: 'team-a', team_name: 'Alpha', rank_in_cohort_final: 1, power_score_final: 0.6 }),
      makeRankingRow({ team_id_master: 'team-b', team_name: 'Bravo', rank_in_cohort_final: 2, power_score_final: 0.4 }),
      makeRankingRow({
        team_id_master: 'team-c',
        team_name: 'Charlie',
        rank_in_cohort_final: undefined,
        rank_change_7d: null,
        power_score_final: 0.5,
      }),
      makeRankingRow({
        team_id_master: 'team-d',
        team_name: 'Delta',
        rank_in_cohort_final: undefined,
        rank_change_7d: null,
        power_score_final: 0.1,
      }),
    ];

    function dividers(): Element[] {
      return Array.from(container!.querySelectorAll('[data-testid="rankings-unranked-divider"]'));
    }

    const before = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

    it('explains the unranked teams with one line between them and the ranked ones', async () => {
      await renderTable(BOARD);

      expect(dividers()).toHaveLength(1);
      expect(dividers()[0].textContent).toBe('Not ranked yet: fewer than 37 games in the last 12 months');
      expect(before(rows()[1], dividers()[0])).toBe(true);
      expect(before(dividers()[0], rows()[2])).toBe(true);
      expect(rows()[2].firstElementChild!.textContent).toBe('—');
      expect(caption()).toBe('Showing 4 of 4 teams · 2 ranked');
    });

    it('drops the line when another sort mixes ranked and unranked teams', async () => {
      await renderTable(BOARD);

      await act(async () =>
        (container!.querySelector('[aria-label="Sort by PowerScore"]') as HTMLButtonElement).click()
      );

      expect(rows().map(rowName)).toEqual(['Alpha', 'Charlie', 'Bravo', 'Delta']);
      expect(dividers()).toHaveLength(0);
    });

    it('drops the line when rank order is reversed and the unranked teams come first', async () => {
      await renderTable(BOARD);

      await act(async () => (container!.querySelector('[aria-label="Sort by Rank"]') as HTMLButtonElement).click());

      expect(rows().map(rowName)).toEqual(['Charlie', 'Delta', 'Bravo', 'Alpha']);
      expect(dividers()).toHaveLength(0);
    });

    it('heads the list with the line when no team has a rank yet', async () => {
      await renderTable(BOARD.slice(2));

      expect(dividers()).toHaveLength(1);
      expect(before(dividers()[0], rows()[0])).toBe(true);
      expect(caption()).toBe('Showing 2 of 2 teams · 0 ranked');
    });
  });

  // happy-dom applies no stylesheet, so these read the phone layout from the classes in force below sm
  // (unprefixed and `max-sm:`). They check which elements the classes show, not how the board renders.
  describe('on a phone', () => {
    function phoneClasses(el: Element): string[] {
      return el.className
        .split(/\s+/)
        .filter(Boolean)
        .flatMap((name) => (!name.includes(':') ? [name] : name.startsWith('max-sm:') ? [name.slice(7)] : []));
    }

    function shownOnPhone(el: Element): boolean {
      return !phoneClasses(el).includes('hidden');
    }

    /** Column count of a bracketed `grid-cols-[...]` class, e.g. `grid-cols-[56px_1fr_50px]` → 3. */
    function phoneColumnCount(grid: Element): number {
      const template = phoneClasses(grid).find((name) => name.startsWith('grid-cols-['))!;
      return template.slice('grid-cols-['.length, -1).split('_').length;
    }

    it('shows one cell per column in the header and in every row, so none wraps onto a second line', async () => {
      await renderTable(cohort(3));
      const header = container!.querySelector('[data-testid="rankings-table-header"]')!;

      for (const grid of [header, ...rows()]) {
        expect(phoneColumnCount(grid)).toBe(3);
        expect(Array.from(grid.children).filter(shownOnPhone)).toHaveLength(3);
      }
    });

    it('prompts a tap with View under the score, and leaves View Team to wider screens', async () => {
      await renderTable(cohort(3));

      for (const row of rows()) {
        const scoreCell = row.children[2];
        const prompt = scoreCell.lastElementChild!;
        expect(scoreCell.textContent).toBe('50.00View');
        expect(prompt.textContent).toBe('View');
        expect(prompt.querySelector('svg')).not.toBeNull();
        expect(shownOnPhone(prompt)).toBe(true);
        expect(prompt.className.split(/\s+/)).toContain('sm:hidden');

        const viewTeam = row.lastElementChild!;
        expect(viewTeam.textContent).toBe('View Team');
        expect(shownOnPhone(viewTeam)).toBe(false);
        expect(viewTeam.className.split(/\s+/)).toContain('sm:flex');
      }
    });

    it('shrinks the card header to the updated date and the PowerScore help, keeping the title for screen readers', async () => {
      await renderTable([makeRankingRow({ last_calculated: '2026-08-24T12:00:00Z' })]);
      const card = container!.querySelector('[data-testid="rankings-table-card"]')!;
      const title = container!.querySelector('[data-testid="rankings-title"]')!;
      const header = title.parentElement!;

      expect(title.textContent).toContain('Complete Rankings');
      expect(phoneClasses(title)).toContain('sr-only');
      expect(shownOnPhone(title)).toBe(true);

      const description = Array.from(header.children).find((child) => child.textContent?.includes('Age: U13'))!;
      expect(description.textContent).toContain('Age: U13 • Boys');
      expect(shownOnPhone(description)).toBe(false);

      const updated = Array.from(header.children).find((child) => child.textContent?.startsWith('Updated '))!;
      expect(updated.textContent).toBe('Updated Aug 24, 2026');
      expect(shownOnPhone(updated)).toBe(true);
      expect(updated.className.split(/\s+/)).toContain('sm:hidden');

      expect(Array.from(header.querySelectorAll('button')).some((b) => b.textContent === 'What is PowerScore?')).toBe(
        true
      );
      expect(phoneClasses(card)).toEqual(expect.arrayContaining(['pt-0', 'gap-3']));
    });

    it('shows no updated date when the board carries no calculation time', async () => {
      await renderTable([makeRankingRow({ last_calculated: null as unknown as string })]);
      const header = container!.querySelector('[data-testid="rankings-title"]')!.parentElement!;

      expect(header.textContent).not.toContain('Updated ');
    });
  });
});
