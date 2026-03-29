import { describe, it, expect, vi, beforeEach } from 'vitest';
import type Stripe from 'stripe';

// Mock next/headers before importing the route
vi.mock('next/headers', () => ({
  headers: vi.fn(),
}));

// Mock the stripe module
vi.mock('@/lib/stripe/server', () => ({
  stripe: {
    webhooks: {
      constructEvent: vi.fn(),
    },
    subscriptions: {
      retrieve: vi.fn(),
    },
  },
  WEBHOOK_EVENTS: {
    CHECKOUT_COMPLETED: 'checkout.session.completed',
    SUBSCRIPTION_UPDATED: 'customer.subscription.updated',
    SUBSCRIPTION_DELETED: 'customer.subscription.deleted',
    INVOICE_PAID: 'invoice.paid',
    INVOICE_PAYMENT_FAILED: 'invoice.payment_failed',
  },
}));

// Mock @supabase/supabase-js (used directly in webhook route for admin client)
vi.mock('@supabase/supabase-js', () => ({
  createClient: vi.fn(() => ({
    from: vi.fn(() => ({
      update: vi.fn().mockReturnThis(),
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnValue({
        select: vi.fn().mockResolvedValue({ data: [{ id: '1' }], error: null }),
      }),
    })),
  })),
}));

import { POST } from '../route';
import { headers } from 'next/headers';
import { stripe } from '@/lib/stripe/server';

function makeRequest(body = ''): Request {
  return new Request('http://localhost/api/stripe/webhook', {
    method: 'POST',
    body,
  });
}

describe('POST /api/stripe/webhook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset env vars
    process.env.STRIPE_WEBHOOK_SECRET = 'whsec_test_secret';
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-service-role-key';
  });

  it('returns 400 when stripe-signature header is missing', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([]) as unknown as Awaited<ReturnType<typeof headers>>,
    );

    const res = await POST(makeRequest());

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toContain('Missing stripe-signature header');
  });

  it('returns 500 when webhook secret is not configured', async () => {
    delete process.env.STRIPE_WEBHOOK_SECRET;

    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_test']]) as unknown as Awaited<ReturnType<typeof headers>>,
    );

    const res = await POST(makeRequest());

    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body.error).toBe('Webhook not configured');
  });

  it('returns 400 with generic message on signature verification failure', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_invalid']]) as unknown as Awaited<
        ReturnType<typeof headers>
      >,
    );

    vi.mocked(stripe.webhooks.constructEvent).mockImplementation(() => {
      throw new Error('No signatures found matching the expected signature for payload');
    });

    const res = await POST(makeRequest('bad body'));

    expect(res.status).toBe(400);
    const body = await res.json();
    // Should NOT leak the raw Stripe error message
    expect(body.error).toBe('Webhook signature verification failed');
    expect(body.error).not.toContain('No signatures found');
  });

  it('returns 200 for known event types', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<
        ReturnType<typeof headers>
      >,
    );

    const fakeEvent = {
      type: 'customer.subscription.deleted',
      data: {
        object: {
          id: 'sub_123',
          customer: 'cus_123',
          status: 'canceled',
        } as unknown as Stripe.Subscription,
      },
    } as Stripe.Event;

    vi.mocked(stripe.webhooks.constructEvent).mockReturnValue(fakeEvent);

    const res = await POST(makeRequest('valid body'));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.received).toBe(true);
  });

  it('returns 200 for unknown event types (acknowledge receipt)', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<
        ReturnType<typeof headers>
      >,
    );

    const fakeEvent = {
      type: 'some.unknown.event',
      data: { object: {} },
    } as unknown as Stripe.Event;

    vi.mocked(stripe.webhooks.constructEvent).mockReturnValue(fakeEvent);

    const res = await POST(makeRequest('valid body'));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.received).toBe(true);
  });
});
