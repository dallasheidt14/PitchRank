import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { GameExplainability, GameWithTeams } from '@/lib/types';

const { mockUseGameExplainability } = vi.hoisted(() => ({ mockUseGameExplainability: vi.fn() }));

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

vi.mock('@/lib/hooks', () => ({
  useTeamGames: () => ({
    data: { games: GAMES, lastScrapedAt: null },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  useTeam: () => ({ data: { team_name: 'Test FC 2013', age: 13, gender: 'M' } }),
  usePrefetchTeam: () => vi.fn(),
  useGameExplainability: mockUseGameExplainability,
}));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock('@/components/MissingGamesForm', () => ({ MissingGamesForm: () => null }));
vi.mock('@/components/UnknownOpponentLink', () => ({ UnknownOpponentLink: () => null }));
vi.mock('@/components/MergeTeamsDialogWrapper', () => ({ MergeTeamsDialogWrapper: () => null }));

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

function highlightedScore(): HTMLElement {
  return Array.from(container!.querySelectorAll('td')).find((cell) => cell.textContent === '4-0')!
    .firstElementChild as HTMLElement;
}

beforeEach(() => {
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
