import React, { act } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createRoot, type Root } from 'react-dom/client';

import { GameBreakdownPanel } from './GameBreakdownPanel';

const breakdown = {
  team_id: '11111111-1111-1111-1111-111111111111',
  game_uuid: '22222222-2222-2222-2222-222222222222',
  game_id: 'provider-game-1',
  opp_id: '33333333-3333-3333-3333-333333333333',
  game_date: '2026-04-01',
  gf: 4,
  ga: 0,
  team_mu: 1500,
  team_sigma: 80,
  opp_mu: 1560,
  opp_sigma: 77,
  expected_outcome: 0.41,
  actual_outcome: 0.86,
  outcome_surprise: 0.45,
  g_factor: 0.94,
  recency_weight: 0.12,
  rating_contribution: 0.14,
  off_residual: 2.1,
  def_residual: 0.4,
};

function renderPanel() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  return { container, root };
}

async function flushRender(root: Root, element: React.ReactElement) {
  await act(async () => {
    root.render(element);
    await Promise.resolve();
  });
}

describe('GameBreakdownPanel', () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    const render = renderPanel();
    root = render.root;
    container = render.container;
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

  it('renders a premium breakdown summary', async () => {
    await flushRender(
      root!,
      React.createElement(GameBreakdownPanel, {
        teamId: breakdown.team_id,
        gameId: breakdown.game_uuid,
        breakdown,
        isPremium: true,
        isLoading: false,
      })
    );

    expect(container?.textContent).toContain('Outperformed expectation');
    expect(container?.textContent).toContain('Above expectation');
    expect(container?.textContent).toContain('PitchRank expected roughly 2-0.');
    expect(container?.textContent).toContain('Actual result: 4-0 (margin +4.0 goals).');
  });

  it('shows an unavailable message when breakdown data is missing', async () => {
    await flushRender(
      root!,
      React.createElement(GameBreakdownPanel, {
        teamId: breakdown.team_id,
        gameId: breakdown.game_uuid,
        breakdown: undefined,
        isPremium: false,
        isLoading: false,
      })
    );

    expect(container?.textContent).toContain('Breakdown unavailable for this game yet');
  });
});
