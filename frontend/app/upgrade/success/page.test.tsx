import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { mockConfetti } = vi.hoisted(() => ({
  mockConfetti: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams({ session_id: 'cs_test_paid' }),
}));
vi.mock('@/hooks/useUser', () => ({ useUser: () => ({ user: null, isLoading: false }) }));
vi.mock('@/components/ui/confetti', () => ({ launchConfetti: mockConfetti }));

import UpgradeSuccessPage from './page';

let container: HTMLDivElement;
let root: Root;

async function renderWithFetch(fetchImpl: () => Promise<unknown>) {
  vi.stubGlobal('fetch', vi.fn(fetchImpl));
  await act(async () => {
    root.render(<UpgradeSuccessPage />);
  });
}

function renderWithSyncResponse(body: Record<string, unknown>) {
  return renderWithFetch(() => Promise.resolve({ json: () => Promise.resolve(body) }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  window.history.replaceState(null, '', '/upgrade/success?session_id=cs_test_paid');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('UpgradeSuccessPage', () => {
  it('removes the session id from the address bar and still syncs with it', async () => {
    await renderWithSyncResponse({ synced: true });

    expect(window.location.pathname + window.location.search).toBe('/upgrade/success');
    const [, request] = vi.mocked(fetch).mock.calls[0];
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
});
