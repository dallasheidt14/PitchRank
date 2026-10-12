import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react-dom/test-utils';

const { mockUseTeam } = vi.hoisted(() => ({ mockUseTeam: vi.fn() }));

vi.mock('@/lib/hooks', () => ({ useTeam: mockUseTeam }));

vi.mock('@/hooks/useUser', () => ({
  useUser: () => ({ profile: null, isLoading: false }),
  hasPremiumAccess: () => false,
  hasAdminAccess: () => false,
}));

vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({}) }));

vi.mock('@/lib/watchlist', () => ({
  addToWatchlist: vi.fn(),
  removeFromWatchlist: vi.fn(),
  isWatched: () => false,
  addToSupabaseWatchlist: vi.fn(),
  removeFromSupabaseWatchlist: vi.fn(),
}));

vi.mock('@/lib/events', () => ({
  trackTeamPageViewed: vi.fn(),
  trackWatchlistAdded: vi.fn(),
  trackWatchlistRemoved: vi.fn(),
}));

vi.mock('@/components/ShareButtons', () => ({ ShareButtons: () => null }));
vi.mock('@/components/NotificationBell', () => ({ NotificationBell: () => null }));
vi.mock('@/components/TeamSchema', () => ({ TeamSchema: () => null }));
vi.mock('@/components/ui/Toaster', () => ({ toast: vi.fn() }));

import { TeamHeader } from '@/components/TeamHeader';
import { TooltipProvider } from '@/components/ui/tooltip';
import { POWERSCORE_DEFINITION } from '@/lib/constants';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';

const TEAM = {
  team_id_master: TEAM_ID,
  team_name: 'Rush WI 2012 Rush',
  club_name: 'Rush Wisconsin',
  state: 'WI',
  age: 15,
  gender: 'F',
  rank_in_cohort_final: 12,
  power_score_final: 0.71,
  total_games_played: 40,
  games_played: 28,
  offense_norm: 0.62,
  defense_norm: 0.48,
  sos_rank_state: 7,
  sos_rank_national: 140,
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }))
  );
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query) =>
      ({
        matches: query === '(hover: none) and (pointer: coarse)',
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList
  );
  mockUseTeam.mockReturnValue({ data: TEAM, isLoading: false, isError: false, error: null, refetch: vi.fn() });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('TeamHeader explanations on a touch screen', () => {
  it.each([
    ['PowerScore', POWERSCORE_DEFINITION],
    ['Games Played', 'Total completed games across all time'],
    ['Ranked Games', 'Recent games used in PowerScore calculation'],
    ['Offense', 'Offensive strength: better than 62% of teams'],
    ['Defense', 'Defensive strength: better than 48% of teams'],
    ['State SOS', '#7 toughest schedule in WI'],
    ['National SOS', '#140 toughest schedule nationally'],
  ])('%s is a button that opens its explanation on tap', (label, explanation) => {
    act(() => {
      root.render(React.createElement(TooltipProvider, null, React.createElement(TeamHeader, { teamId: TEAM_ID })));
    });
    const trigger = Array.from(container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes(label)
    )!;
    expect(trigger.getAttribute('type')).toBe('button');
    expect(document.body.textContent).not.toContain(explanation);

    act(() => trigger.click());

    expect(document.body.textContent).toContain(explanation);
  });
});
