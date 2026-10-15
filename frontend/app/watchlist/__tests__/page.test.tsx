// The watchlist card says "Not ranked yet" only when the ranking says why: the team is short of games.
import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockUseQuery } = vi.hoisted(() => ({ mockUseQuery: vi.fn() }));

vi.mock('@tanstack/react-query', () => ({
  useQuery: mockUseQuery,
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock('@/hooks/useUser', () => ({
  useUser: () => ({ user: { id: 'u1' }, profile: { plan: 'premium' }, isLoading: false }),
  hasPremiumAccess: () => true,
}));
vi.mock('@/hooks/useWatchlistMigration', () => ({ useWatchlistMigration: () => {} }));
vi.mock('@/lib/watchlist', () => ({
  fetchWatchlist: vi.fn(),
  removeFromSupabaseWatchlist: vi.fn(),
  initWatchlist: vi.fn(),
}));
vi.mock('@/components/insights', () => ({ InsightModal: () => null, DeltaIndicator: () => null }));

import WatchlistPage from '../page';

const team = (id: string, name: string, rank: number | null, status: string | null) => ({
  team_id_master: id,
  team_name: name,
  club_name: null,
  state: 'AZ',
  age: 13,
  gender: 'M',
  rank_in_cohort_final: rank,
  rank_in_state_final: null,
  status,
  power_score_final: 0.5,
  sos_norm: null,
  sos_rank_state: null,
  sos_rank_national: null,
  rank_change_7d: null,
  rank_change_30d: null,
  wins: 1,
  losses: 0,
  draws: 0,
  games_played: 1,
  total_games_played: 1,
  win_percentage: null,
  new_games_count: 0,
  last_game_date: null,
  last_5_results: [],
  watchlist_added_at: '2026-10-01T00:00:00Z',
});

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe('WatchlistPage cards', () => {
  it('notes "Not ranked yet" only on a team short of games', async () => {
    mockUseQuery.mockReturnValue({
      data: {
        teams: [
          team('t1', 'Ranked FC', 7, 'Active'),
          team('t2', 'Fresh FC', null, 'Not Enough Ranked Games'),
          // No ranking row (an inactive team, or a failed lookup): the page can't say why.
          team('t3', 'Quiet FC', null, null),
        ],
      },
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: vi.fn(),
      status: 'success',
      fetchStatus: 'idle',
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root!.render(React.createElement(WatchlistPage)));

    const cardOf = (name: string) =>
      Array.from(container!.querySelectorAll('h3')).find((h) => h.textContent === name)!.parentElement!;
    expect(cardOf('Fresh FC').textContent).toContain('Not ranked yet');
    expect(cardOf('Ranked FC').textContent).not.toContain('Not ranked yet');
    expect(cardOf('Quiet FC').textContent).not.toContain('Not ranked yet');
  });
});
