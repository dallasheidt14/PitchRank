import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockUseTeamSearch } = vi.hoisted(() => ({
  mockUseTeamSearch: vi.fn(),
}));

vi.mock('@/hooks/useTeamSearch', () => ({
  useTeamSearch: mockUseTeamSearch,
}));

vi.mock('@/lib/events', () => ({
  trackSearchUsed: vi.fn(),
  trackSearchResultClicked: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { GlobalSearch } from './GlobalSearch';

// useTeamSearch builds every row from the raw teams table, so rank_in_cohort_final is
// always 0. The fixtures keep that 0: a `{rank && ...}` guard renders it as a literal
// "0" in the subtitle.
const dynamosU10 = {
  team_id_master: 'team-u10',
  team_name: 'Dynamos SC - Dynamos SC 2017 SC',
  searchable_name: 'Dynamos SC - Dynamos SC 2017 SC Dynamos SC U10 17',
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
  searchable_name: 'Dynamos SC 2013 SC Dynamos SC U14 13',
  age: 14,
};

// A truthy rank with no state: pins that rank stays out of the subtitle even when it
// would render, and that a missing state leaves no leading separator behind.
const dynamosRanked = {
  ...dynamosU10,
  team_id_master: 'team-ranked',
  team_name: 'Dynamos SC 2012 SC',
  searchable_name: 'Dynamos SC 2012 SC Dynamos SC U15 12',
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
      data: [dynamosU10, dynamosU14, dynamosRanked],
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

  it('renders the club name with its age group above a bulleted state/age/gender line', async () => {
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');

    const options = container!.querySelectorAll('[role="option"]');
    expect(options).toHaveLength(3);
    expect(options[0].textContent).toBe('Dynamos SC U10AZ • U10 Boys');
    expect(options[1].textContent).toBe('Dynamos SC U14AZ • U14 Boys');
    expect(options[2].textContent).toBe('Dynamos SC U15U15 Boys');
  });

  it('announces the disambiguating metadata in the accessible name', async () => {
    await flushRender(root!);
    await typeQuery(container!, 'dynamos');

    const options = container!.querySelectorAll('[role="option"]');
    expect(options[0].getAttribute('aria-label')).toBe('Select Dynamos SC U10 AZ • U10 Boys');
    expect(options[1].getAttribute('aria-label')).toBe('Select Dynamos SC U14 AZ • U14 Boys');
    expect(options[2].getAttribute('aria-label')).toBe('Select Dynamos SC U15 U15 Boys');
  });
});
