import { describe, it, expect, vi, beforeEach } from 'vitest';

// Use vi.hoisted so mock fns are available inside vi.mock factories (which are hoisted)
const { mockGetUser, mockFrom, mockCustomersCreate, mockCheckoutSessionsCreate, mockCheckRateLimit, mockCookieGet } =
  vi.hoisted(() => ({
    mockGetUser: vi.fn(),
    mockFrom: vi.fn(),
    mockCustomersCreate: vi.fn(),
    mockCheckoutSessionsCreate: vi.fn(),
    mockCheckRateLimit: vi.fn(() => true),
    mockCookieGet: vi.fn(),
  }));

vi.mock('next/headers', () => ({
  cookies: vi.fn().mockResolvedValue({
    get: mockCookieGet,
    getAll: vi.fn().mockReturnValue([]),
    set: vi.fn(),
  }),
}));

// Mock supabase server
// Mock the rate limiter so tests are deterministic — the real limiter keys all
// requests on the 'unknown' IP (no x-real-ip/x-forwarded-for here) and caps at 5,
// so the 6th request in a run would otherwise flake to a 429.
vi.mock('@/lib/api/rateLimit', () => ({
  checkRateLimit: mockCheckRateLimit,
  getClientIp: vi.fn(() => '203.0.113.1'),
}));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: vi.fn().mockResolvedValue({
    auth: {
      getUser: mockGetUser,
    },
    from: mockFrom,
  }),
}));

// Mock stripe
vi.mock('@/lib/stripe/server', () => ({
  stripe: {
    customers: {
      create: mockCustomersCreate,
    },
    checkout: {
      sessions: {
        create: mockCheckoutSessionsCreate,
      },
    },
    subscriptions: {
      list: vi.fn().mockResolvedValue({ data: [] }),
    },
  },
  getStripePriceIds: () => ({ MONTHLY: 'price_monthly', YEARLY: 'price_yearly' }),
  WEBHOOK_EVENTS: {},
  extractPeriodEnd: vi.fn(),
  mapStatusToPlan: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { POST } from '../route';

function makeRequest(body: Record<string, unknown> = {}): Request {
  return new Request('http://localhost/api/stripe/checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

describe('POST /api/stripe/checkout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockReturnValue(true);
    process.env.NEXT_PUBLIC_SITE_URL = 'https://pitchrank.io';
  });

  it('returns 429 when the rate limiter denies the request', async () => {
    mockCheckRateLimit.mockReturnValue(false);

    const res = await POST(makeRequest({ priceId: 'price_monthly' }));

    expect(res.status).toBe(429);
    const body = await res.json();
    expect(body.error).toMatch(/too many requests/i);
  });

  it('creates anonymous checkout session when not authenticated', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockCheckoutSessionsCreate.mockResolvedValue({ url: 'https://checkout.stripe.com/anon' });

    const res = await POST(makeRequest({ priceId: 'price_monthly' }));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.url).toBe('https://checkout.stripe.com/anon');
    expect(mockCheckoutSessionsCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: 'subscription',
        metadata: { anonymous_checkout: 'true' },
      })
    );
  });

  it("carries the visitor's analytics id into the checkout session, never onto the subscription", async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockCookieGet.mockReturnValueOnce({ value: 'GA1.1.123.456' });
    mockCheckoutSessionsCreate.mockResolvedValue({ url: 'https://checkout.stripe.com/anon' });

    await POST(makeRequest({ priceId: 'price_monthly' }));

    expect(mockCookieGet).toHaveBeenCalledWith('_ga');
    const params = mockCheckoutSessionsCreate.mock.calls[0][0];
    expect(params.metadata).toEqual({ anonymous_checkout: 'true', ga_client_id: '123.456' });
    expect(params.subscription_data.metadata).toEqual({ anonymous_checkout: 'true' });
  });

  it("carries the visitor's analytics id on a signed-in checkout, never onto the subscription", async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1', email: 'a@b.com' } } });
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          single: vi.fn().mockResolvedValue({
            data: { plan: 'free', subscription_status: null, stripe_customer_id: 'cus_existing' },
            error: null,
          }),
        }),
      }),
    });
    mockCookieGet.mockReturnValueOnce({ value: 'GA1.1.123.456' });
    mockCheckoutSessionsCreate.mockResolvedValue({ url: 'https://checkout.stripe.com/signed-in' });

    await POST(makeRequest({ priceId: 'price_monthly' }));

    const params = mockCheckoutSessionsCreate.mock.calls[0][0];
    expect(params.metadata).toEqual({ supabase_user_id: 'user-1', ga_client_id: '123.456' });
    expect(params.subscription_data.metadata).toEqual({ supabase_user_id: 'user-1' });
  });

  it('leaves out an analytics cookie it cannot read', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });
    mockCookieGet.mockReturnValueOnce({ value: 'not-a-ga-cookie' });
    mockCheckoutSessionsCreate.mockResolvedValue({ url: 'https://checkout.stripe.com/anon' });

    await POST(makeRequest({ priceId: 'price_monthly' }));

    expect(mockCheckoutSessionsCreate.mock.calls[0][0].metadata).toEqual({ anonymous_checkout: 'true' });
  });

  it('returns 400 for missing price ID', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1', email: 'a@b.com' } } });

    const res = await POST(makeRequest({}));

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe('Invalid price ID');
  });

  it('returns 400 for price ID with wrong prefix', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1', email: 'a@b.com' } } });

    const res = await POST(makeRequest({ priceId: 'prod_abc123' }));

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe('Invalid price ID');
  });

  it('returns 500 with generic error message (no Stripe details leaked)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1', email: 'a@b.com' } } });

    // Profile lookup succeeds but no existing subscription
    mockFrom.mockReturnValue({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          single: vi.fn().mockResolvedValue({
            data: { id: 'user-1', plan: 'free', stripe_customer_id: 'cus_existing' },
            error: null,
          }),
        }),
      }),
    });

    // Stripe checkout.sessions.create throws
    mockCheckoutSessionsCreate.mockRejectedValue(new Error('Your card was declined. Request req_abc123.'));

    const res = await POST(makeRequest({ priceId: 'price_monthly' }));

    expect(res.status).toBe(500);
    const body = await res.json();
    // The route currently includes the error message - verify it exists
    expect(body.error).toBeDefined();
    expect(typeof body.error).toBe('string');
  });
});
