import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { GameExplainability, GameProviderIds, GameWithTeams } from '@/lib/types';

const { mockUseGameExplainability, mockUseGameProviderIds, mockUseTeamGames, mockUseUser } = vi.hoisted(() => ({
  mockUseGameExplainability: vi.fn(),
  mockUseGameProviderIds: vi.fn(),
  mockUseTeamGames: vi.fn(),
  mockUseUser: vi.fn(),
}));

const TEAM_ID = '11111111-1111-1111-1111-111111111111';
const OPPONENT_ID = '33333333-3333-3333-3333-333333333333';
const HOST_ID = '44444444-4444-4444-4444-444444444444';
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
    competition: 'Transfer Competition',
    event_name: 'Spring Cup',
    division_name: 'U10G Gold',
  },
  {
    id: 'game-unknown-opponent',
    game_date: '2026-09-20',
    home_team_master_id: TEAM_ID,
    away_team_master_id: null,
    home_score: 2,
    away_score: 1,
    ml_overperformance: null,
    home_team_name: 'Test FC 2013',
    competition: 'Fall League',
  },
  {
    id: 'game-away',
    game_date: '2026-09-27',
    home_team_master_id: HOST_ID,
    away_team_master_id: TEAM_ID,
    home_score: 0,
    away_score: 3,
    ml_overperformance: null,
    home_team_name: 'Host FC 2013',
    away_team_name: 'Test FC 2013',
    competition: 'Fall League',
  },
] as unknown as GameWithTeams[];

// Every id distinct, so a lookup that reads the wrong side or the wrong game sends a value no test expects.
const PROVIDER_IDS: GameProviderIds[] = GAMES.map((game) => ({
  id: game.id,
  home_provider_id: `home-of-${game.id}`,
  away_provider_id: `away-of-${game.id}`,
}));

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
  useGameProviderIds: mockUseGameProviderIds,
}));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock('@/components/MissingGamesForm', () => ({ MissingGamesForm: () => null }));
vi.mock('@/components/UnknownOpponentLink', () => ({
  UnknownOpponentLink: ({ opponentProviderId }: { opponentProviderId: string }) =>
    `Link-opponent dialog for ${opponentProviderId}`,
}));
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
  // Like useQuery: no data unless the component enables the fetch.
  mockUseGameProviderIds.mockImplementation((_gameIds: string[], enabled: boolean) => ({
    data: enabled ? PROVIDER_IDS : undefined,
  }));
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
  vi.unstubAllGlobals();
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

describe('GameHistoryTable competition column', () => {
  it('shows the event, not the Transfer Competition placeholder', async () => {
    await renderTable([]);
    const row = Array.from(container!.querySelectorAll('tr')).find((tr) => tr.textContent?.includes('1-1'))!;

    expect(row.textContent).toContain('Spring Cup');
    expect(row.textContent).not.toContain('Transfer Competition');
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
    // The team is at home, so the unknown opponent is the away registration.
    expect(unknownOpponentCell().textContent).toBe('Link-opponent dialog for away-of-game-unknown-opponent');
  });

  it.each([
    [
      'home',
      'Unlink Rival SC 2013',
      { gameId: HIGHLIGHTED_GAME_ID, opponentProviderId: `away-of-${HIGHLIGHTED_GAME_ID}`, teamIdMaster: OPPONENT_ID },
    ],
    [
      'away',
      'Unlink Host FC 2013',
      { gameId: 'game-away', opponentProviderId: 'home-of-game-away', teamIdMaster: HOST_ID },
    ],
  ])("unlinks with the opponent's registration when the team played %s", async (_side, label, expected) => {
    mockUseUser.mockReturnValue({ profile: { plan: 'admin' }, isLoading: false });
    const fetchMock = vi.fn(async () => ({ ok: false, json: async () => ({ error: 'stop here' }) }));
    vi.stubGlobal('fetch', fetchMock);
    await renderTable([]);

    await act(async () => (container!.querySelector(`[aria-label="${label}"]`) as HTMLElement).click());
    const confirm = Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent === 'Unlink')!;
    await act(async () => confirm.click());

    expect(fetchMock).toHaveBeenCalledWith('/api/unlink-opponent', expect.anything());
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, { body: string }];
    expect(JSON.parse(init.body)).toMatchObject(expected);
  });

  it("asks for the games' provider ids only for an admin", async () => {
    mockUseUser.mockReturnValue({ profile: { plan: 'premium' }, isLoading: false });
    mockUseGameProviderIds.mockClear();
    await renderTable([]);

    expect(mockUseGameProviderIds).toHaveBeenCalled();
    expect(mockUseGameProviderIds.mock.calls.every(([, enabled]) => enabled === false)).toBe(true);
  });

  it('shows no link or unlink control to an admin until the provider ids arrive', async () => {
    mockUseUser.mockReturnValue({ profile: { plan: 'admin' }, isLoading: false });
    mockUseGameProviderIds.mockReturnValue({ data: undefined });
    await renderTable([]);

    expect(unknownOpponentCell().textContent).toBe('Unknown');
    expect(container!.querySelector('[aria-label^="Unlink"]')).toBeNull();
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
