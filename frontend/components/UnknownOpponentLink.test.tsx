import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { GameWithTeams } from '@/lib/types';

const { mockUseTeamSearch } = vi.hoisted(() => ({ mockUseTeamSearch: vi.fn() }));

vi.mock('@/hooks/useTeamSearch', () => ({ useTeamSearch: mockUseTeamSearch }));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ refetchQueries: vi.fn() }) }));

import { UnknownOpponentLink } from './UnknownOpponentLink';

const GAME = {
  id: 'game-1',
  game_date: '2026-09-20',
  home_team_master_id: 'team-current',
  away_team_master_id: null,
  away_provider_id: 'gotsport-999',
  home_score: 2,
  away_score: 1,
} as unknown as GameWithTeams;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  mockUseTeamSearch.mockReturnValue({
    results: [],
    match: 'exact',
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  vi.clearAllMocks();
});

async function openAndType(query: string) {
  await act(async () => {
    root!.render(
      React.createElement(UnknownOpponentLink, {
        game: GAME,
        currentTeamId: 'team-current',
        opponentProviderId: 'gotsport-999',
      })
    );
  });
  await act(async () => {
    (container!.querySelector('button[aria-label="Link unknown opponent to a team"]') as HTMLButtonElement).click();
  });
  const input = document.body.querySelector('input[placeholder="Type team name..."]') as HTMLInputElement;
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
  await act(async () => {
    setValue.call(input, query);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('UnknownOpponentLink search', () => {
  // The opponent being linked can never be the team whose page this is; /api/link-opponent
  // has no check of its own against linking a team to itself.
  it('asks the hook for ten results without the current team', async () => {
    await act(async () => {
      root!.render(
        React.createElement(UnknownOpponentLink, {
          game: GAME,
          currentTeamId: 'team-current',
          opponentProviderId: 'gotsport-999',
        })
      );
    });

    expect(mockUseTeamSearch).toHaveBeenLastCalledWith('', { limit: 10, excludeId: 'team-current' });
  });

  // An admin links whatever row they pick to every game this provider id played, so a
  // typo-tolerant result must not look like an exact one.
  it.each([
    ['exact', false],
    ['similar', true],
    ['relaxed', true],
  ])('labels %s results as close matches: %s', async (match, labelled) => {
    mockUseTeamSearch.mockReturnValue({
      results: [
        {
          team_id_master: 'team-rebels',
          team_name: 'Rebels SC 2014',
          club_name: 'Rebels SC',
          state: 'CA',
          age: 13,
          gender: 'F',
        },
      ],
      match,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    await openAndType('rebles');

    expect(document.body.textContent).toContain('Rebels SC 2014');
    expect(document.body.textContent?.includes('Showing close matches')).toBe(labelled);
  });

  it('scrolls the row the arrow keys highlight into view', async () => {
    const scrolled: Element[] = [];
    const original = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = function (this: HTMLElement) {
      scrolled.push(this);
    };
    try {
      const rebels = {
        team_id_master: 'team-rebels',
        team_name: 'Rebels SC 2014',
        club_name: 'Rebels SC',
        state: 'CA',
        age: 13,
        gender: 'F',
      };
      mockUseTeamSearch.mockReturnValue({
        results: [rebels, { ...rebels, team_id_master: 'team-rebels-2', team_name: 'Rebels SC 2014 Blue' }],
        match: 'similar',
        isLoading: false,
        isError: false,
        error: null,
        refetch: vi.fn(),
      });
      await openAndType('rebles');
      const input = document.body.querySelector('input[placeholder="Type team name..."]') as HTMLInputElement;
      await act(async () => {
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
      });

      expect(scrolled.at(-1)?.tagName).toBe('BUTTON');
      expect(scrolled.at(-1)?.textContent).toContain('Rebels SC 2014 Blue');
    } finally {
      HTMLElement.prototype.scrollIntoView = original;
    }
  });

  it('offers nothing, not even a new team, for a single letter followed by a space', async () => {
    await openAndType('a ');

    expect(document.body.textContent).not.toContain('No teams found');
    expect(document.body.textContent).not.toContain('as new team');
  });
});
