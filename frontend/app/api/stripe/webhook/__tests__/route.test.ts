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
      cancel: vi.fn().mockResolvedValue({ id: 'sub_123', status: 'canceled' }),
    },
    customers: {
      retrieve: vi.fn().mockResolvedValue({ id: 'cus_123', email: 'test@example.com' }),
      update: vi.fn().mockResolvedValue({ id: 'cus_123' }),
    },
  },
  WEBHOOK_EVENTS: {
    CHECKOUT_COMPLETED: 'checkout.session.completed',
    CHECKOUT_ASYNC_PAYMENT_SUCCEEDED: 'checkout.session.async_payment_succeeded',
    CHECKOUT_ASYNC_PAYMENT_FAILED: 'checkout.session.async_payment_failed',
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
  isSessionPaymentSettled: (s: { payment_status?: string }) =>
    s.payment_status === 'paid' || s.payment_status === 'no_payment_required',
}));

// Mock the Beehiiv client — assert lifecycle routing without hitting the API
vi.mock('@/lib/beehiiv', () => ({
  tagSubscriber: vi.fn().mockResolvedValue(true),
  untagSubscriber: vi.fn().mockResolvedValue(true),
  setLifecycle: vi.fn().mockResolvedValue(true),
  setSubscriberCustomField: vi.fn().mockResolvedValue(true),
  enrollInAutomation: vi.fn().mockResolvedValue(true),
}));

vi.mock('@/lib/notifications/admin', () => ({
  notifyAdmin: vi.fn().mockResolvedValue(true),
}));

vi.mock('@/lib/email/password-setup', () => ({
  sendPasswordSetupEmail: vi.fn().mockResolvedValue(true),
}));

vi.mock('@/lib/email/returning-subscriber', () => ({
  sendReturningSubscriberEmail: vi.fn().mockResolvedValue(true),
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

// When set, successive .maybeSingle() calls consume this queue instead of
// priorStateRow — lets a test return different rows for the customer-ID
// lookup vs the email lookup in handleCheckoutCompleted.
let maybeSingleQueue: Array<Record<string, unknown> | null> | null = null;
function queueMaybeSingle(rows: Array<Record<string, unknown> | null>) {
  maybeSingleQueue = rows;
}
function nextMaybeSingle() {
  return maybeSingleQueue && maybeSingleQueue.length > 0 ? maybeSingleQueue.shift()! : priorStateRow;
}

// hashed_token the mocked admin generateLink returns. Set to null to simulate
// Supabase returning no link (one of the set-password failure modes).
let generateLinkHashedToken: string | null = 'test-hashed-token';
function setGenerateLinkHashedToken(value: string | null) {
  generateLinkHashedToken = value;
}

vi.mock('@supabase/supabase-js', () => ({
  createClient: vi.fn(() => ({
    from: vi.fn(() => {
      const builder: Record<string, unknown> = {
        update: vi.fn().mockReturnThis(),
        select: vi.fn().mockReturnThis(),
        eq: vi.fn().mockReturnThis(),
        maybeSingle: vi.fn().mockImplementation(() => Promise.resolve({ data: nextMaybeSingle(), error: null })),
        then: undefined,
      };
      // For .eq() chains that terminate in a second .select() (updateUserProfile pattern)
      builder.eq = vi.fn().mockReturnValue({
        select: vi.fn().mockResolvedValue({ data: [{ id: '1' }], error: null }),
        maybeSingle: vi.fn().mockImplementation(() => Promise.resolve({ data: nextMaybeSingle(), error: null })),
      });
      return builder;
    }),
    auth: {
      admin: {
        createUser: vi
          .fn()
          .mockResolvedValue({ data: { user: { id: 'new-user-id', email: 'test@example.com' } }, error: null }),
        generateLink: vi.fn().mockImplementation(() =>
          Promise.resolve({
            data: { properties: generateLinkHashedToken ? { hashed_token: generateLinkHashedToken } : {} },
          })
        ),
      },
    },
  })),
}));

import { POST } from '../route';
import { headers } from 'next/headers';
import { stripe, updateUserProfile } from '@/lib/stripe/server';
import { setLifecycle, setSubscriberCustomField, enrollInAutomation } from '@/lib/beehiiv';
import { sendReturningSubscriberEmail } from '@/lib/email/returning-subscriber';
import { sendPasswordSetupEmail } from '@/lib/email/password-setup';
import { notifyAdmin } from '@/lib/notifications/admin';

function makeRequest(body = ''): Request {
  return new Request('http://localhost/api/stripe/webhook', {
    method: 'POST',
    body,
  });
}

describe('POST /api/stripe/webhook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    maybeSingleQueue = null;
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
    // The handler re-fetches current state instead of trusting the payload
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      customer: 'cus_123',
      status: 'active',
      cancel_at_period_end: true,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);
    vi.mocked(updateUserProfile).mockResolvedValueOnce([{ id: '1' }]);

    const res = await POST(makeRequest('valid body'));

    expect(res.status).toBe(200);
    expect(vi.mocked(updateUserProfile)).toHaveBeenCalledWith(
      expect.anything(),
      'cus_123',
      expect.objectContaining({ cancel_at_period_end: true })
    );
  });

  it('cancels anonymous trial checkout for a returning subscriber instead of charging', async () => {
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
    );

    const fakeEvent = {
      id: 'evt_returning_trial',
      type: 'checkout.session.completed',
      data: {
        object: {
          id: 'cs_returning',
          customer: 'cus_new',
          subscription: 'sub_new',
          payment_status: 'no_payment_required',
        } as unknown as Stripe.Checkout.Session,
      },
    } as Stripe.Event;

    vi.mocked(stripe.webhooks.constructEvent).mockReturnValue(fakeEvent);
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_new',
      status: 'trialing',
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    // First maybeSingle: lookup by new stripe_customer_id → no profile (anonymous path).
    // Second maybeSingle: lookup by email → existing account WITH billing history.
    queueMaybeSingle([
      null,
      { id: 'user-returning', stripe_customer_id: 'cus_old', stripe_subscription_id: 'sub_old' },
    ]);

    const res = await POST(makeRequest('valid body'));

    expect(res.status).toBe(200);
    // The trial subscription is canceled — never converted to a charge.
    expect(vi.mocked(stripe.subscriptions.cancel)).toHaveBeenCalledWith('sub_new');
    // User is told to log in and re-subscribe; admin is notified.
    expect(vi.mocked(sendReturningSubscriberEmail)).toHaveBeenCalledWith('test@example.com');
    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(expect.stringContaining('Returning subscriber'));
    // The profile keeps its existing billing state, and no lifecycle
    // routing fires for the canceled checkout.
    expect(vi.mocked(updateUserProfile)).not.toHaveBeenCalled();
    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
    expect(vi.mocked(enrollInAutomation)).not.toHaveBeenCalled();
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
    maybeSingleQueue = null;
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
      hosted_invoice_url: 'https://invoice.stripe.com/i/test_abc',
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'past_due');
    expect(vi.mocked(setSubscriberCustomField)).toHaveBeenCalledWith(
      'test@example.com',
      'last_failed_invoice_url',
      'https://invoice.stripe.com/i/test_abc'
    );
  });

  it('routes paid_canceled on charge.refunded', async () => {
    await fireEvent('charge.refunded', {
      id: 'ch_123',
      customer: 'cus_123',
      refunded: true,
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'paid_canceled');
  });

  it('skips charge.refunded for guest checkouts without a customer', async () => {
    await fireEvent('charge.refunded', { id: 'ch_guest', customer: null, refunded: true });

    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
  });

  it('ignores partial refunds (charge.refunded false)', async () => {
    await fireEvent('charge.refunded', { id: 'ch_partial', customer: 'cus_123', refunded: false });

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
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      customer: 'cus_123',
      status: 'active',
      cancel_at_period_end: true,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

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
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      customer: 'cus_123',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    await fireEvent('customer.subscription.updated', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    });

    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'paid');
  });

  it('writes current subscription state when a stale update event replays', async () => {
    setPriorState({ subscription_status: 'canceled', cancel_at_period_end: false });
    // The replayed event claims active, but Stripe's current truth is canceled
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      customer: 'cus_123',
      status: 'canceled',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    await fireEvent('customer.subscription.updated', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    });

    expect(vi.mocked(updateUserProfile)).toHaveBeenCalledWith(
      expect.anything(),
      'cus_123',
      expect.objectContaining({ subscription_status: 'canceled', plan: 'free' })
    );
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
    maybeSingleQueue = null;
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
      payment_status: 'paid',
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

  it('flags async payment failure without provisioning anything', async () => {
    await fireEvent('checkout.session.async_payment_failed', {
      id: 'cs_failed',
      customer: 'cus_123',
      subscription: 'sub_123',
      payment_status: 'unpaid',
    });

    expect(vi.mocked(updateUserProfile)).not.toHaveBeenCalled();
    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(expect.stringContaining('Async payment failed'));
  });

  it('skips fulfillment when checkout session is unpaid', async () => {
    await fireEvent('checkout.session.completed', {
      customer: 'cus_123',
      subscription: 'sub_123',
      payment_status: 'unpaid',
    });

    // An async payment method completed checkout but hasn't settled yet — the
    // route must defer activation entirely (no profile write, no Beehiiv routing,
    // and no subscription fetch) until checkout.session.async_payment_succeeded.
    expect(vi.mocked(updateUserProfile)).not.toHaveBeenCalled();
    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
    expect(vi.mocked(enrollInAutomation)).not.toHaveBeenCalled();
    expect(vi.mocked(stripe.subscriptions.retrieve)).not.toHaveBeenCalled();
  });

  it('fulfills async payments via checkout.session.async_payment_succeeded', async () => {
    process.env.BEEHIIV_PAID_AUTOMATION_ID = 'aut_test_paid';
    // A profile already exists for this customer (authenticated checkout path)
    setPriorState({ id: '1', subscription_status: null });
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    await fireEvent('checkout.session.async_payment_succeeded', {
      customer: 'cus_123',
      subscription: 'sub_123',
      payment_status: 'paid',
    });

    // The async-success event runs the same fulfillment handler as a synchronous
    // checkout — the existing profile is activated to premium.
    expect(vi.mocked(updateUserProfile)).toHaveBeenCalledWith(
      expect.anything(),
      'cus_123',
      expect.objectContaining({ plan: 'premium' })
    );
  });
});

describe('Idempotency on Stripe webhook re-delivery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    maybeSingleQueue = null;
    process.env.STRIPE_WEBHOOK_SECRET = 'whsec_test_secret';
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-service-role-key';
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

  it('skips trial enrollment when checkout re-delivers and status is unchanged', async () => {
    process.env.BEEHIIV_TRIAL_AUTOMATION_ID = 'aut_test_trial';
    // Existing profile already in 'trialing' state → this is a re-delivery
    setPriorState({ id: '1', subscription_status: 'trialing', cancel_at_period_end: false });
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_123',
      status: 'trialing',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);

    await fireEvent('checkout.session.completed', {
      customer: 'cus_123',
      subscription: 'sub_123',
      payment_status: 'paid',
    });

    expect(vi.mocked(enrollInAutomation)).not.toHaveBeenCalled();
    // Lifecycle write still fires (idempotent upsert)
    expect(vi.mocked(setLifecycle)).toHaveBeenCalledWith('test@example.com', 'trialing');
  });

  it('skips Beehiiv sync when subscription.deleted re-delivers (already canceled)', async () => {
    process.env.BEEHIIV_TRIAL_CANCEL_AUTOMATION_ID = 'aut_test_trial_cancel';
    process.env.BEEHIIV_PAID_CANCEL_AUTOMATION_ID = 'aut_test_paid_cancel';
    // Prior state already canceled — first delivery already ran
    setPriorState({ subscription_status: 'canceled', cancel_at_period_end: false });

    await fireEvent('customer.subscription.deleted', {
      id: 'sub_123',
      customer: 'cus_123',
      status: 'canceled',
    });

    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
    expect(vi.mocked(enrollInAutomation)).not.toHaveBeenCalled();
  });

  it('skips Dunning enrollment when payment_failed re-delivers (already past_due)', async () => {
    process.env.BEEHIIV_DUNNING_AUTOMATION_ID = 'aut_test_dunning';
    setPriorState({ subscription_status: 'past_due', cancel_at_period_end: false });

    await fireEvent('invoice.payment_failed', { customer: 'cus_123' });

    expect(vi.mocked(enrollInAutomation)).not.toHaveBeenCalled();
    expect(vi.mocked(setLifecycle)).not.toHaveBeenCalled();
  });

  it('pins payment_failed ordering: invoice URL → Dunning enroll → DB status', async () => {
    // Regression guard for codex P1 review on PRs #800/#802:
    //   - setSubscriberCustomField MUST run before enrollInAutomation so the
    //     first dunning email renders the per-invoice URL (not portal fallback).
    //   - updateUserProfile (subscription_status='past_due') MUST run AFTER
    //     enrollInAutomation so a mid-flight timeout doesn't orphan a
    //     past_due record that never enrolled (Stripe retry would early-return
    //     on prior.status === 'past_due').
    process.env.BEEHIIV_DUNNING_AUTOMATION_ID = 'aut_test_dunning';
    setPriorState({ subscription_status: 'active', cancel_at_period_end: false });

    await fireEvent('invoice.payment_failed', {
      customer: 'cus_123',
      hosted_invoice_url: 'https://invoice.stripe.com/i/test_ordering',
    });

    const fieldOrder = vi.mocked(setSubscriberCustomField).mock.invocationCallOrder[0];
    const enrollOrder = vi.mocked(enrollInAutomation).mock.invocationCallOrder[0];
    const profileOrder = vi.mocked(updateUserProfile).mock.invocationCallOrder.at(-1) ?? 0;

    expect(fieldOrder).toBeLessThan(enrollOrder);
    expect(enrollOrder).toBeLessThan(profileOrder);
  });
});

describe('Set-password email failure alerts an admin', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    maybeSingleQueue = null;
    process.env.STRIPE_WEBHOOK_SECRET = 'whsec_test_secret';
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-service-role-key';
    setPriorState(null);
    setGenerateLinkHashedToken('test-hashed-token');
    vi.mocked(headers).mockResolvedValue(
      new Map([['stripe-signature', 'sig_valid']]) as unknown as Awaited<ReturnType<typeof headers>>
    );
  });

  // New anonymous checkout: no profile by customer-id, none by email → the
  // route creates a user and tries to send the set-password email.
  function fireNewSignup(): Promise<Response> {
    queueMaybeSingle([null, null]);
    vi.mocked(stripe.subscriptions.retrieve).mockResolvedValueOnce({
      id: 'sub_new',
      status: 'active',
      cancel_at_period_end: false,
      items: { data: [{ current_period_end: 1735689600 }] },
    } as unknown as Stripe.Response<Stripe.Subscription>);
    vi.mocked(stripe.webhooks.constructEvent).mockReturnValue({
      id: 'evt_new_signup',
      type: 'checkout.session.completed',
      data: { object: { customer: 'cus_new', subscription: 'sub_new', payment_status: 'paid' } },
    } as unknown as Stripe.Event);
    return POST(makeRequest('valid body'));
  }

  it('alerts admin and returns 200 when the set-password email send fails', async () => {
    vi.mocked(sendPasswordSetupEmail).mockResolvedValueOnce(false);

    const res = await fireNewSignup();

    expect(res.status).toBe(200);
    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(expect.stringContaining('Set-password email FAILED'));
    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(expect.stringContaining('email send failed'));
    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(expect.stringContaining('test@example.com'));
  });

  it('does not alert when the set-password email sends successfully', async () => {
    vi.mocked(sendPasswordSetupEmail).mockResolvedValueOnce(true);

    const res = await fireNewSignup();

    expect(res.status).toBe(200);
    expect(vi.mocked(sendPasswordSetupEmail)).toHaveBeenCalled();
    expect(vi.mocked(notifyAdmin)).not.toHaveBeenCalledWith(expect.stringContaining('Set-password email FAILED'));
  });

  it('alerts admin and returns 200 when the set-password email throws', async () => {
    vi.mocked(sendPasswordSetupEmail).mockRejectedValueOnce(new Error('Resend unavailable'));

    const res = await fireNewSignup();

    expect(res.status).toBe(200);
    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(expect.stringContaining('Set-password email FAILED'));
  });

  it('alerts admin and returns 200 when no setup link can be generated', async () => {
    setGenerateLinkHashedToken(null);

    const res = await fireNewSignup();

    expect(res.status).toBe(200);
    expect(vi.mocked(sendPasswordSetupEmail)).not.toHaveBeenCalled();
    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(expect.stringContaining('Set-password email FAILED'));
    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(expect.stringContaining('no setup link generated'));
  });
});
