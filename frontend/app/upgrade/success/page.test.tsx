import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const TEAM_PATH = '/teams/11111111-1111-1111-1111-111111111111';

const { mockConfetti, state } = vi.hoisted(() => ({
  mockConfetti: vi.fn(),
  state: { query: { session_id: 'cs_test_paid' } as Record<string, string> },
}));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(state.query),
}));
vi.mock('@/hooks/useUser', () => ({ useUser: () => ({ user: null, isLoading: false }) }));
vi.mock('@/components/ui/confetti', () => ({ launchConfetti: mockConfetti }));

import UpgradeSuccessPage from './page';

let container: HTMLDivElement;
let root: Root;

async function renderWithFetch(fetchImpl: (url: string) => Promise<unknown>) {
  vi.stubGlobal('fetch', vi.fn(fetchImpl));
  await act(async () => {
    root.render(<UpgradeSuccessPage />);
  });
}

const respondWith = (body: Record<string, unknown>) => Promise.resolve({ json: () => Promise.resolve(body) });

function renderWithSyncResponse(body: Record<string, unknown>) {
  return renderWithFetch((url) => respondWith(url === '/api/stripe/sync' ? body : { status: 'email' }));
}

function renderWithLoginResponses(...bodies: Array<Record<string, unknown>>) {
  return renderWithFetch((url) =>
    url === '/api/stripe/sync' ? respondWith({ synced: true }) : respondWith(bodies.shift() ?? { status: 'email' })
  );
}

function loginCalls() {
  return vi.mocked(fetch).mock.calls.filter(([url]) => url === '/api/stripe/checkout-login');
}

const pageText = () => container.textContent ?? '';

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  state.query = { session_id: 'cs_test_paid' };
  window.history.replaceState(null, '', '/upgrade/success?session_id=cs_test_paid');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('UpgradeSuccessPage', () => {
  it('removes the session id from the address bar and still syncs with it', async () => {
    await renderWithSyncResponse({ synced: true });

    expect(window.location.pathname + window.location.search).toBe('/upgrade/success');
    const [url, request] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe('/api/stripe/sync');
    expect(request?.body).toBe(JSON.stringify({ sessionId: 'cs_test_paid' }));
  });

  it('removes the session id even when the sync request fails', async () => {
    await renderWithFetch(() => Promise.reject(new Error('offline')));

    expect(window.location.search).toBe('');
  });

  it('celebrates a synced subscription', async () => {
    await renderWithSyncResponse({ synced: true, plan: 'premium', status: 'trialing' });

    expect(mockConfetti).toHaveBeenCalledTimes(1);
  });

  it('does not celebrate a checkout whose payment has not settled', async () => {
    await renderWithSyncResponse({ synced: false, error: 'Payment still processing' });

    expect(mockConfetti).not.toHaveBeenCalled();
  });

  describe('signing the buyer in', () => {
    it('sends the session id after the sync, then opens the team with a full page load', async () => {
      const replace = vi.fn();
      vi.stubGlobal('location', { ...window.location, replace });

      await renderWithLoginResponses({ status: 'signed_in', next: TEAM_PATH });

      const urls = vi.mocked(fetch).mock.calls.map(([url]) => url);
      expect(urls).toEqual(['/api/stripe/sync', '/api/stripe/checkout-login']);
      expect(loginCalls()[0][1]?.body).toBe(JSON.stringify({ sessionId: 'cs_test_paid' }));
      expect(replace).toHaveBeenCalledWith(TEAM_PATH);
      expect(pageText()).toContain('Setting up your account...');
    });

    it('still tries to sign in when the sync request fails', async () => {
      const replace = vi.fn();
      vi.stubGlobal('location', { ...window.location, replace });

      await renderWithFetch((url) =>
        url === '/api/stripe/sync'
          ? Promise.reject(new Error('offline'))
          : respondWith({ status: 'signed_in', next: TEAM_PATH })
      );

      expect(replace).toHaveBeenCalledWith(TEAM_PATH);
    });

    it('retries a pending account at 1, 2, 3 and 4 seconds, holding back the email box until the end', async () => {
      vi.useFakeTimers();
      await renderWithLoginResponses(...Array.from({ length: 5 }, () => ({ status: 'pending' })));
      expect(loginCalls()).toHaveLength(1);

      for (const [delay, attempts] of [
        [999, 1],
        [1, 2],
        [2000, 3],
        [3000, 4],
      ]) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(delay);
        });
        expect(loginCalls()).toHaveLength(attempts);
        expect(pageText()).toContain('Setting up your account...');
        expect(pageText()).not.toContain('Check your email');
        expect(pageText()).not.toContain('You now have access to:');
      }

      await act(async () => {
        await vi.advanceTimersByTimeAsync(4000);
      });
      expect(loginCalls()).toHaveLength(5);
      expect(pageText()).toContain('Check your email');
      expect(pageText()).not.toContain('Setting up your account...');
    });

    it('stops retrying once the account appears', async () => {
      const replace = vi.fn();
      vi.stubGlobal('location', { ...window.location, replace });
      vi.useFakeTimers();

      await renderWithLoginResponses({ status: 'pending' }, { status: 'signed_in', next: TEAM_PATH });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });

      expect(loginCalls()).toHaveLength(2);
      expect(replace).toHaveBeenCalledWith(TEAM_PATH);
    });

    it('shows the email box straight away when the route says to use it', async () => {
      await renderWithLoginResponses({ status: 'email' });

      expect(loginCalls()).toHaveLength(1);
      expect(pageText()).toContain('Check your email');
    });

    it('shows the email box when the sign-in request fails', async () => {
      await renderWithFetch((url) =>
        url === '/api/stripe/sync' ? respondWith({ synced: true }) : Promise.reject(new Error('offline'))
      );

      expect(pageText()).toContain('Check your email');
      expect(pageText()).not.toContain('Setting up your account...');
    });

    it('asks for nothing on a visit with no session id', async () => {
      state.query = {};

      await renderWithFetch(() => respondWith({}));

      expect(fetch).not.toHaveBeenCalled();
      expect(pageText()).not.toContain('Setting up your account...');
      expect(pageText()).toContain('Check your email');
    });
  });
});
