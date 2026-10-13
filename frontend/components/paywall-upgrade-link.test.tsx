import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { act } from 'react-dom/test-utils';

const { mockTrackClick, mockTrackImpression } = vi.hoisted(() => ({
  mockTrackClick: vi.fn(),
  mockTrackImpression: vi.fn(),
}));

vi.mock('@/hooks/useUser', () => ({
  useUser: () => ({ profile: null, isLoading: false }),
  hasPremiumAccess: () => false,
}));
vi.mock('@/lib/events', () => ({
  trackPaywallUpgradeClicked: mockTrackClick,
  trackPaywallImpression: mockTrackImpression,
}));

import { ClutchFactorCard } from '@/components/ClutchFactorCard';
import { TeamInsightsCard } from '@/components/TeamInsightsCard';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // Stop happy-dom following the href; React's own handlers have already run by now.
  container.addEventListener('click', (e) => e.preventDefault());
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe.each([
  ['clutch_factor', ClutchFactorCard],
  ['team_insights', TeamInsightsCard],
] as const)('%s paywall upgrade link', (feature, Component) => {
  it('is one link styled as a button, and records the click', () => {
    act(() => root.render(<Component teamId={TEAM_ID} />));

    const links = [...container.querySelectorAll('a')].filter((a) => a.textContent?.includes('Upgrade to Unlock'));
    expect(links).toHaveLength(1);
    const link = links[0];
    expect(link.getAttribute('href')).toBe(`/upgrade?source=${feature}&team=${TEAM_ID}`);
    expect(link.getAttribute('data-slot')).toBe('button');
    expect(link.querySelector('button')).toBeNull();
    expect(link.closest('button')).toBeNull();

    act(() => link.click());

    expect(mockTrackClick).toHaveBeenCalledTimes(1);
    expect(mockTrackClick).toHaveBeenCalledWith({ feature, location: 'team_detail_page', team_id: TEAM_ID });
  });
});
