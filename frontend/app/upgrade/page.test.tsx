import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react-dom/test-utils';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';

const { mockPreview, state } = vi.hoisted(() => ({
  mockPreview: vi.fn(),
  state: { next: null as string | null },
}));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(state.next ? { next: state.next } : {}),
}));
vi.mock('@/hooks/useUser', () => ({ useUser: () => ({ user: null, isLoading: false }) }));
vi.mock('@/lib/events', () => ({
  trackUpgradePageViewed: vi.fn(),
  trackPlanSelected: vi.fn(),
  trackCheckoutInitiated: vi.fn(),
}));
vi.mock('@/lib/stripe/client', () => ({ startCheckout: vi.fn() }));
vi.mock('@/lib/api', () => ({
  api: {
    getDbStats: () => Promise.resolve({ totalTeams: 0, totalGames: 0 }),
    getPaywallTeamPreview: mockPreview,
  },
}));

import UpgradePage from './page';

let container: HTMLDivElement;
let root: Root;

async function render() {
  await act(async () => {
    root.render(<UpgradePage />);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.next = null;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe('UpgradePage paywall', () => {
  it('names the team the parent tapped', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue({
      team_name: 'Phoenix Rising 2014',
      club_name: 'Phoenix Rising',
      age: 12,
      gender: 'M',
      rank_in_cohort_final: 7,
    });
    await render();
    expect(mockPreview).toHaveBeenCalledWith(TEAM_ID);
    expect(container.textContent).toContain('You were looking at');
    expect(container.textContent).toContain('Phoenix Rising 2014');
    expect(container.textContent).toContain('#7 nationally');
  });

  it('does not look anything up for a next that is not a team page', async () => {
    state.next = '/compare';
    await render();
    expect(mockPreview).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain('You were looking at');
  });

  it('shows no banner when the team is unknown', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue(null);
    await render();
    expect(container.textContent).not.toContain('You were looking at');
  });

  it('shows one plan card on phones: the unselected card is hidden below md', async () => {
    await render();
    const hiddenOnPhone = Array.from(container.querySelectorAll('.hidden.md\\:block'));
    expect(hiddenOnPhone).toHaveLength(1);
    expect(hiddenOnPhone[0].textContent).toContain('Month-to-month');
  });

  it('keeps the sign-in link pointed at the tapped team', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue(null);
    await render();
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain(`/login?next=${encodeURIComponent(`/teams/${TEAM_ID}`)}`);
  });

  it('drops the old team banner when the destination is no longer a team', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue({
      team_name: 'Phoenix Rising 2014',
      club_name: null,
      age: 12,
      gender: 'M',
      rank_in_cohort_final: 7,
    });
    await render();
    expect(container.textContent).toContain('Phoenix Rising 2014');
    state.next = '/compare';
    await render();
    expect(container.textContent).not.toContain('Phoenix Rising 2014');
  });
});
