import { describe, it, expect, vi, beforeEach } from 'vitest';

// Hoisted mock fns so they're available inside vi.mock factories
const { mockGetUser, mockServerFrom, mockAdminFrom, mockSessionsRetrieve, mockSubscriptionsRetrieve } = vi.hoisted(
  () => ({
    mockGetUser: vi.fn(),
    mockServerFrom: vi.fn(),
    mockAdminFrom: vi.fn(),
    mockSessionsRetrieve: vi.fn(),
    mockSubscriptionsRetrieve: vi.fn(),
  })
);

vi.mock('next/headers', () => ({
  cookies: vi.fn().mockResolvedValue({
    getAll: vi.fn().mockReturnValue([]),
    set: vi.fn(),
  }),
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
}));

import { POST } from '../route';

function makeRequest(body: unknown): Request {
  return new Request('http://localhost/api/stripe/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// Helper to build a chainable supabase query mock that returns the given final value
function chain(final: { data?: unknown; error?: unknown }) {
  const single = vi.fn().mockResolvedValue(final);
  const maybeSingle = vi.fn().mockResolvedValue(final);
  const eq2 = vi.fn(() => ({ single, maybeSingle }));
  const eq1 = vi.fn(() => ({ single, maybeSingle, eq: eq2 }));
  const select = vi.fn(() => ({ eq: eq1 }));
  const update = vi.fn(() => ({ eq: vi.fn().mockResolvedValue(final) }));
  return { select, update, eq: eq1 };
}

describe('POST /api/stripe/sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    mockSessionsRetrieve.mockResolvedValue({ customer: 'cus_123', subscription: null });

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'Session has no subscription' });
  });

  it('authenticated: returns 403 when session metadata user does not match', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue({
      customer: 'cus_123',
      subscription: { id: 'sub_1', status: 'active', cancel_at_period_end: false },
      metadata: { supabase_user_id: 'user-attacker' },
    });

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: 'Session does not belong to you' });
  });

  it('authenticated: returns 403 when no metadata and customer_id mismatch on profile', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue({
      customer: 'cus_attacker',
      subscription: { id: 'sub_1', status: 'active', cancel_at_period_end: false },
      metadata: {},
    });
    mockServerFrom.mockReturnValue(chain({ data: { stripe_customer_id: 'cus_real' }, error: null }));

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: 'Session does not belong to you' });
  });

  it('authenticated: returns 403 when profile has no customer_id (cannot verify)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue({
      customer: 'cus_123',
      subscription: { id: 'sub_1', status: 'active', cancel_at_period_end: false },
      metadata: {},
    });
    mockServerFrom.mockReturnValue(chain({ data: { stripe_customer_id: null }, error: null }));

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(403);
    const body = await res.json();
    expect(body.error).toMatch(/cannot verify/i);
  });

  it('authenticated: syncs profile by user.id when metadata matches', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-real' } } });
    mockSessionsRetrieve.mockResolvedValue({
      customer: 'cus_123',
      subscription: { id: 'sub_1', status: 'active', cancel_at_period_end: false },
      metadata: { supabase_user_id: 'user-real' },
    });
    const updateEq = vi.fn().mockResolvedValue({ error: null });
    mockServerFrom.mockReturnValue({ update: vi.fn(() => ({ eq: updateEq })) });

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ synced: true, plan: 'premium', status: 'active' });
    expect(updateEq).toHaveBeenCalledWith('id', 'user-real');
  });

  it('anonymous: returns 202 when no profile exists yet (webhook pending)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockResolvedValue({
      customer: 'cus_anon',
      subscription: { id: 'sub_1', status: 'active', cancel_at_period_end: false },
    });
    mockAdminFrom.mockReturnValue(chain({ data: null, error: null }));

    const res = await POST(makeRequest({ sessionId: 'cs_test_anon' }));

    expect(res.status).toBe(202);
    const body = await res.json();
    expect(body).toMatchObject({ synced: false });
  });

  it('anonymous: syncs by stripe_customer_id when profile exists', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockResolvedValue({
      customer: 'cus_anon',
      subscription: { id: 'sub_1', status: 'active', cancel_at_period_end: false },
    });
    // First call (lookup) returns profile; second call (update) returns success
    const updateEq = vi.fn().mockResolvedValue({ error: null });
    const lookupChain = chain({ data: { id: 'profile-99' }, error: null });
    mockAdminFrom.mockReturnValueOnce(lookupChain).mockReturnValueOnce({ update: vi.fn(() => ({ eq: updateEq })) });

    const res = await POST(makeRequest({ sessionId: 'cs_test_anon' }));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ synced: true, plan: 'premium', status: 'active' });
    expect(updateEq).toHaveBeenCalledWith('id', 'profile-99');
  });

  it('returns 500 on unexpected Stripe error', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockSessionsRetrieve.mockRejectedValue(new Error('Stripe down'));

    const res = await POST(makeRequest({ sessionId: 'cs_test_abc' }));

    expect(res.status).toBe(500);
  });
});
