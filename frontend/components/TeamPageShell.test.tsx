import { afterEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockUseTeam, mockPush, mockSearchParams } = vi.hoisted(() => ({
  mockUseTeam: vi.fn(),
  mockPush: vi.fn(),
  mockSearchParams: { current: new URLSearchParams() },
}));

vi.mock('@/lib/hooks', () => ({ useTeam: mockUseTeam }));
vi.mock('next/navigation', () => ({
  useSearchParams: () => mockSearchParams.current,
  useRouter: () => ({ push: mockPush }),
}));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock('next/dynamic', () => ({ default: () => () => null }));
vi.mock('@/components/TeamHeader', () => ({ TeamHeader: () => null }));
vi.mock('@/components/GameHistoryTable', () => ({ GameHistoryTable: () => null }));
vi.mock('@/components/UpcomingGamesTable', () => ({ UpcomingGamesTable: () => null }));
vi.mock('@/components/Breadcrumbs', () => ({ Breadcrumbs: () => null }));

import { TeamPageShell } from './TeamPageShell';

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
}

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.clearAllMocks();
});

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
});
