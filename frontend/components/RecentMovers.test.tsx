import { afterEach, describe, expect, it } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { RecentMovers } from './RecentMovers';
import { makeRankingRow as makeTeam } from '@/test/fixtures';
import type { RankingRow } from '@/types/RankingRow';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function renderMovers(movers7d: RankingRow[], movers30d: RankingRow[] = []) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(
      React.createElement(RecentMovers, {
        initialMovers7d: movers7d,
        initialMovers30d: movers30d,
        cohortLabel: 'U12 Boys',
      })
    );
    await Promise.resolve();
  });
}

function moverRow(): HTMLAnchorElement {
  const row = container!.querySelector('a[href^="/teams/"]');
  expect(row).not.toBeNull();
  return row as HTMLAnchorElement;
}

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  localStorage.clear();
});

describe('RecentMovers', () => {
  it('names the cohort and the national scope in the card description', async () => {
    await renderMovers([makeTeam()]);

    expect(container!.textContent).toContain('U12 Boys');
    expect(container!.textContent).toContain('Recent Movers (Nationally)');
    expect(container!.textContent).not.toContain('Biggest rank changes');
  });

  it('shows the move size with the current rank beneath it', async () => {
    await renderMovers([makeTeam({ rank_in_cohort_final: 89, rank_change_7d: 258 })]);

    expect(container!.textContent).toContain('258');
    expect(container!.textContent).toContain('Now #89');
  });

  it('shows the current rank for fallers too', async () => {
    await renderMovers([makeTeam({ rank_in_cohort_final: 400, rank_change_7d: -90 })]);

    expect(container!.textContent).toContain('90');
    expect(container!.textContent).toContain('Now #400');
  });

  it('keeps the rank on the badge side, not under the team name', async () => {
    await renderMovers([makeTeam({ rank_in_cohort_final: 89, rank_change_7d: 258, state: 'AZ' })]);

    const [info, badgeSide] = Array.from(moverRow().children);
    expect(info.textContent).toContain('AZ');
    expect(info.textContent).not.toContain('#');
    expect(badgeSide.textContent).toContain('Now #89');
  });

  // The row link's label replaces everything inside it, so the direction is spoken there, not on the badge.
  it('tells screen readers which way each team moved', async () => {
    await renderMovers([
      makeTeam({ team_id_master: 'up', rank_in_cohort_final: 89, rank_change_7d: 258 }),
      makeTeam({ team_id_master: 'down', rank_in_cohort_final: 400, rank_change_7d: -90 }),
    ]);

    const labels = Array.from(container!.querySelectorAll('a[href^="/teams/"]')).map((a) =>
      a.getAttribute('aria-label')
    );
    expect(labels[0]).toContain('Rank 89, up 258 in the last 7 days');
    expect(labels[1]).toContain('Rank 400, down 90 in the last 7 days');
  });

  it('reads each row like a rankings row: rank, movement over the window shown, team, state, PowerScore', async () => {
    await renderMovers(
      [
        makeTeam({
          team_name: 'Week FC',
          club_name: null,
          state: 'AZ',
          rank_in_cohort_final: 89,
          rank_change_7d: 258,
          power_score_final: 0.5,
        }),
      ],
      [
        makeTeam({
          team_name: 'Month FC',
          club_name: null,
          state: 'AZ',
          rank_in_cohort_final: 400,
          rank_change_30d: -120,
          power_score_final: 0.25,
        }),
      ]
    );
    expect(moverRow().getAttribute('aria-label')).toBe(
      'Rank 89, up 258 in the last 7 days, Week FC, AZ, PowerScore 50.00'
    );

    await act(async () => {
      (container!.querySelector('[aria-label="Show 30-day rank changes"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(moverRow().getAttribute('aria-label')).toBe(
      'Rank 400, down 120 in the last 30 days, Month FC, AZ, PowerScore 25.00'
    );
  });

  it('shows the empty state when there are no movers', async () => {
    await renderMovers([]);

    expect(container!.textContent).toContain('No significant rank changes');
    expect(container!.querySelector('a[href^="/teams/"]')).toBeNull();
  });

  it('switches to the 30-day movers and persists the choice', async () => {
    await renderMovers(
      [makeTeam({ team_id_master: 'week', team_name: 'Week FC' })],
      // 7d and 30d disagree in sign and magnitude, so a badge reading the wrong
      // field shows the wrong direction.
      [makeTeam({ team_id_master: 'month', team_name: 'Month FC', rank_change_7d: 40, rank_change_30d: -120 })]
    );

    await act(async () => {
      (container!.querySelector('[aria-label="Show 30-day rank changes"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });

    expect(container!.textContent).toContain('Month FC');
    expect(container!.textContent).not.toContain('Week FC');
    expect(container!.textContent).toContain('30 days');
    expect(moverRow().getAttribute('aria-label')).toContain('down 120 in the last 30 days');
    expect(localStorage.getItem('recentMoversTimeWindow')).toBe('30d');
  });

  it('restores the saved window preference on mount', async () => {
    localStorage.setItem('recentMoversTimeWindow', '30d');

    await renderMovers(
      [makeTeam({ team_id_master: 'week', team_name: 'Week FC' })],
      [makeTeam({ team_id_master: 'month', team_name: 'Month FC', rank_change_30d: 120 })]
    );

    expect(container!.textContent).toContain('Month FC');
    expect(container!.textContent).not.toContain('Week FC');
    expect(container!.textContent).toContain('30 days');
  });
});
