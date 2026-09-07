import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react-dom/test-utils';

const { mockUseTeam, mockUseUser, mockTrackTeamPageViewed } = vi.hoisted(() => ({
  mockUseTeam: vi.fn(),
  mockUseUser: vi.fn(),
  mockTrackTeamPageViewed: vi.fn(),
}));

vi.mock('@/lib/hooks', () => ({ useTeam: mockUseTeam }));

vi.mock('@/hooks/useUser', () => ({
  useUser: mockUseUser,
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
  trackTeamPageViewed: mockTrackTeamPageViewed,
  trackWatchlistAdded: vi.fn(),
  trackWatchlistRemoved: vi.fn(),
}));

vi.mock('@/components/ShareButtons', () => ({ ShareButtons: () => null }));
vi.mock('@/components/NotificationBell', () => ({ NotificationBell: () => null }));
vi.mock('@/components/TeamSchema', () => ({ TeamSchema: () => null }));
vi.mock('@/components/ui/Toaster', () => ({ toast: vi.fn() }));

vi.mock('@/components/ui/tooltip', async () => {
  const ReactModule = await import('react');
  return {
    Tooltip: ({ children }: { children: React.ReactNode }) => ReactModule.createElement('div', null, children),
    TooltipTrigger: ({ children }: { children: React.ReactNode }) => ReactModule.createElement('div', null, children),
    TooltipContent: ({ children }: { children: React.ReactNode }) => ReactModule.createElement('div', null, children),
  };
});

import { TeamHeader } from '@/components/TeamHeader';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';

const TEAM = {
  team_id_master: TEAM_ID,
  team_name: 'Rush WI 2012 Rush',
  club_name: 'Rush Wisconsin',
  state: 'WI',
  age: 15,
  gender: 'Female',
  rank_in_cohort_final: 12,
  power_score_final: 0.71,
};

let container: HTMLDivElement;
let root: Root;
let fetchMock: ReturnType<typeof vi.fn>;

/** The beacon POSTs made so far, ignoring the component's other fetches. */
function beaconCalls() {
  return fetchMock.mock.calls.filter(([url]) => url === '/api/track-team-view');
}

function renderHeader() {
  act(() => {
    root.render(React.createElement(TeamHeader, { teamId: TEAM_ID }));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);

  fetchMock = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
  vi.stubGlobal('fetch', fetchMock);

  mockUseUser.mockReturnValue({ profile: null, isLoading: false });
  mockUseTeam.mockReturnValue({
    data: TEAM,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe('TeamHeader view beacon', () => {
  it('posts the canonical team id once when team data loads', () => {
    renderHeader();

    expect(beaconCalls()).toHaveLength(1);
    const [, init] = beaconCalls()[0];
    expect(JSON.parse(init.body)).toEqual({ teamId: TEAM_ID });
    expect(init.method).toBe('POST');
  });

  it('does not post again when the same team arrives as a fresh object', () => {
    // A refetch hands the effect a new object with the same id, which is what the
    // ref guard is for. Re-rendering with the identical reference would not re-run
    // the effect at all, and so would pass with the guard deleted.
    renderHeader();
    mockUseTeam.mockReturnValue({
      data: { ...TEAM },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    renderHeader();
    renderHeader();

    expect(beaconCalls()).toHaveLength(1);
  });

  it('survives its own page load without waiting for the response', () => {
    // keepalive lets the request outlive a tab close between data load and send.
    renderHeader();

    const [, init] = beaconCalls()[0];
    expect(init.keepalive).toBe(true);
  });

  it('attaches a rejection handler so a failed beacon cannot surface to the reader', () => {
    // Asserted on the promise rather than through process.on('unhandledRejection'):
    // vitest installs its own handler, so an escaping rejection never reaches Node
    // and a test watching for one passes with the .catch() deleted.
    const rejected = Promise.reject(new Error('offline'));
    const catchSpy = vi.spyOn(rejected, 'catch');
    fetchMock.mockReturnValue(rejected);

    renderHeader();

    expect(catchSpy).toHaveBeenCalled();
    rejected.catch(() => {});
  });

  it('keeps rendering the page when fetch throws synchronously', () => {
    // A browser extension wrapping window.fetch can throw rather than reject, and
    // .catch() never sees that. Recording a view must not cost the reader the page.
    fetchMock.mockImplementation(() => {
      throw new Error('blocked');
    });

    expect(() => renderHeader()).not.toThrow();
    // The GA4 call precedes the beacon and must not become collateral damage.
    expect(mockTrackTeamPageViewed).toHaveBeenCalledWith(expect.objectContaining({ team_id_master: TEAM_ID }));
  });

  it('records nothing until the team resolves', () => {
    mockUseTeam.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderHeader();

    expect(beaconCalls()).toHaveLength(0);
    expect(mockTrackTeamPageViewed).not.toHaveBeenCalled();
  });
});
