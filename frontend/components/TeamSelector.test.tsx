import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockUseTeamSearch } = vi.hoisted(() => ({
  mockUseTeamSearch: vi.fn(),
}));

vi.mock('@/hooks/useTeamSearch', () => ({
  useTeamSearch: mockUseTeamSearch,
}));

import { TeamSelector } from './TeamSelector';

// One club, three squads, no league and no distinction — the shape that collapses to a single
// identical label under composeTeamDisplay and is the reason teamDisplayName exists.
const copper = {
  team_id_master: 'team-copper',
  team_name: '2014/15G Copper',
  searchable_name: '2014/15G Copper Colorado United U13 14',
  club_name: 'Colorado United',
  league: null,
  distinction: null,
  has_modular11_alias: false,
  state: 'co',
  age: 13,
  gender: 'F',
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

const dash = {
  ...copper,
  team_id_master: 'team-dash',
  team_name: 'Colorado United - Dash',
  searchable_name: 'Colorado United - Dash Colorado United U13 14',
};

// A registered name whose own U-token contradicts the stored cohort — appending age would
// render "BUCKS BYRNES U15 U19".
const bucks = {
  ...copper,
  team_id_master: 'team-bucks',
  team_name: 'BUCKS BYRNES U15',
  searchable_name: 'BUCKS BYRNES U15 Bucks Soccer Club U19 08',
  club_name: 'Bucks Soccer Club',
  state: 'pa',
  age: 19,
  gender: 'M',
};

function renderSelector(props: { value?: string | null; onChange?: () => void } = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  return {
    container,
    root: createRoot(container),
    element: React.createElement(TeamSelector, {
      label: 'Team A',
      value: props.value ?? null,
      onChange: props.onChange ?? vi.fn(),
    }),
  };
}

async function flushRender(root: Root, element: React.ReactElement) {
  await act(async () => {
    root.render(element);
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

describe('TeamSelector rows', () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTeamSearch.mockReturnValue({
      data: [copper, dash, bucks],
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
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

  it('shows the registered name over a club/state/cohort line', async () => {
    const rendered = renderSelector();
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    await typeQuery(container, 'colorado united');

    // Rows sort by how early the query matches, so the squad whose registered name starts
    // with the club comes first.
    const rows = container.querySelectorAll('button[aria-label^="Select"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toBe('Colorado United - DashColorado United • CO • U13 Girls');
    expect(rows[1].textContent).toBe('2014/15G CopperColorado United • CO • U13 Girls');
  });

  it('carries the club into the accessible name', async () => {
    const rendered = renderSelector();
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    await typeQuery(container, 'colorado united');

    const rows = container.querySelectorAll('button[aria-label^="Select"]');
    expect(rows[1].getAttribute('aria-label')).toBe('Select 2014/15G Copper Colorado United • CO • U13 Girls');
  });

  // The query matches club_name, and the registered name shares no text with it, so without the
  // club on the row the result looks unrelated to what was typed.
  it('highlights the club when that is what the query matched', async () => {
    const rendered = renderSelector();
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    await typeQuery(container, 'colorado');

    const row = container.querySelector('button[aria-label^="Select"]');
    expect(row!.querySelector('mark')!.textContent).toBe('Colorado');
  });

  it('never appends the cohort age to a name that carries its own', async () => {
    const rendered = renderSelector();
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    await typeQuery(container, 'bucks');

    const row = container.querySelector('button[aria-label^="Select"]');
    expect(row!.textContent).toBe('BUCKS BYRNES U15Bucks Soccer Club • PA • U19 Boys');
  });

  // Nothing else on /compare shows a cohort, and many registered names span more than one age
  // group, so a bare name in the confirmation is ambiguous.
  it('keeps club and cohort visible after a team is selected', async () => {
    const rendered = renderSelector({ value: 'team-copper' });
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);

    expect(container.textContent).toContain('Selected:');
    expect(container.textContent).toContain('2014/15G Copper');
    expect(container.textContent).toContain('Colorado United • CO • U13 Girls');
  });
});
