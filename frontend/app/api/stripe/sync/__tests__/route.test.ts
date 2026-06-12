import { describe, it, expect, vi, beforeEach } from 'vitest';

// Hoisted mock fns so they're available inside vi.mock factories
const {
  mockGetUser,
  mockServerFrom,
  mockAdminFrom,
  mockSessionsRetrieve,
  mockSubscriptionsRetrieve,
  mockCheckRateLimit,
} = vi.hoisted(() => ({
  mockGetUser: vi.fn(),
  mockServerFrom: vi.fn(),
  mockAdminFrom: vi.fn(),
  mockSessionsRetrieve: vi.fn(),
  mockSubscriptionsRetrieve: vi.fn(),
  mockCheckRateLimit: vi.fn(() => true),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn().mockResolvedValue({
    getAll: vi.fn().mockReturnValue([]),
    set: vi.fn(),
  }),
}));

vi.mock('@/lib/api/rateLimit', () => ({
  checkRateLimit: mockCheckRateLimit,
  getClientIp: vi.fn(() => '203.0.113.1'),
}));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: vi.fn().mockResolvedValue({
    auth: { getUser: mockGetUser },
    from: mockServerFrom,
  }),
}));

vi.mock('@/lib/supabase/service', () => ({
  getSupabaseAdmin: vi.fn(() => ({ from: mockAdminFrom })),
}));

vi.mock('@/lib/stripe/server', () => ({
  stripe: {
    checkout: { sessions: { retrieve: mockSessionsRetrieve } },
    subscriptions: { retrieve: mockSubscriptionsRetrieve },
  },
  extractPeriodEnd: vi.fn(() => '2026-12-31T00:00:00.000Z'),
  mapStatusToPlan: vi.fn((status: string) => (status === 'active' ? 'premium' : 'free')),
  isSessionPaymentSettled: (s: { payment_status?: string }) =>
    s.payment_status === 'paid' || s.payment_status === 'no_payment_required',
}));

import { POST } from '../route';

function makeRequest(body: unknown): Request {
  return new Request('http://localhost/api/stripe/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * Build a retrieved Stripe checkout session for the happy path
 * (complete + paid + active subscription). Override any field per test.
 */
function makeSession(overrides: Record<string, unknown> = {}) {
  return {
    status: 'complete',
    payment_status: 'paid',
    customer: 'cus_123',
    subscription: { id: 'sub_1', status: 'active', cancel_at_period_end: false },
    ...overrides,
  };
}

/**
 * Build a chainable supabase SELECT mock that records the filter args
 * (column/value pair) so tests can assert the lookup is keyed correctly.
 * Returns the supabase-shaped `client` plus the underlying spies.
 *
 * Supports both `.single()` and `.maybeSingle()` terminators.
 */
function selectChain(final: { data?: unknown; error?: unknown }) {
  const single = vi.fn().mockResolvedValue(final);
  const maybeSingle = vi.fn().mockResolvedValue(final);
  const eq = vi.fn(() => ({ single, maybeSingle }));
  const select = vi.fn(() => ({ eq }));
  return { client: { select }, select, eq, single, maybeSingle };
}

/**
 * Build a chainable supabase UPDATE mock that records the filter args.
 * The route pattern is `.from(table).update(updates).eq(column, value)`.
 */
function updateChain(final: { error?: unknown } = { error: null }) {
  const eq = vi.fn().mockResolvedValue(final);
  const update = vi.fn(() => ({ eq }));
  return { client: { update }, update, eq };
}

describe('POST /api/stripe/sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockReturnValue(true);
  });

  it('returns 400 when sessionId is missing', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });

    const res = await POST(makeRequest({}));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'Missing session_id' });
  });

  it('returns 400 when sessionId is not a string', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });

    const res = await POST(makeRequest({ sessionId: 123 }));

    expect(res.status).toBe(400);
  });

  it('returns 400 when session has no subscription', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockResolvedValue(makeSession({ subscription: null }));

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'Session has no subscription' });
  });

  it('authenticated: returns 403 when session metadata user does not match', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue(makeSession({ metadata: { supabase_user_id: 'user-attacker' } }));

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: 'Session does not belong to you' });
  });

  it('authenticated: returns 403 when no metadata and customer_id mismatch on profile', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue(makeSession({ customer: 'cus_attacker', metadata: {} }));
    const chain = selectChain({ data: { stripe_customer_id: 'cus_real' }, error: null });
    mockServerFrom.mockReturnValue(chain.client);

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: 'Session does not belong to you' });

    // Ownership check must look up the profile by user.id, never by anything
    // attacker-controlled. Wrong filter column here = anyone can claim any
    // checkout session.
    expect(mockServerFrom).toHaveBeenCalledWith('user_profiles');
    expect(chain.eq).toHaveBeenCalledWith('id', 'user-real');
  });

  it('authenticated: returns 403 when profile has no customer_id (cannot verify)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue(makeSession({ metadata: {} }));
    const chain = selectChain({ data: { stripe_customer_id: null }, error: null });
    mockServerFrom.mockReturnValue(chain.client);

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toMatch(/cannot verify/i);
    expect(chain.eq).toHaveBeenCalledWith('id', 'user-real');
  });

  it('authenticated: syncs profile by user.id when metadata matches', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue(makeSession({ metadata: { supabase_user_id: 'user-real' } }));
    // Metadata path also cross-checks the stored customer ID
    const profileChain = selectChain({ data: { stripe_customer_id: 'cus_123' }, error: null });
    mockServerFrom.mockReturnValue(profileChain.client);
    const update = updateChain({ error: null });
    mockAdminFrom.mockReturnValue(update.client);

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ synced: true, plan: 'premium', status: 'active' });

    // Critical: must update the profile keyed by user.id from the verified
    // session, never by stripe_customer_id directly (otherwise a forged session
    // pointing at another user's customer_id would mutate that user's row).
    // The write goes through the admin client — API roles have no UPDATE
    // privilege on user_profiles since the P0 lockdown.
    expect(mockAdminFrom).toHaveBeenCalledWith('user_profiles');
    expect(update.eq).toHaveBeenCalledWith('id', 'user-real');
  });

  it('anonymous: returns 202 when no profile exists yet (webhook pending)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockResolvedValue(makeSession({ customer: 'cus_anon' }));
    const chain = selectChain({ data: null, error: null });
    mockAdminFrom.mockReturnValue(chain.client);

    const res = await POST(makeRequest({ sessionId: 'cs_test_anon' }));

    expect(res.status).toBe(202);
    const body = await res.json();
    expect(body).toMatchObject({ synced: false });

    // Anonymous-path lookup MUST be keyed by stripe_customer_id from the
    // verified Stripe session, never by anything client-supplied. Wrong column
    // here = account-linking regression (e.g., looking up by email could
    // attach a payment to the wrong account).
    expect(mockAdminFrom).toHaveBeenCalledWith('user_profiles');
    expect(chain.eq).toHaveBeenCalledWith('stripe_customer_id', 'cus_anon');
  });

  it('anonymous: syncs by stripe_customer_id when profile exists', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockResolvedValue(makeSession({ customer: 'cus_anon' }));
    const lookup = selectChain({ data: { id: 'profile-99' }, error: null });
    const update = updateChain({ error: null });
    mockAdminFrom
      .mockReturnValueOnce(lookup.client) // first call: SELECT to find profile
      .mockReturnValueOnce(update.client); // second call: UPDATE that profile

    const res = await POST(makeRequest({ sessionId: 'cs_test_anon' }));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ synced: true, plan: 'premium', status: 'active' });

    // Lookup keyed by stripe_customer_id from Stripe (not client input).
    expect(lookup.eq).toHaveBeenCalledWith('stripe_customer_id', 'cus_anon');
    // Then update by the resolved profile.id — NOT by stripe_customer_id again
    // (which would update any row sharing that customer_id, not just this profile).
    expect(update.eq).toHaveBeenCalledWith('id', 'profile-99');
  });

  it('returns 500 on unexpected Stripe error', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockRejectedValue(new Error('Stripe down'));

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(500);
  });

  it('returns 400 when the checkout session is not complete', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockResolvedValueOnce(makeSession({ status: 'open', payment_status: 'unpaid' }));

    const res = await POST(makeRequest({ sessionId: 'cs_test_open' }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/not complete/i);
  });

  it('returns 202 when payment is still processing (async method)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockResolvedValueOnce(makeSession({ payment_status: 'unpaid' }));

    const res = await POST(makeRequest({ sessionId: 'cs_test_unpaid' }));

    expect(res.status).toBe(202);
    expect(await res.json()).toMatchObject({ synced: false });
  });

  it('authenticated: returns 403 when metadata matches but stored customer differs', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValueOnce(
      makeSession({ customer: 'cus_other', metadata: { supabase_user_id: 'user-real' } })
    );
    // Profile already linked to a different Stripe customer — must not be re-pointed
    const profileChain = selectChain({ data: { stripe_customer_id: 'cus_real' }, error: null });
    mockServerFrom.mockReturnValue(profileChain.client);

    const res = await POST(makeRequest({ sessionId: 'cs_test_mismatch' }));

    expect(res.status).toBe(403);
    expect((await res.json()).error).toMatch(/billing profile/i);
    expect(mockAdminFrom).not.toHaveBeenCalled();
  });

  it('anonymous: trial checkout (no_payment_required) passes the paid guard and syncs', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    // A trial checkout settles with payment_status 'no_payment_required' — the
    // guard must treat it like 'paid' so trials can sync, not reject as unpaid.
    mockSessionsRetrieve.mockResolvedValueOnce(
      makeSession({ customer: 'cus_anon', payment_status: 'no_payment_required' })
    );
    const lookup = selectChain({ data: { id: 'profile-99' }, error: null });
    const update = updateChain({ error: null });
    mockAdminFrom
      .mockReturnValueOnce(lookup.client) // SELECT to find profile by customer
      .mockReturnValueOnce(update.client); // UPDATE that profile

    const res = await POST(makeRequest({ sessionId: 'cs_test_trial' }));

    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ synced: true });
    expect(lookup.eq).toHaveBeenCalledWith('stripe_customer_id', 'cus_anon');
    expect(update.eq).toHaveBeenCalledWith('id', 'profile-99');
  });

  it('returns 429 when the rate limiter denies', async () => {
    mockCheckRateLimit.mockReturnValue(false);

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(429);
  });

  it('returns 500 when the billing-profile verification lookup fails', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue(makeSession({ metadata: { supabase_user_id: 'user-real' } }));
    // The ownership-verification lookup errors — fail closed (writing without
    // completing verification would reopen the de-link hole).
    const chain = selectChain({ data: null, error: { message: 'boom' } });
    mockServerFrom.mockReturnValue(chain.client);

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(500);
    // Must never reach the admin write when verification couldn't complete.
    expect(mockAdminFrom).not.toHaveBeenCalled();
  });
});
