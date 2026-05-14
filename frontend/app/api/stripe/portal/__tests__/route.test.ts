import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockGetUser, mockFrom, mockPortalSessionsCreate } = vi.hoisted(() => ({
  mockGetUser: vi.fn(),
  mockFrom: vi.fn(),
  mockPortalSessionsCreate: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn().mockResolvedValue({
    getAll: vi.fn().mockReturnValue([]),
    set: vi.fn(),
  }),
}));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: vi.fn().mockResolvedValue({
    auth: { getUser: mockGetUser },
    from: mockFrom,
  }),
}));

vi.mock('@/lib/stripe/server', () => ({
  stripe: {
    billingPortal: { sessions: { create: mockPortalSessionsCreate } },
  },
}));

import { POST } from '../route';

/**
 * Build a chainable supabase mock that records the filter args (column/value)
 * so tests can assert the lookup is keyed correctly. Returns the supabase-shaped
 * `client` for use with `mockFrom.mockReturnValue(...)`, plus the underlying
 * spies for assertions.
 */
function profileChain(final: { data?: unknown; error?: unknown }) {
  const single = vi.fn().mockResolvedValue(final);
  const eq = vi.fn(() => ({ single }));
  const select = vi.fn(() => ({ eq }));
  return { client: { select }, select, eq, single };
}

describe('POST /api/stripe/portal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.NEXT_PUBLIC_SITE_URL = 'https://pitchrank.io';
  });

  it('returns 401 when not authenticated', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });

    const res = await POST();

    expect(res.status).toBe(401);
  });

  it('returns 400 when profile has no stripe_customer_id', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null });
    const chain = profileChain({ data: { stripe_customer_id: null }, error: null });
    mockFrom.mockReturnValue(chain.client);

    const res = await POST();

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'No billing account found' });
  });

  it('returns 400 when profile lookup errors', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null });
    const chain = profileChain({ data: null, error: { message: 'boom' } });
    mockFrom.mockReturnValue(chain.client);

    const res = await POST();

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'No billing account found' });
  });

  it('keys the portal session off the user own stripe_customer_id', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null });
    const chain = profileChain({ data: { stripe_customer_id: 'cus_user-1' }, error: null });
    mockFrom.mockReturnValue(chain.client);
    mockPortalSessionsCreate.mockResolvedValue({ url: 'https://billing.stripe.com/session/abc' });

    const res = await POST();

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ url: 'https://billing.stripe.com/session/abc' });

    // Critical regression guard: the customer passed to Stripe MUST be the one we
    // looked up by `user.id` — never a value derived from request body or any
    // other column. Wrong table, wrong filter column, or wrong filter value here
    // = billing-account leak (returning another user's portal session).
    expect(mockFrom).toHaveBeenCalledWith('user_profiles');
    expect(chain.select).toHaveBeenCalledWith('stripe_customer_id');
    expect(chain.eq).toHaveBeenCalledWith('id', 'user-1');
    expect(mockPortalSessionsCreate).toHaveBeenCalledWith({
      customer: 'cus_user-1',
      return_url: 'https://pitchrank.io/watchlist',
    });
  });

  it('returns 500 on Stripe error without leaking details', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null });
    const chain = profileChain({ data: { stripe_customer_id: 'cus_user-1' }, error: null });
    mockFrom.mockReturnValue(chain.client);
    mockPortalSessionsCreate.mockRejectedValue(new Error('Stripe is down: req_xyz'));

    const res = await POST();

    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body.error).toBe('Failed to create portal session');
  });
});
