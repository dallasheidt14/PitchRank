import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockUseTeamSearch } = vi.hoisted(() => ({
  mockUseTeamSearch: vi.fn(),
}));

vi.mock('@/hooks/useTeamSearch', () => ({
  useTeamSearch: mockUseTeamSearch,
}));

const { mockTrackSearchUsed } = vi.hoisted(() => ({
  mockTrackSearchUsed: vi.fn(),
}));

vi.mock('@/lib/events', () => ({
  trackSearchUsed: mockTrackSearchUsed,
  trackSearchResultClicked: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { GlobalSearch } from './GlobalSearch';

// useTeamSearch builds every row from the search route's teams, so rank_in_cohort_final is always 0.
const dynamosU10 = {
  team_id_master: 'team-u10',
  team_name: 'Dynamos SC - Dynamos SC 2017 SC',
  club_name: 'Dynamos SC',
  league: null,
  distinction: null,
  has_modular11_alias: false,
  state: 'az',
  age: 10,
  gender: 'M',
  rank_in_cohort_final: 0,
  power_score_final: 0,
  sos_norm: 0,
  offense_norm: null,
  defense_norm: null,
  games_played: 0,
  wins: 0,
  losses: 0,
  draws: 0,
  total_games_played: 0,
  total_wins: 0,
  total_losses: 0,
  total_draws: 0,
  win_percentage: null,
};

const dynamosU14 = {
  ...dynamosU10,
  team_id_master: 'team-u14',
  team_name: 'Dynamos SC 2013 SC',
  age: 14,
};

// No state: pins that a missing state leaves no leading separator behind in the subtitle.
const dynamosRanked = {
  ...dynamosU10,
  team_id_master: 'team-ranked',
  team_name: 'Dynamos SC 2012 SC',
  state: null,
  age: 15,
  rank_in_cohort_final: 7,
};

function renderGlobalSearch() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  return { container, root: createRoot(container) };
}

async function flushRender(root: Root) {
  await act(async () => {
    root.render(React.createElement(GlobalSearch));
    await Promise.resolve();
  });
}

// The Input is controlled, so set the value through the native setter React tracks
// and dispatch the 'input' event React maps onChange to.
async function typeQuery(container: HTMLElement, value: string) {
  const input = container.querySelector('input') as HTMLInputElement;
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setValue.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await Promise.resolve();
  });
}

describe('GlobalSearch result rows', () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTeamSearch.mockReturnValue({
      results: [dynamosU10, dynamosU14, dynamosRanked],
      match: 'exact',
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    const rendered = renderGlobalSearch();
    container = rendered.container;
    root = rendered.root;
  });

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }

    container?.remove();
    root = null;
    container = null;
  });

  it('renders the registered team name above a bulleted club/state/age/gender line', async () => {
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');

    const options = container!.querySelectorAll('[role="option"]');
    expect(options).toHaveLength(3);
    expect(options[0].textContent).toBe('Dynamos SC - Dynamos SC 2017 SCDynamos SC • AZ • U10 Boys');
    expect(options[1].textContent).toBe('Dynamos SC 2013 SCDynamos SC • AZ • U14 Boys');
    expect(options[2].textContent).toBe('Dynamos SC 2012 SCDynamos SC • U15 Boys');
  });

  it('announces the disambiguating metadata in the accessible name', async () => {
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');

    const options = container!.querySelectorAll('[role="option"]');
    expect(options[0].getAttribute('aria-label')).toBe(
      'Select Dynamos SC - Dynamos SC 2017 SC Dynamos SC • AZ • U10 Boys'
    );
    expect(options[1].getAttribute('aria-label')).toBe('Select Dynamos SC 2013 SC Dynamos SC • AZ • U14 Boys');
    expect(options[2].getAttribute('aria-label')).toBe('Select Dynamos SC 2012 SC Dynamos SC • U15 Boys');
  });

  // The query can match club_name alone, and then the registered name shares no text with it.
  // The club has to be on the row, and highlighted, or the result looks unrelated to what was
  // typed. textContent flattens the <mark> away, so the highlight needs its own assertion.
  it('shows and highlights the club when the query matched it rather than the team name', async () => {
    mockUseTeamSearch.mockReturnValue({
      match: 'exact',
      results: [
        {
          ...dynamosU10,
          team_name: '2014/15G Copper',
          club_name: 'Colorado United',
        },
      ],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    await flushRender(root!);
    await typeQuery(container!, 'colorado');

    const option = container!.querySelector('[role="option"]');
    expect(option!.textContent).toBe('2014/15G CopperColorado United • AZ • U10 Boys');
    expect(option!.querySelector('mark')!.textContent).toBe('Colorado');
  });

  it('passes the typed query and the nav limit to the hook', async () => {
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');

    expect(mockUseTeamSearch).toHaveBeenLastCalledWith('dynamos', { limit: 8 });
  });

  // The label sits outside the listbox: the keyboard scroll indexes the listbox's children
  // by the highlighted row.
  it.each(['similar', 'relaxed'])('labels %s results as close matches, outside the listbox', async (match) => {
    mockUseTeamSearch.mockReturnValue({
      results: [dynamosU10, dynamosU14],
      match,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    await flushRender(root!);
    await typeQuery(container!, 'dynamso');

    expect(container!.textContent).toContain('Showing close matches');
    const options = [...container!.querySelector('#global-search-results')!.children];
    expect(options.map((child) => child.getAttribute('role'))).toEqual(['option', 'option']);
  });

  it('keeps the dropdown shut for a single letter followed by a space', async () => {
    mockUseTeamSearch.mockReturnValue({
      results: [],
      match: 'exact',
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    await flushRender(root!);
    await typeQuery(container!, 'a ');
    await flushRender(root!);

    expect(container!.textContent).not.toContain('No teams found');
    expect(mockTrackSearchUsed).not.toHaveBeenCalled();
  });

  it('does not label exact results', async () => {
    mockUseTeamSearch.mockReturnValue({
      results: [dynamosU10],
      match: 'exact',
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');

    expect(container!.textContent).toContain('Dynamos SC');
    expect(container!.textContent).not.toContain('Showing close matches');
  });

  // The browser's clear button is hidden, so the X stands in for it and must keep the cursor
  // in the box the way the native one does.
  it('clears the search with the X and keeps the cursor in the box', async () => {
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');
    const input = container!.querySelector('input') as HTMLInputElement;

    await act(async () => {
      (container!.querySelector('button[aria-label="Clear search"]') as HTMLButtonElement).click();
    });

    expect(input.value).toBe('');
    expect(document.activeElement).toBe(input);
    expect(container!.querySelectorAll('[role="option"]')).toHaveLength(0);
  });

  it('clears the search on Escape while results are showing', async () => {
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');
    const input = container!.querySelector('input') as HTMLInputElement;
    expect(container!.querySelectorAll('[role="option"]').length).toBeGreaterThan(0);

    await act(async () => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });

    expect(input.value).toBe('');
    expect(container!.querySelectorAll('[role="option"]')).toHaveLength(0);
  });

  it('records nothing for a failed search, then records the retry that succeeds', async () => {
    const failed = {
      results: [],
      match: 'exact',
      isLoading: false,
      isError: true,
      error: new Error('Search failed (429)'),
      refetch: vi.fn(),
    };
    mockUseTeamSearch.mockReturnValue(failed);
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');
    await flushRender(root!);

    expect(mockTrackSearchUsed).not.toHaveBeenCalled();

    mockUseTeamSearch.mockReturnValue({ ...failed, results: [dynamosU10], isError: false, error: null });
    await flushRender(root!);

    expect(mockTrackSearchUsed).toHaveBeenCalledTimes(1);
    expect(mockTrackSearchUsed).toHaveBeenCalledWith({ query: 'dynamos', results_count: 1 });
  });

  // The fetch is asynchronous, so the event must wait for the query's own results:
  // recording on the keystroke would send the previous query's count.
  it('records a search once, after its results arrive, with their count', async () => {
    const loading = {
      results: [],
      match: 'exact',
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
    mockUseTeamSearch.mockReturnValue(loading);
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');

    expect(mockTrackSearchUsed).not.toHaveBeenCalled();

    mockUseTeamSearch.mockReturnValue({
      ...loading,
      results: [dynamosU10, dynamosU14],
      isLoading: false,
    });
    await flushRender(root!);
    await flushRender(root!);

    expect(mockTrackSearchUsed).toHaveBeenCalledTimes(1);
    expect(mockTrackSearchUsed).toHaveBeenCalledWith({ query: 'dynamos', results_count: 2 });
  });

  it('records a search that finds nothing once it has finished', async () => {
    const loading = {
      results: [],
      match: 'exact',
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    };
    mockUseTeamSearch.mockReturnValue(loading);
    await flushRender(root!);
    await typeQuery(container!, 'zzzz');

    mockUseTeamSearch.mockReturnValue({ ...loading, isLoading: false });
    await flushRender(root!);
    await flushRender(root!);

    expect(mockTrackSearchUsed).toHaveBeenCalledTimes(1);
    expect(mockTrackSearchUsed).toHaveBeenCalledWith({ query: 'zzzz', results_count: 0 });
  });
});
