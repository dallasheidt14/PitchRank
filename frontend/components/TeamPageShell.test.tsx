import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockUseTeam, mockPush, mockBack, mockSearchParams, mockBreadcrumbs } = vi.hoisted(() => ({
  mockBreadcrumbs: vi.fn(() => null),
  mockUseTeam: vi.fn(),
  mockPush: vi.fn(),
  mockBack: vi.fn(),
  mockSearchParams: { current: new URLSearchParams() },
}));

vi.mock('@/lib/hooks', () => ({ useTeam: mockUseTeam }));
vi.mock('next/navigation', () => ({
  useSearchParams: () => mockSearchParams.current,
  useRouter: () => ({ push: mockPush, back: mockBack }),
}));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock('next/dynamic', () => ({ default: () => () => null }));
vi.mock('@/components/TeamHeader', () => ({ TeamHeader: () => null }));
vi.mock('@/components/GameHistoryTable', () => ({ GameHistoryTable: () => null }));
vi.mock('@/components/UpcomingGamesTable', () => ({ UpcomingGamesTable: () => null }));
vi.mock('@/components/Breadcrumbs', () => ({ Breadcrumbs: mockBreadcrumbs }));

import { TeamPageShell } from './TeamPageShell';
import { markIfOpenedFromRankings, noteTeamOpenedFromRankings } from '@/hooks/useRankingsViewState';

const startUrl = window.location.href;
let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function clickBackToRankings(query: string, team: { state: string | null; age: number; gender: string }) {
  mockSearchParams.current = new URLSearchParams(query);
  mockUseTeam.mockReturnValue({ data: team });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(React.createElement(TeamPageShell, { id: 'team-1' })));
  const button = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Back to Rankings')!;
  await act(async () => button.click());
  return button;
}

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.restoreAllMocks();
  vi.clearAllMocks();
  window.history.replaceState(null, '', startUrl);
  markIfOpenedFromRankings();
});

const QUERY = 'region=national&ageGroup=u13&gender=female';
const TEAM_URL = `/teams/team-1?${QUERY}`;
const GIRLS_TEAM = { state: 'AZ', age: 13, gender: 'F' };
const MARKED_ENTRY = { __NA: true, __pitchrankFromRankings: true, __pitchrankTeamSeen: true };

function traverseTo(state: object, url: string) {
  window.history.replaceState(state, '', url);
  window.dispatchEvent(new PopStateEvent('popstate', { state }));
}

describe('TeamPageShell Back to Rankings', () => {
  it('returns a girls team to the girls board the rankings row linked from', async () => {
    await clickBackToRankings('region=national&ageGroup=u13&gender=f', { state: 'AZ', age: 13, gender: 'F' });

    expect(mockUseTeam).toHaveBeenCalledWith('team-1');
    expect(mockPush).toHaveBeenCalledWith('/rankings/national/u13/female');
  });

  it("opens the team's own board when the page was reached without a rankings query", async () => {
    await clickBackToRankings('', { state: 'AZ', age: 13, gender: 'F' });

    expect(mockPush).toHaveBeenCalledWith('/rankings/az/u13/female');
  });

  it('goes back to the rankings entry a row opened this page from, where the list kept its place', async () => {
    noteTeamOpenedFromRankings(TEAM_URL);
    window.history.replaceState({ __NA: true }, '', TEAM_URL);

    await clickBackToRankings(QUERY, GIRLS_TEAM);

    expect(mockBack).toHaveBeenCalledTimes(1);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('still goes back when the marked page is reached again by Back or Forward, with no row click', async () => {
    window.history.replaceState(MARKED_ENTRY, '', TEAM_URL);

    await clickBackToRankings(QUERY, GIRLS_TEAM);

    expect(mockBack).toHaveBeenCalledTimes(1);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('ignores a second tap before the back lands', async () => {
    window.history.replaceState(MARKED_ENTRY, '', TEAM_URL);

    const button = await clickBackToRankings(QUERY, GIRLS_TEAM);
    await act(async () => button.click());

    expect(mockBack).toHaveBeenCalledTimes(1);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('ignores a second tap after the back lands, while this page is still up', async () => {
    window.history.replaceState(MARKED_ENTRY, '', TEAM_URL);

    const button = await clickBackToRankings(QUERY, GIRLS_TEAM);
    traverseTo({ __NA: true }, '/rankings/national/u13/female');
    await act(async () => button.click());

    expect(mockBack).toHaveBeenCalledTimes(1);
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('works again when Forward returns to this page before the board rendered', async () => {
    window.history.replaceState(MARKED_ENTRY, '', TEAM_URL);

    const button = await clickBackToRankings(QUERY, GIRLS_TEAM);
    traverseTo({ __NA: true }, '/rankings/national/u13/female');
    traverseTo(MARKED_ENTRY, TEAM_URL);
    await act(async () => button.click());

    expect(mockBack).toHaveBeenCalledTimes(2);
  });

  it('works again when the browser restores this page from its back/forward cache', async () => {
    window.history.replaceState(MARKED_ENTRY, '', TEAM_URL);

    const button = await clickBackToRankings(QUERY, GIRLS_TEAM);
    window.dispatchEvent(new Event('pageshow'));
    await act(async () => button.click());

    expect(mockBack).toHaveBeenCalledTimes(2);
  });

  it('still renders and opens the board when the history write fails', async () => {
    noteTeamOpenedFromRankings(TEAM_URL);
    window.history.replaceState({ __NA: true }, '', TEAM_URL);
    vi.spyOn(window.history, 'replaceState').mockImplementation(() => {
      throw new DOMException('Attempt to use history.replaceState() more than 100 times', 'SecurityError');
    });

    await clickBackToRankings(QUERY, GIRLS_TEAM);

    expect(mockBack).not.toHaveBeenCalled();
    expect(mockPush).toHaveBeenCalledWith('/rankings/national/u13/female');
  });
});

describe('TeamPageShell breadcrumbs', () => {
  async function renderShell(team: object | undefined) {
    mockUseTeam.mockReturnValue({ data: team });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root!.render(React.createElement(TeamPageShell, { id: 'team-1' })));
    return (mockBreadcrumbs.mock.calls.at(-1) as unknown as [{ items: { label: string; href: string }[] }])[0].items;
  }

  it('ends in the team name after its own board, not in the team id', async () => {
    const items = await renderShell({
      team_name: 'Phoenix United 2014 Elite',
      club_name: 'Phoenix United',
      state: 'AZ',
      age: 13,
      gender: 'M',
    });

    expect(items).toEqual([
      { label: 'Home', href: '/' },
      { label: 'Rankings', href: '/rankings' },
      { label: 'Arizona U13 Boys', href: '/rankings/az/u13/male' },
      { label: 'Phoenix United 2014 Elite', href: '/teams/team-1' },
    ]);
  });

  it('points a team with no state at the national board', async () => {
    const items = await renderShell({
      team_name: 'Lone Star 2011',
      club_name: null,
      state: null,
      age: 16,
      gender: 'F',
    });

    expect(items[2]).toEqual({ label: 'National U16 Girls', href: '/rankings/national/u16/female' });
  });

  it('ends with a plain team crumb until the team loads, so Rankings is never the current page', async () => {
    const items = await renderShell(undefined);

    expect(items).toEqual([
      { label: 'Home', href: '/' },
      { label: 'Rankings', href: '/rankings' },
      { label: 'Team', href: '/teams/team-1' },
    ]);
  });

  it('goes straight from Rankings to the team when no board ranks its age', async () => {
    const items = await renderShell({
      team_name: 'Mesa FC 2018',
      club_name: 'Mesa FC',
      state: 'AZ',
      age: 9,
      gender: 'M',
    });

    expect(items).toEqual([
      { label: 'Home', href: '/' },
      { label: 'Rankings', href: '/rankings' },
      { label: 'Mesa FC 2018', href: '/teams/team-1' },
    ]);
  });

  it('names a team with a placeholder name by its club', async () => {
    const items = await renderShell({
      team_name: 'unknown_4482913',
      club_name: 'Aardvark SC',
      state: 'AZ',
      age: 13,
      gender: 'M',
    });

    expect(items.at(-1)).toEqual({ label: 'Aardvark SC', href: '/teams/team-1' });
  });
});
