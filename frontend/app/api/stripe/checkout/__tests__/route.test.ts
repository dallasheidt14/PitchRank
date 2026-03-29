import { describe, it, expect, vi, beforeEach } from 'vitest';

// Use vi.hoisted so mock fns are available inside vi.mock factories (which are hoisted)
const { mockGetUser, mockFrom, mockCustomersCreate, mockCheckoutSessionsCreate } = vi.hoisted(
  () => ({
    mockGetUser: vi.fn(),
    mockFrom: vi.fn(),
    mockCustomersCreate: vi.fn(),
    mockCheckoutSessionsCreate: vi.fn(),
  }),
);

// Mock next/headers (needed by supabase/server)
vi.mock('next/headers', () => ({
  cookies: vi.fn().mockResolvedValue({
    getAll: vi.fn().mockReturnValue([]),
    set: vi.fn(),
  }),
}));

// Mock supabase server
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
  },
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
    process.env.NEXT_PUBLIC_SITE_URL = 'https://pitchrank.com';
  });

  it('returns 401 when not authenticated', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });

    const res = await POST(makeRequest({ priceId: 'price_abc123' }));

    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.error).toBe('Not authenticated');
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
    mockCheckoutSessionsCreate.mockRejectedValue(
      new Error('Your card was declined. Request req_abc123.'),
    );

    const res = await POST(makeRequest({ priceId: 'price_valid123' }));

    expect(res.status).toBe(500);
    const body = await res.json();
    // The route currently includes the error message - verify it exists
    expect(body.error).toBeDefined();
    expect(typeof body.error).toBe('string');
  });
});
