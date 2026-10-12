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
import type { RankingRow } from '@/types/RankingRow';

// One club, three squads, no league and no distinction — the shape that collapses to a single
// identical label under composeTeamDisplay and is the reason teamDisplayName exists.
const copper: RankingRow = {
  team_id_master: 'team-copper',
  team_name: '2014/15G Copper',
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

const dash: RankingRow = {
  ...copper,
  team_id_master: 'team-dash',
  team_name: 'Colorado United - Dash',
};

// A registered name whose own U-token contradicts the stored cohort — appending age would
// render "BUCKS BYRNES U15 U19".
const bucks: RankingRow = {
  ...copper,
  team_id_master: 'team-bucks',
  team_name: 'BUCKS BYRNES U15',
  club_name: 'Bucks Soccer Club',
  state: 'pa',
  age: 19,
  gender: 'M',
};

// What the search route returns for each query, in its order.
const SERVER_RESULTS: Record<string, RankingRow[]> = {
  'colorado united': [dash, copper],
  colorado: [copper, dash],
  bucks: [bucks],
};

type SelectorProps = {
  value?: string | null;
  selectedTeam?: RankingRow | null;
  onChange?: () => void;
  excludeTeamId?: string;
};

function selectorElement(props: SelectorProps = {}) {
  return React.createElement(TeamSelector, {
    label: 'Team A',
    value: props.value ?? null,
    selectedTeam: props.selectedTeam ?? null,
    onChange: props.onChange ?? vi.fn(),
    excludeTeamId: props.excludeTeamId,
  });
}

function renderSelector(props: SelectorProps = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  return {
    container,
    root: createRoot(container),
    element: selectorElement(props),
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
    mockUseTeamSearch.mockImplementation((query: string) => ({
      results: SERVER_RESULTS[query.trim()] ?? [],
      match: 'exact',
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    }));
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

    // Rows render in the order the search route returns them.
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
    const rendered = renderSelector({ value: 'team-copper', selectedTeam: copper });
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);

    expect(container.textContent).toContain('Selected:');
    expect(container.textContent).toContain('2014/15G Copper');
    expect(container.textContent).toContain('Colorado United • CO • U13 Girls');
  });

  it('asks the hook for ten results without the other selected team', async () => {
    const rendered = renderSelector({ excludeTeamId: 'team-dash' });
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);

    expect(mockUseTeamSearch).toHaveBeenLastCalledWith('', { limit: 10, excludeId: 'team-dash' });
  });

  it.each([
    ['exact', false],
    ['similar', true],
    ['relaxed', true],
  ])('labels %s results as close matches: %s', async (match, labelled) => {
    mockUseTeamSearch.mockImplementation((query: string) => ({
      results: SERVER_RESULTS[query.trim()] ?? [],
      match,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    }));
    const rendered = renderSelector();
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    await typeQuery(container, 'bucks');

    expect(container.textContent).toContain('BUCKS BYRNES U15');
    expect(container.textContent?.includes('Showing close matches')).toBe(labelled);
  });

  it('scrolls the row the arrow keys highlight into view', async () => {
    const scrolled: Element[] = [];
    const original = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = function (this: HTMLElement) {
      scrolled.push(this);
    };
    try {
      mockUseTeamSearch.mockImplementation((query: string) => ({
        results: SERVER_RESULTS[query.trim()] ?? [],
        match: 'similar',
        isLoading: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      }));
      const rendered = renderSelector();
      ({ root, container } = rendered);
      await flushRender(root, rendered.element);
      await typeQuery(container, 'colorado');
      const input = container.querySelector('input') as HTMLInputElement;
      await act(async () => {
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
      });

      expect(scrolled.at(-1)?.tagName).toBe('BUTTON');
      expect(scrolled.at(-1)?.textContent).toContain('Dash');
    } finally {
      HTMLElement.prototype.scrollIntoView = original;
    }
  });

  it('keeps the dropdown shut for a single letter followed by a space', async () => {
    const rendered = renderSelector();
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    await typeQuery(container, 'a ');

    expect(container.textContent).not.toContain('No teams found');
  });

  // The parent owns the selected rows and exchanges them on Swap without calling onChange,
  // so the confirmation has to follow the props rather than a copy taken at selection.
  it('shows the swapped-in team after the parent exchanges value and row', async () => {
    const rendered = renderSelector({ value: 'team-copper', selectedTeam: copper });
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    expect(container.textContent).toContain('Selected: 2014/15G Copper');

    await flushRender(root, selectorElement({ value: 'team-dash', selectedTeam: dash }));

    expect(container.textContent).toContain('Selected: Colorado United - Dash');
    expect(container.textContent).not.toContain('2014/15G Copper');
  });

  it('shows no confirmation for a row that does not belong to the selected id', async () => {
    const rendered = renderSelector({ value: 'team-dash', selectedTeam: copper });
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);

    expect(container.textContent).not.toContain('Selected:');
  });

  async function pressClosed(target: HTMLElement, key: string) {
    const input = target.querySelector('input') as HTMLInputElement;
    await act(async () => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    await act(async () => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
    });
  }

  it('selects the top result on Enter with the dropdown closed', async () => {
    const onChange = vi.fn();
    const rendered = renderSelector({ onChange });
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    await typeQuery(container, 'colorado united');

    await pressClosed(container, 'Enter');

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('team-dash', dash);
  });

  it('selects nothing on Enter when there are no results', async () => {
    const onChange = vi.fn();
    const rendered = renderSelector({ onChange });
    ({ root, container } = rendered);
    await flushRender(root, rendered.element);
    await typeQuery(container, 'no such team');

    await pressClosed(container, 'Enter');

    expect(onChange).not.toHaveBeenCalled();
  });
});
