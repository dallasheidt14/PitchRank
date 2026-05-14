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

function profileChain(final: { data?: unknown; error?: unknown }) {
  const single = vi.fn().mockResolvedValue(final);
  const eq = vi.fn(() => ({ single }));
  const select = vi.fn(() => ({ eq }));
  return { select };
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
    mockFrom.mockReturnValue(profileChain({ data: { stripe_customer_id: null }, error: null }));

    const res = await POST();

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'No billing account found' });
  });

  it('returns 400 when profile lookup errors', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null });
    mockFrom.mockReturnValue(profileChain({ data: null, error: { message: 'boom' } }));

    const res = await POST();

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'No billing account found' });
  });

  it('keys the portal session off the user own stripe_customer_id', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null });
    mockFrom.mockReturnValue(profileChain({ data: { stripe_customer_id: 'cus_user-1' }, error: null }));
    mockPortalSessionsCreate.mockResolvedValue({ url: 'https://billing.stripe.com/session/abc' });

    const res = await POST();

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ url: 'https://billing.stripe.com/session/abc' });
    // Critical regression guard: the customer passed to Stripe MUST be the one we
    // looked up by user.id — never a value derived from request body. Wrong filter
    // here = billing-account leak.
    expect(mockPortalSessionsCreate).toHaveBeenCalledWith({
      customer: 'cus_user-1',
      return_url: 'https://pitchrank.io/watchlist',
    });
  });

  it('returns 500 on Stripe error without leaking details', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } }, error: null });
    mockFrom.mockReturnValue(profileChain({ data: { stripe_customer_id: 'cus_user-1' }, error: null }));
    mockPortalSessionsCreate.mockRejectedValue(new Error('Stripe is down: req_xyz'));

    const res = await POST();

    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body.error).toBe('Failed to create portal session');
  });
});
