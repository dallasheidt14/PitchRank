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
    customers: {
      retrieve: vi.fn().mockResolvedValue({ id: 'cus_123', email: 'test@example.com' }),
      update: vi.fn().mockResolvedValue({ id: 'cus_123' }),
    },
  },
  WEBHOOK_EVENTS: {
    CHECKOUT_COMPLETED: 'checkout.session.completed',
    SUBSCRIPTION_UPDATED: 'customer.subscription.updated',
    SUBSCRIPTION_DELETED: 'customer.subscription.deleted',
    INVOICE_PAID: 'invoice.paid',
    INVOICE_PAYMENT_FAILED: 'invoice.payment_failed',
    TRIAL_WILL_END: 'customer.subscription.trial_will_end',
    CHARGE_REFUNDED: 'charge.refunded',
  },
  extractPeriodEnd: vi.fn(() => new Date().toISOString()),
  mapStatusToPlan: vi.fn((status: string) =>
    status === 'active' || status === 'trialing' || status === 'past_due' ? 'premium' : 'free'
  ),
  updateUserProfile: vi.fn().mockResolvedValue([{ id: '1' }]),
}));

// Mock the Beehiiv client — assert lifecycle routing without hitting the API
vi.mock('@/lib/beehiiv', () => ({
  tagSubscriber: vi.fn().mockResolvedValue(true),
  untagSubscriber: vi.fn().mockResolvedValue(true),
  setLifecycle: vi.fn().mockResolvedValue(true),
  enrollInAutomation: vi.fn().mockResolvedValue(true),
}));

vi.mock('@/lib/notifications/admin', () => ({
  notifyAdmin: vi.fn().mockResolvedValue(true),
}));

vi.mock('@/lib/email/password-setup', () => ({
  sendPasswordSetupEmail: vi.fn().mockResolvedValue(true),
}));

// Mock @supabase/supabase-js (used directly in webhook route for admin client).
// Builder supports both:
//   - update(...).eq(...).select() → returns rows for updateUserProfile-style writes
//   - select(...).eq(...).maybeSingle() → returns one row for getPriorState reads
//
// Tests override priorStateRow to control what getPriorState reads back.
let priorStateRow: Record<string, unknown> | null = null;
function setPriorState(row: Record<string, unknown> | null) {
  priorStateRow = row;
}

vi.mock('@supabase/supabase-js', () => ({
  createClient: vi.fn(() => ({
    from: vi.fn(() => {
      const builder: Record<string, unknown> = {
        update: vi.fn().mockReturnThis(),
        select: vi.fn().mockReturnThis(),
        eq: vi.fn().mockReturnThis(),
        maybeSingle: vi.fn().mockImplementation(() => Promise.resolve({ data: priorStateRow, error: null })),
        then: undefined,
      };
      // For .eq() chains that terminate in a second .select() (updateUserProfile pattern)
      builder.eq = vi.fn().mockReturnValue({
        select: vi.fn().mockResolvedValue({ data: [{ id: '1' }], error: null }),
        maybeSingle: vi.fn().mockImplementation(() => Promise.resolve({ data: priorStateRow, error: null })),
      });
      return builder;
    }),
    auth: {
      admin: {
        createUser: vi
          .fn()
          .mockResolvedValue({ data: { user: { id: 'new-user-id', email: 'test@example.com' } }, error: null }),
        generateLink: vi.fn().mockResolvedValue({ data: { properties: { action_link: 'https://example.com/setup' } } }),
      },
    },
  })),
}));

import { POST } from '../route';
import { headers } from 'next/headers';
import { stripe, updateUserProfile } from '@/lib/stripe/server';
import { setLifecycle, enrollInAutomation } from '@/lib/beehiiv';

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
    vi.mocked(headers).mockResolvedValue(new Map([]) as unknown as Awaited<ReturnType<typeof headers>>);

    const res = await POST(makeRequest());

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toContain('Missing stripe-signature header');
  });

  it('returns 500 when webhook secret is not configured', async () => {
    delete process.env.STRIPE_WEBHOOK_SECRET;

    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_test']]) as unknown as Awaited<ReturnType<typeof headers>>
    );

    const res = await POST(makeRequest());

    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body.error).toBe('Webhook not configured');
  });

  it('returns 400 with generic message on signature verification failure', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_invalid']]) as unknown as Awaited<ReturnType<typeof headers>>
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
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
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

  it('returns 500 on transient errors so Stripe retries', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
    );

    const fakeEvent = {
      id: 'evt_transient',
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
    vi.mocked(updateUserProfile).mockRejectedValueOnce(new Error('DB connection timeout'));

    const res = await POST(makeRequest('valid body'));

    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body.error).toBe('Webhook handler failed');
  });

  it('returns 200 on permanent errors (missing user) to stop retries', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
    );

    const fakeEvent = {
      id: 'evt_permanent',
      type: 'customer.subscription.deleted',
      data: {
        object: {
          id: 'sub_123',
          customer: 'cus_orphan',
          status: 'canceled',
        } as unknown as Stripe.Subscription,
      },
    } as Stripe.Event;

    vi.mocked(stripe.webhooks.constructEvent).mockReturnValue(fakeEvent);
    vi.mocked(updateUserProfile).mockRejectedValueOnce(
      new Error('No user profile found for Stripe customer cus_orphan')
    );

    const res = await POST(makeRequest('valid body'));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.error).toBe('Permanent webhook error');
  });

  it('tracks cancel_at_period_end on subscription updates', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
    );

    const fakeEvent = {
      id: 'evt_cancel_pending',
      type: 'customer.subscription.updated',
      data: {
        object: {
          id: 'sub_123',
          customer: 'cus_123',
          status: 'active',
          cancel_at_period_end: true,
          items: { data: [{ current_period_end: 1735689600 }] },
        } as unknown as Stripe.Subscription,
      },
    } as Stripe.Event;

    vi.mocked(stripe.webhooks.constructEvent).mockReturnValue(fakeEvent);
    vi.mocked(updateUserProfile).mockResolvedValueOnce([{ id: '1' }]);

    const res = await POST(makeRequest('valid body'));

    expect(res.status).toBe(200);
    expect(vi.mocked(updateUserProfile)).toHaveBeenCalledWith(
      expect.anything(),
      'cus_123',
      expect.objectContaining({ cancel_at_period_end: true })
    );
  });

  it('returns 200 for unknown event types (acknowledge receipt)', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
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

describe('Beehiiv lifecycle routing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.STRIPE_WEBHOOK_SECRET = 'whsec_test_secret';
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-service-role-key';
    setPriorState(null);
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
    );
  });

  function fireEvent(type: string, object: Record<string, unknown>): Promise<Response> {
    vi.mocked(stripe.webhooks.constructEvent).mockReturnValue({
      id: `evt_${type}`,
      type,
      data: { object },
    } as unknown as Stripe.Event);
    return POST(makeRequest('valid body'));
  }

  it('routes trial_canceled when subscription deleted from trialing state', async () => {
    setPriorState({ subscription_status: 'trialing', cancel_at_period_end: false });

    await fireEvent('customer.subscription.deleted', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'canceled',
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'trial_canceled');
  });

  it('routes paid_canceled when subscription deleted from active state', async () => {
    setPriorState({ subscription_status: 'active', cancel_at_period_end: false });

    await fireEvent('customer.subscription.deleted', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'canceled',
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'paid_canceled');
  });

  it('routes past_due when invoice payment fails', async () => {
    await fireEvent('invoice.payment_failed', {
      customer: 'cus_123',
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'past_due');
  });

  it('routes paid_canceled on charge.refunded', async () => {
    await fireEvent('charge.refunded', {
      id: 'ch_123',
      customer: 'cus_123',
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'paid_canceled');
  });

  it('skips charge.refunded for guest checkouts without a customer', async () => {
    await fireEvent('charge.refunded', { id: 'ch_guest', customer: null });

    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
  });

  it('acknowledges trial_will_end without writing lifecycle', async () => {
    await fireEvent('customer.subscription.trial_will_end', {
      id: 'sub_123',
      customer: 'cus_123',
    });

    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
  });

  it('routes canceling when cancel_at_period_end flips true', async () => {
    setPriorState({ subscription_status: 'active', cancel_at_period_end: false });

    await fireEvent('customer.subscription.updated', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'active',
      cancel_at_period_end: true,
      items: { data: [{ current_period_end: 1735689600 }] },
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'canceling');
  });

  it('routes paid when cancel_at_period_end flips false (reactivation)', async () => {
    setPriorState({ subscription_status: 'active', cancel_at_period_end: true });

    await fireEvent('customer.subscription.updated', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'paid');
  });

  it('flips lifecycle to paid only on first invoice after trial', async () => {
    setPriorState({ subscription_status: 'trialing', cancel_at_period_end: false });
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    await fireEvent('invoice.paid', {
      customer: 'cus_123',
      parent: { subscription_details: { subscription: 'sub_123' } },
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'paid');
  });

  it('does not flip lifecycle on renewal invoices (active → active)', async () => {
    setPriorState({ subscription_status: 'active', cancel_at_period_end: false });
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    await fireEvent('invoice.paid', {
      customer: 'cus_123',
      parent: { subscription_details: { subscription: 'sub_123' } },
    });

    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
  });

  it('recovers lifecycle to paid when past_due invoice succeeds on retry', async () => {
    setPriorState({ subscription_status: 'past_due', cancel_at_period_end: false });
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    await fireEvent('invoice.paid', {
      customer: 'cus_123',
      parent: { subscription_details: { subscription: 'sub_123' } },
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'paid');
  });
});

describe('Beehiiv automation enrollment', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.STRIPE_WEBHOOK_SECRET = 'whsec_test_secret';
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-service-role-key';
    // Clear all lifecycle automation env vars between tests
    for (const key of [
      'BEEHIIV_TRIAL_AUTOMATION_ID',
      'BEEHIIV_PAID_AUTOMATION_ID',
      'BEEHIIV_TRIAL_CANCEL_AUTOMATION_ID',
      'BEEHIIV_PAID_CANCEL_AUTOMATION_ID',
      'BEEHIIV_DUNNING_AUTOMATION_ID',
    ]) {
      delete process.env[key];
    }
    setPriorState(null);
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
    );
  });

  function fireEvent(type: string, object: Record<string, unknown>): Promise<Response> {
    vi.mocked(stripe.webhooks.constructEvent).mockReturnValue({
      id: `evt_${type}`,
      type,
      data: { object },
    } as unknown as Stripe.Event);
    return POST(makeRequest('valid body'));
  }

  it('enrolls in trial automation when checkout completes with trialing status', async () => {
    process.env.BEEHIIV_TRIAL_AUTOMATION_ID = 'aut_test_trial';
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      status: 'trialing',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    await fireEvent('checkout.session.completed', {
      customer: 'cus_123',
      subscription: 'sub_123',
    });

    expect(vi.mocked(enrollInAutomation)).toHaveBeenCalledWith('test@example.com', 'aut_test_trial');
  });

  it('skips enrollment when the automation env var is not set', async () => {
    setPriorState({ subscription_status: 'trialing', cancel_at_period_end: false });

    await fireEvent('customer.subscription.deleted', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'canceled',
    });

    // lifecycle should still be written, but no enrollment without BEEHIIV_TRIAL_CANCEL_AUTOMATION_ID
    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'trial_canceled');
    expect(vi.mocked(enrollInAutomation)).not.toHaveBeenCalled();
  });

  it('enrolls in trial-cancel automation when set and trial canceled', async () => {
    process.env.BEEHIIV_TRIAL_CANCEL_AUTOMATION_ID = 'aut_test_trial_cancel';
    setPriorState({ subscription_status: 'trialing', cancel_at_period_end: false });

    await fireEvent('customer.subscription.deleted', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'canceled',
    });

    expect(vi.mocked(enrollInAutomation)).toHaveBeenCalledWith('test@example.com', 'aut_test_trial_cancel');
  });
});
