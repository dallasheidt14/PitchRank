import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { UserProfile } from './useUser';

type SingleResult = { data: unknown; error: { code?: string; message: string } | null };

let singleResults: SingleResult[] = [];
let singleCalls = 0;
let authCallback: ((event: string, session: unknown) => Promise<void>) | null = null;

// Both stubs are created once. useRouter and createClientSupabase are effect
// dependencies of useUser, so a stub that returns a fresh object per render would
// re-run initialization forever — the real implementations are stable.
vi.mock('next/navigation', () => {
  const router = { push: vi.fn(), refresh: vi.fn() };
  return { useRouter: () => router };
});

vi.mock('@/lib/supabase/client', () => {
  const client = {
    auth: {
      getSession: async () => ({ data: { session: { user: { id: 'user-1' } } }, error: null }),
      getUser: async () => ({ data: { user: { id: 'user-1' } }, error: null }),
      onAuthStateChange: (cb: (event: string, session: unknown) => Promise<void>) => {
        authCallback = cb;
        return { data: { subscription: { unsubscribe: () => {} } } };
      },
    },
    from: () => ({
      select: () => ({
        eq: () => ({
          single: async () => singleResults[Math.min(singleCalls++, singleResults.length - 1)],
        }),
      }),
    }),
  };
  return { createClientSupabase: () => client };
});

import { hasPremiumAccess, useUser } from './useUser';

const PREMIUM_PROFILE: UserProfile = {
  id: 'user-1',
  email: 'premium@example.com',
  plan: 'premium',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  stripe_customer_id: 'cus_test',
  stripe_subscription_id: 'sub_test',
  subscription_status: 'active',
  subscription_period_end: '2027-01-01T00:00:00Z',
  cancel_at_period_end: false,
};

const ok = (profile: UserProfile): SingleResult => ({ data: profile, error: null });
const transientFailure = (): SingleResult => ({ data: null, error: { message: 'network error' } });
const noRow = (): SingleResult => ({ data: null, error: { code: 'PGRST116', message: 'no rows' } });

function queue(results: SingleResult[]) {
  singleResults = results;
  singleCalls = 0;
}

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function Probe() {
  const { profile, error } = useUser();
  return React.createElement(
    'div',
    null,
    `plan:${profile?.plan ?? 'none'}|premium:${hasPremiumAccess(profile)}|error:${error ? 'yes' : 'no'}`
  );
}

async function render() {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(React.createElement(Probe));
  });
}

const readout = () => container!.textContent ?? '';

// useUser backs off 300ms then 600ms between its three attempts; wait past that
// so assertions see the settled result rather than a retry still in flight.
async function settleRetries() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 1100));
  });
}

beforeEach(() => {
  authCallback = null;
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe('useUser profile loading', () => {
  it('recovers a premium plan when the first profile fetch fails transiently', async () => {
    queue([transientFailure(), ok(PREMIUM_PROFILE)]);

    await render();
    await settleRetries();

    expect(readout()).toContain('plan:premium');
    expect(readout()).toContain('premium:true');
    expect(singleCalls).toBe(2);
  });

  it('does not retry when the profile genuinely does not exist', async () => {
    queue([noRow()]);

    await render();

    expect(readout()).toContain('plan:none');
    expect(readout()).toContain('error:no');
    expect(singleCalls).toBe(1);
  });

  it('reports an error rather than a free plan when every attempt fails', async () => {
    queue([transientFailure()]);

    await render();
    await settleRetries();

    expect(singleCalls).toBe(3);
    expect(readout()).toContain('error:yes');
  });

  it('keeps an established premium plan when a later refetch fails', async () => {
    queue([ok(PREMIUM_PROFILE)]);
    await render();
    expect(readout()).toContain('premium:true');

    queue([transientFailure()]);
    await act(async () => {
      await authCallback!('TOKEN_REFRESHED', { user: { id: 'user-1' } });
    });
    await settleRetries();

    expect(readout()).toContain('plan:premium');
    expect(readout()).toContain('premium:true');
  });
});
