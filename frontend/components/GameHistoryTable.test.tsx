import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { GameExplainability, GameWithTeams } from '@/lib/types';

const { mockUseGameExplainability, mockUseTeamGames, mockUseUser } = vi.hoisted(() => ({
  mockUseGameExplainability: vi.fn(),
  mockUseTeamGames: vi.fn(),
  mockUseUser: vi.fn(),
}));

const TEAM_ID = '11111111-1111-1111-1111-111111111111';
const OPPONENT_ID = '33333333-3333-3333-3333-333333333333';
const HIGHLIGHTED_GAME_ID = 'game-highlighted';

const GAMES = [
  {
    id: HIGHLIGHTED_GAME_ID,
    game_date: '2026-09-06',
    home_team_master_id: TEAM_ID,
    away_team_master_id: OPPONENT_ID,
    home_score: 4,
    away_score: 0,
    ml_overperformance: 3,
    home_team_name: 'Test FC 2013',
    away_team_name: 'Rival SC 2013',
    competition: 'Fall League',
  },
  {
    id: 'game-plain',
    game_date: '2026-09-13',
    home_team_master_id: TEAM_ID,
    away_team_master_id: OPPONENT_ID,
    home_score: 1,
    away_score: 1,
    ml_overperformance: 0.2,
    home_team_name: 'Test FC 2013',
    away_team_name: 'Rival SC 2013',
    competition: 'Fall League',
  },
  {
    id: 'game-unknown-opponent',
    game_date: '2026-09-20',
    home_team_master_id: TEAM_ID,
    away_team_master_id: null,
    away_provider_id: 'gotsport-999',
    home_score: 2,
    away_score: 1,
    ml_overperformance: null,
    home_team_name: 'Test FC 2013',
    competition: 'Fall League',
  },
] as unknown as GameWithTeams[];

const BREAKDOWN: GameExplainability = {
  team_id: TEAM_ID,
  game_uuid: HIGHLIGHTED_GAME_ID,
  game_id: 'provider-game-1',
  opp_id: OPPONENT_ID,
  game_date: '2026-09-06',
  gf: 4,
  ga: 0,
  team_mu: 1500,
  team_sigma: 82,
  opp_mu: 1670,
  opp_sigma: 79,
  expected_outcome: 0.42,
  actual_outcome: 0.86,
  outcome_surprise: 0.44,
  g_factor: 0.94,
  recency_weight: 0.12,
  rating_contribution: 0.14,
  off_residual: 2.1,
  def_residual: 0.4,
};

const LOADED_GAMES = {
  data: { games: GAMES, lastScrapedAt: null },
  isLoading: false,
  isError: false,
  error: null,
  refetch: vi.fn(),
};

vi.mock('@/lib/hooks', () => ({
  useTeamGames: mockUseTeamGames,
  useTeam: () => ({ data: { team_name: 'Test FC 2013', age: 13, gender: 'M' } }),
  usePrefetchTeam: () => vi.fn(),
  useGameExplainability: mockUseGameExplainability,
}));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock('@/components/MissingGamesForm', () => ({ MissingGamesForm: () => null }));
vi.mock('@/components/UnknownOpponentLink', () => ({ UnknownOpponentLink: () => 'Link-opponent dialog' }));
vi.mock('@/hooks/useUser', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/hooks/useUser')>()),
  useUser: mockUseUser,
}));
vi.mock('@/components/MergeTeamsDialogWrapper', () => ({ MergeTeamsDialogWrapper: () => 'Merge-teams dialog' }));

import { GameHistoryTable } from './GameHistoryTable';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function renderTable(explanations: GameExplainability[]) {
  mockUseGameExplainability.mockReturnValue({ data: explanations });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(GameHistoryTable, { teamId: TEAM_ID })));
}

function unknownOpponentCell(): HTMLElement {
  const row = Array.from(container!.querySelectorAll('tr')).find((tr) => tr.textContent?.includes('2-1'))!;
  return row.querySelectorAll('td')[1];
}

function highlightedScore(): HTMLElement {
  return Array.from(container!.querySelectorAll('td')).find((cell) => cell.textContent === '4-0')!
    .firstElementChild as HTMLElement;
}

beforeEach(() => {
  mockUseTeamGames.mockReturnValue(LOADED_GAMES);
  mockUseUser.mockReturnValue({ profile: null, isLoading: false });
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query) =>
      ({
        matches: query === '(hover: none) and (pointer: coarse)',
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList
  );
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.restoreAllMocks();
});

describe('GameHistoryTable highlighted scores', () => {
  it('makes an explained score a button that opens its explanation on tap, and says so', async () => {
    await renderTable([BREAKDOWN]);
    const score = highlightedScore();

    expect(score.tagName).toBe('BUTTON');
    expect(score.getAttribute('type')).toBe('button');
    expect(container!.textContent).toContain('Tap or hover a highlighted score for details.');

    await act(async () => score.click());

    expect(document.body.textContent).toContain('better than model expectation');
  });

  it('explains the colours without promising details when no explanation has loaded', async () => {
    await renderTable([]);

    expect(highlightedScore().tagName).toBe('SPAN');
    expect(container!.textContent).toContain('2+ goals better than PitchRank expected');
    expect(container!.textContent).not.toContain('Tap or hover');
  });
});

describe('GameHistoryTable opponent data controls', () => {
  it.each([
    ['signed-out visitor', null, false],
    ['subscriber', { plan: 'premium' }, false],
    ['admin whose profile is still loading', { plan: 'admin' }, true],
  ])('hides unlinking and linking opponents from a %s', async (_who, profile, isLoading) => {
    mockUseUser.mockReturnValue({ profile, isLoading });
    await renderTable([]);

    expect(container!.querySelector('[aria-label^="Unlink"]')).toBeNull();
    expect(unknownOpponentCell().textContent).toBe('Unknown');
  });

  it('shows both to an admin', async () => {
    mockUseUser.mockReturnValue({ profile: { plan: 'admin' }, isLoading: false });
    await renderTable([]);

    expect(container!.querySelectorAll('[aria-label="Unlink Rival SC 2013"]')).toHaveLength(2);
    expect(unknownOpponentCell().textContent).toBe('Link-opponent dialog');
  });
});

describe('GameHistoryTable merge-teams control', () => {
  const GAMES_STATES = [
    ['loading', { data: undefined, isLoading: true, isError: false, error: null, refetch: vi.fn() }],
    ['failed', { data: undefined, isLoading: false, isError: true, error: new Error('down'), refetch: vi.fn() }],
    [
      'empty',
      { data: { games: [], lastScrapedAt: null }, isLoading: false, isError: false, error: null, refetch: vi.fn() },
    ],
  ] as const;

  it.each(GAMES_STATES)('hides it from a subscriber while the games list is %s', async (_state, games) => {
    mockUseTeamGames.mockReturnValue(games);
    mockUseUser.mockReturnValue({ profile: { plan: 'premium' }, isLoading: false });
    await renderTable([]);

    expect(container!.textContent).not.toContain('Merge-teams dialog');
  });

  it.each(GAMES_STATES)('shows it to an admin while the games list is %s', async (_state, games) => {
    mockUseTeamGames.mockReturnValue(games);
    mockUseUser.mockReturnValue({ profile: { plan: 'admin' }, isLoading: false });
    await renderTable([]);

    expect(container!.textContent).toContain('Merge-teams dialog');
  });
});
