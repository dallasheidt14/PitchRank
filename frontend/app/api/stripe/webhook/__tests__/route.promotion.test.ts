import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';
import type Stripe from 'stripe';
import { filteringClientMock, type MockRow } from '@/test/supabase-mock';
import { makeCheckoutSession, makeStripeSubscription } from '@/test/fixtures';

/**
 * Sale fulfillment against doubles that hold state: profile writes land on stored rows (the real
 * updateUserProfile runs against the filtering double, so a missing row throws for real), Stripe's
 * subscription list honours customer, status and limit and answers newest first, and createUser
 * inserts the trigger-created profile and refuses an email it already holds. Analytics is not
 * mocked: the Measurement Protocol body is read off a stubbed fetch.
 */

const h = vi.hoisted(() => ({
  db: { current: null as unknown as ReturnType<typeof import('@/test/supabase-mock').filteringClientMock> },
  stripe: {
    subscriptions: [] as Stripe.Subscription[],
    customers: new Map<string, { id: string; email: string | null; name: string | null }>(),
    customerUpdates: [] as Array<{ id: string; params: unknown }>,
    /** Awaited by every subscription list, so a test can hold one delivery back while another finishes. */
    listGate: null as null | ((customer: string) => Promise<void>),
  },
  auth: {
    users: [] as Array<{ id: string; email: string }>,
    nextId: 0,
    /** createUser calls wait here until `size` have arrived, so both lookups run before either create. */
    barrier: null as null | { size: number; arrived: number; release: () => void; ready: Promise<void> },
    /** Which side of a createUser race answers late; production can order them either way. */
    late: 'refusal' as 'refusal' | 'creation',
    /** Awaited once the login and its profile exist, before createUser answers. */
    afterInsert: null as null | (() => Promise<void>),
    /** Every updateUserById call, as the sign-in marker is written through it. */
    marks: [] as Array<{ id: string; attributes: unknown }>,
  },
}));

vi.mock('@/lib/promotions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/promotions')>();
  // A second sale, so the event names are shown to come from the sale rather than from code.
  const spring = {
    ...actual.PROMOTIONS[0],
    id: 'spring-2027',
    campaign: 'spring-2027',
    analyticsPrefix: 'spring_sale',
  };
  const promotions = [...actual.PROMOTIONS, spring];
  return {
    ...actual,
    PROMOTIONS: promotions,
    findPromotionById: (id: string) => actual.findPromotionById(id, promotions),
  };
});

vi.mock('next/headers', () => ({ headers: vi.fn(async () => new Map([['stripe-signature', 'sig_valid']])) }));

vi.mock('@/lib/stripe/server', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/stripe/server')>();
  const find = (id: string) => h.stripe.subscriptions.find((s) => s.id === id);
  return {
    ...actual,
    stripe: {
      // Each delivery carries its own event, so two in flight at once never read each other's.
      webhooks: { constructEvent: (body: string) => JSON.parse(body) },
      subscriptions: {
        retrieve: vi.fn(async (id: string) => {
          const subscription = find(id);
          if (!subscription) throw new Error(`No such subscription: ${id}`);
          return subscription;
        }),
        list: vi.fn(async ({ customer, status, limit = 10 }: { customer: string; status: string; limit?: number }) => {
          await h.stripe.listGate?.(customer);
          const rows = h.stripe.subscriptions
            .filter((s) => s.customer === customer && s.status === status)
            .sort((a, b) => b.created - a.created);
          return { data: rows.slice(0, limit), has_more: rows.length > limit };
        }),
        cancel: vi.fn(async (id: string) => {
          const subscription = find(id)!;
          subscription.status = 'canceled';
          return subscription;
        }),
      },
      customers: {
        retrieve: vi.fn(async (id: string) => h.stripe.customers.get(id) ?? { id, deleted: true }),
        update: vi.fn(async (id: string, params: unknown) => {
          h.stripe.customerUpdates.push({ id, params });
          return { id };
        }),
      },
    },
  };
});

async function createUser({ email }: { email: string }) {
  const barrier = h.auth.barrier;
  if (barrier) {
    barrier.arrived += 1;
    if (barrier.arrived === barrier.size) barrier.release();
    await barrier.ready;
  }
  if (h.auth.users.some((user) => user.email === email)) {
    if (h.auth.late === 'refusal') await new Promise((resolve) => setTimeout(resolve, 0));
    return {
      data: { user: null },
      error: { code: 'email_exists', message: 'A user with this email address has already been registered' },
    };
  }
  const user = { id: `user-new-${++h.auth.nextId}`, email };
  h.auth.users.push(user);
  // The handle_new_user trigger's insert.
  h.db.current.tableRows.user_profiles.push(profile({ id: user.id, email }));
  await h.auth.afterInsert?.();
  // The login and its profile exist from here, before the response reaches the caller.
  if (h.auth.late === 'creation') await new Promise((resolve) => setTimeout(resolve, 5));
  return { data: { user }, error: null };
}

vi.mock('@/lib/supabase/service', () => ({
  getSupabaseAdmin: () => ({
    from: (table: string) => h.db.current.client.from(table),
    auth: {
      admin: {
        createUser,
        updateUserById: vi.fn(async (id: string, attributes: unknown) => {
          h.auth.marks.push({ id, attributes });
          return { data: { user: {} }, error: null };
        }),
        generateLink: vi.fn(async () => ({ data: { properties: { hashed_token: 'test-hashed-token' } } })),
      },
    },
  }),
}));

vi.mock('@/lib/beehiiv', () => ({
  tagSubscriber: vi.fn().mockResolvedValue(true),
  untagSubscriber: vi.fn().mockResolvedValue(true),
  setLifecycle: vi.fn().mockResolvedValue(true),
  setSubscriberCustomField: vi.fn().mockResolvedValue(true),
  enrollInAutomation: vi.fn().mockResolvedValue(true),
}));
vi.mock('@/lib/notifications/admin', () => ({ notifyAdmin: vi.fn().mockResolvedValue(undefined) }));
vi.mock('@/lib/email/password-setup', () => ({ sendPasswordSetupEmail: vi.fn().mockResolvedValue(true) }));
vi.mock('@/lib/email/returning-subscriber', () => ({ sendReturningSubscriberEmail: vi.fn().mockResolvedValue(true) }));
vi.mock('@/lib/email/duplicate-subscription', () => ({
  sendDuplicateSubscriptionEmail: vi.fn().mockResolvedValue(true),
}));
vi.mock('@/lib/email/duplicate-purchase', () => ({ sendDuplicatePurchaseEmail: vi.fn().mockResolvedValue(true) }));

import { POST } from '../route';
import { stripe } from '@/lib/stripe/server';
import { notifyAdmin } from '@/lib/notifications/admin';
import { setLifecycle } from '@/lib/beehiiv';
import { sendDuplicatePurchaseEmail } from '@/lib/email/duplicate-purchase';
import { sendPasswordSetupEmail } from '@/lib/email/password-setup';
import { sendDuplicateSubscriptionEmail } from '@/lib/email/duplicate-subscription';
import { sendReturningSubscriberEmail } from '@/lib/email/returning-subscriber';

const PAYER_EMAIL = 'parent@example.com';
const UNLINKED = '[webhook] PAID_CHECKOUT_NOT_LINKED';

function profile(overrides: MockRow = {}): MockRow {
  return {
    id: 'user-payer',
    email: PAYER_EMAIL,
    plan: 'free',
    stripe_customer_id: null,
    stripe_subscription_id: null,
    subscription_status: null,
    subscription_period_end: null,
    cancel_at_period_end: false,
    ...overrides,
  };
}

function seedProfiles(...rows: MockRow[]) {
  h.db.current.tableRows.user_profiles = rows;
}

const storedProfile = (id: string) => h.db.current.tableRows.user_profiles.find((row) => row.id === id);

function addSubscription(
  id: string,
  customer: string,
  status: Stripe.Subscription.Status = 'active',
  created = 1_700_000_000
): Stripe.Subscription {
  const subscription = makeStripeSubscription({ id, customer, status, created, interval: 'year', unitAmount: 6999 });
  h.stripe.subscriptions.push(subscription);
  return subscription;
}

function addCustomer(id: string, email: string | null = PAYER_EMAIL) {
  h.stripe.customers.set(id, { id, email, name: 'A Parent' });
}

function saleSession(overrides: Parameters<typeof makeCheckoutSession>[0] = {}) {
  return makeCheckoutSession({
    customer: 'cus_guest',
    subscription: 'sub_sale',
    ...overrides,
    metadata: {
      anonymous_checkout: 'true',
      promotion: 'black-friday-2026',
      segment: 'signed_out',
      ga_client_id: '123.456',
      utm_source: 'facebook',
      ...overrides.metadata,
    },
  });
}

function standardSession(overrides: Parameters<typeof makeCheckoutSession>[0] = {}) {
  return makeCheckoutSession({ customer: 'cus_guest', subscription: 'sub_std', amountTotal: 6999, ...overrides });
}

function deliver(type: string, object: unknown): Promise<Response> {
  const event = { id: `evt_${type}`, type, data: { object } };
  return POST(new Request('http://localhost/api/stripe/webhook', { method: 'POST', body: JSON.stringify(event) }));
}

const complete = (session: Stripe.Checkout.Session) => deliver('checkout.session.completed', session);

let fetchMock: ReturnType<typeof vi.fn>;
let consoleError: MockInstance<typeof console.error>;

const gaEvents = () =>
  fetchMock.mock.calls
    .filter(([url]) => String(url).startsWith('https://www.google-analytics.com/'))
    .flatMap(
      ([, init]) => (JSON.parse((init as RequestInit).body as string) as { events: unknown[] }).events
    ) as Array<{
    name: string;
    params?: Record<string, unknown>;
  }>;
const purchaseEvents = () => gaEvents().filter((event) => event.name === 'black_friday_purchase_completed');
const unlinkedLines = () => consoleError.mock.calls.filter(([line]) => line === UNLINKED).map(([, detail]) => detail);
const alerts = () => vi.mocked(notifyAdmin).mock.calls.map(([message]) => message);
const handlerErrors = () =>
  consoleError.mock.calls.map(([line]) => String(line)).filter((line) => line.startsWith('[webhook] Handler error'));

beforeEach(() => {
  vi.clearAllMocks();
  h.db.current = filteringClientMock({ user_profiles: [] });
  h.stripe.subscriptions = [];
  h.stripe.customers = new Map();
  h.stripe.customerUpdates = [];
  h.auth.users = [];
  h.auth.nextId = 0;
  h.auth.barrier = null;
  h.auth.late = 'refusal';
  h.auth.afterInsert = null;
  h.auth.marks = [];
  h.stripe.listGate = null;
  vi.stubEnv('STRIPE_WEBHOOK_SECRET', 'whsec_test');
  vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://pitchrank.io');
  vi.stubEnv('NEXT_PUBLIC_GA_MEASUREMENT_ID', 'G-TEST');
  vi.stubEnv('GA_API_SECRET', 'ga-secret');
  fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204, text: () => Promise.resolve('') });
  vi.stubGlobal('fetch', fetchMock);
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/**
 * Holds every subscription list for `customer` until `release`. `ready` resolves once the first is
 * held and the lists of every other customer have settled.
 */
function holdLists(customer: string) {
  let arrived!: () => void;
  let release!: () => void;
  const reached = new Promise<void>((resolve) => (arrived = resolve));
  const held = new Promise<void>((resolve) => (release = resolve));
  h.stripe.listGate = async (listed) => {
    if (listed !== customer) return;
    arrived();
    await held;
  };
  const ready = reached.then(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));
  return { ready, release: () => release() };
}

/** Holds the next createUser once its login and profile exist, until `release`. */
function holdCreation() {
  let reached!: () => void;
  let release!: () => void;
  const inserted = new Promise<void>((resolve) => (reached = resolve));
  const held = new Promise<void>((resolve) => (release = resolve));
  h.auth.afterInsert = async () => {
    h.auth.afterInsert = null;
    reached();
    await held;
  };
  return { inserted, release: () => release() };
}

function barrier(size: number) {
  let release!: () => void;
  const ready = new Promise<void>((resolve) => (release = resolve));
  h.auth.barrier = { size, arrived: 0, release, ready };
}

describe('a sale bought by someone who already holds Premium', () => {
  it('leaves a payer whose own customer already has a live subscription alone, and alerts the owner', async () => {
    addCustomer('cus_payer');
    addSubscription('sub_old', 'cus_payer', 'active', 1_600_000_000);
    addSubscription('sub_sale', 'cus_payer', 'active', 1_700_000_000);
    seedProfiles(
      profile({
        plan: 'premium',
        stripe_customer_id: 'cus_payer',
        stripe_subscription_id: 'sub_old',
        subscription_status: 'active',
      })
    );

    const res = await complete(saleSession({ customer: 'cus_payer', metadata: { segment: 'returning' } }));

    expect(res.status).toBe(200);
    expect(storedProfile('user-payer')).toEqual({
      id: 'user-payer',
      email: PAYER_EMAIL,
      plan: 'premium',
      stripe_customer_id: 'cus_payer',
      stripe_subscription_id: 'sub_old',
      subscription_status: 'active',
      subscription_period_end: null,
      cancel_at_period_end: false,
    });
    expect(unlinkedLines()).toEqual([{ reason: 'duplicate', subscriptionId: 'sub_sale', customerId: 'cus_payer' }]);
    expect(alerts()).toHaveLength(1);
    expect(alerts()[0]).toContain('sub_old');
    expect(alerts()[0]).toContain('sub_sale');
    expect(alerts()[0]).toContain('profile user-payer points here');
    expect(alerts()[0]).toContain('newsletter lifecycle back to paid');
    expect(sendDuplicatePurchaseEmail).toHaveBeenCalledWith(PAYER_EMAIL);
    expect(purchaseEvents()).toEqual([]);
    expect(setLifecycle).not.toHaveBeenCalled();
  });

  describe('while signed out, matched by email', () => {
    it.each([
      ['a comped premium account with no Stripe customer', { plan: 'premium' }],
      ['an admin account', { plan: 'admin' }],
    ])('refuses to link %s', async (_label, overrides) => {
      addCustomer('cus_guest');
      addSubscription('sub_sale', 'cus_guest');
      seedProfiles(profile(overrides));

      expect((await complete(saleSession())).status).toBe(200);

      expect(storedProfile('user-payer')).toEqual({
        id: 'user-payer',
        email: PAYER_EMAIL,
        plan: overrides.plan,
        stripe_customer_id: null,
        stripe_subscription_id: null,
        subscription_status: null,
        subscription_period_end: null,
        cancel_at_period_end: false,
      });
      expect(h.stripe.customerUpdates).toEqual([]);
      expect(unlinkedLines()).toEqual([{ reason: 'duplicate', subscriptionId: 'sub_sale', customerId: 'cus_guest' }]);
      expect(alerts()).toHaveLength(1);
      expect(sendDuplicatePurchaseEmail).toHaveBeenCalledWith(PAYER_EMAIL);
      expect(purchaseEvents()).toEqual([]);
    });

    it.each([['active'], ['trialing'], ['past_due']] as const)(
      'refuses to link a stale free profile whose other customer holds a %s subscription',
      async (status) => {
        addCustomer('cus_guest');
        addSubscription('sub_sale', 'cus_guest');
        addSubscription('sub_live', 'cus_old', status, 1_600_000_000);
        seedProfiles(profile({ plan: 'free', stripe_customer_id: 'cus_old', stripe_subscription_id: 'sub_live' }));

        expect((await complete(saleSession())).status).toBe(200);

        expect(storedProfile('user-payer')).toEqual({
          id: 'user-payer',
          email: PAYER_EMAIL,
          plan: 'free',
          stripe_customer_id: 'cus_old',
          stripe_subscription_id: 'sub_live',
          subscription_status: null,
          subscription_period_end: null,
          cancel_at_period_end: false,
        });
        expect(h.stripe.customerUpdates).toEqual([]);
        expect(unlinkedLines()).toEqual([{ reason: 'duplicate', subscriptionId: 'sub_sale', customerId: 'cus_guest' }]);
        expect(alerts()[0]).toContain('sub_live');
        expect(alerts()[0]).not.toContain('newsletter lifecycle');
        expect(sendDuplicatePurchaseEmail).toHaveBeenCalledWith(PAYER_EMAIL);
      }
    );

    it('treats a second sale bought after the first as a duplicate', async () => {
      addCustomer('cus_first');
      addCustomer('cus_second');
      addSubscription('sub_first', 'cus_first');
      addSubscription('sub_second', 'cus_second');

      await complete(saleSession({ customer: 'cus_first', subscription: 'sub_first' }));
      await complete(saleSession({ customer: 'cus_second', subscription: 'sub_second' }));

      const [account] = h.db.current.tableRows.user_profiles;
      expect(account).toMatchObject({ stripe_customer_id: 'cus_first', stripe_subscription_id: 'sub_first' });
      expect(unlinkedLines()).toEqual([
        { reason: 'duplicate', subscriptionId: 'sub_second', customerId: 'cus_second' },
      ]);
      expect(purchaseEvents().map((event) => event.params?.transaction_id)).toEqual(['sub_first']);
    });
  });

  it('is not alarmed by a premium profile that already holds this checkout (the sync route linked it first)', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(
      profile({
        plan: 'premium',
        stripe_customer_id: 'cus_guest',
        stripe_subscription_id: 'sub_sale',
        subscription_status: 'active',
      })
    );

    expect((await complete(saleSession())).status).toBe(200);

    expect(unlinkedLines()).toEqual([]);
    expect(purchaseEvents()).toHaveLength(1);
  });
});

describe('sale checkouts the handler cannot link', () => {
  it('alerts the owner when the Stripe customer has no email', async () => {
    addCustomer('cus_guest', null);
    addSubscription('sub_sale', 'cus_guest');

    expect((await complete(saleSession())).status).toBe(200);

    expect(unlinkedLines()).toEqual([{ reason: 'no_email', subscriptionId: 'sub_sale', customerId: 'cus_guest' }]);
    expect(alerts()).toHaveLength(1);
    expect(purchaseEvents()).toEqual([]);
  });

  it('alerts the owner when a login already holds the email but no profile carries it', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    h.auth.users = [{ id: 'user-elsewhere', email: PAYER_EMAIL }];
    seedProfiles(profile({ id: 'user-elsewhere', email: 'changed@example.com' }));

    expect((await complete(saleSession())).status).toBe(200);

    expect(unlinkedLines()).toEqual([
      { reason: 'account_exists_unlinked', subscriptionId: 'sub_sale', customerId: 'cus_guest' },
    ]);
    expect(storedProfile('user-elsewhere')).toMatchObject({ stripe_customer_id: null, stripe_subscription_id: null });
  });

  it('alerts the owner for the loser of two different sales delivered at once for one new email', async () => {
    addCustomer('cus_one');
    addCustomer('cus_two');
    addSubscription('sub_one', 'cus_one');
    addSubscription('sub_two', 'cus_two');
    barrier(2);

    const responses = await Promise.all([
      complete(saleSession({ customer: 'cus_one', subscription: 'sub_one' })),
      complete(saleSession({ customer: 'cus_two', subscription: 'sub_two' })),
    ]);

    expect(responses.map((res) => res.status)).toEqual([200, 200]);
    expect(h.db.current.tableRows.user_profiles).toHaveLength(1);
    expect(unlinkedLines()).toEqual([
      { reason: 'account_exists_unlinked', subscriptionId: 'sub_two', customerId: 'cus_two' },
    ]);
    expect(storedProfile('user-new-1')).toMatchObject({
      stripe_customer_id: 'cus_one',
      stripe_subscription_id: 'sub_one',
    });
  });

  it('stays quiet when the same sale is delivered twice at once and the other delivery linked it', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    barrier(2);
    const session = saleSession();

    const responses = await Promise.all([complete(session), complete(session)]);

    expect(responses.map((res) => res.status)).toEqual([200, 200]);
    expect(unlinkedLines()).toEqual([]);
    expect(alerts().filter((message) => message.includes('not linked'))).toEqual([]);
    expect(storedProfile('user-new-1')).toMatchObject({
      stripe_customer_id: 'cus_guest',
      stripe_subscription_id: 'sub_sale',
    });
  });

  it('sends nothing for a re-delivered duplicate the owner has already cancelled', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest', 'canceled');
    addSubscription('sub_live', 'cus_old', 'active', 1_600_000_000);
    seedProfiles(profile({ plan: 'premium', stripe_customer_id: 'cus_old', stripe_subscription_id: 'sub_live' }));

    expect((await complete(saleSession())).status).toBe(200);

    expect(unlinkedLines()).toEqual([]);
    expect(alerts()).toEqual([]);
    expect(sendDuplicatePurchaseEmail).not.toHaveBeenCalled();
    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_old',
      stripe_subscription_id: 'sub_live',
    });
  });

  it('still links a cancelled sale to an account that was never billed, without counting a purchase', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest', 'canceled');
    seedProfiles(profile());

    expect((await complete(saleSession())).status).toBe(200);

    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_guest',
      stripe_subscription_id: 'sub_sale',
      plan: 'free',
    });
    expect(h.stripe.customerUpdates).toHaveLength(1);
    expect(unlinkedLines()).toEqual([]);
    expect(purchaseEvents()).toEqual([]);
  });
});

describe('a relinked returning buyer (a known gap, left to the daily sweep)', () => {
  it("re-links the profile to an old standard checkout paid after a guest sale, leaving the sale's customer unlinked", async () => {
    addCustomer('cus_old');
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest', 'active', 1_700_000_000);
    seedProfiles(profile({ stripe_customer_id: 'cus_old', subscription_status: 'canceled' }));

    await complete(saleSession());
    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_guest',
      stripe_subscription_id: 'sub_sale',
    });

    addSubscription('sub_std', 'cus_old', 'active', 1_700_000_100);
    const res = await complete(
      standardSession({ customer: 'cus_old', subscription: 'sub_std', metadata: { supabase_user_id: 'user-payer' } })
    );

    expect(res.status).toBe(200);
    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_old',
      stripe_subscription_id: 'sub_std',
    });
    expect(unlinkedLines()).toEqual([]);
  });
});

describe('profile lookups and writes on every checkout', () => {
  it('answers 500, so Stripe retries, when the lookup by customer fails', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(profile({ plan: 'premium', stripe_customer_id: 'cus_guest', stripe_subscription_id: 'sub_sale' }));
    const failure = h.db.current.failOn({
      table: 'user_profiles',
      op: 'select',
      result: { data: null, error: { message: 'statement timeout' } },
    });

    const res = await complete(saleSession());

    expect(res.status).toBe(500);
    expect(failure.hits).toBe(1);
    expect(unlinkedLines()).toEqual([]);
    expect(alerts()).toEqual([]);
  });

  it.each([
    ['a sale', saleSession],
    ['a standard checkout', standardSession],
  ])('answers 500 when the lookup by email fails, for %s', async (_label, makeSession) => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    addSubscription('sub_std', 'cus_guest');
    seedProfiles(profile());
    const failure = h.db.current.failOn({
      table: 'user_profiles',
      op: 'select',
      skip: 1,
      result: { data: null, error: { message: 'statement timeout' } },
    });

    const res = await complete(makeSession());

    expect(res.status).toBe(500);
    expect(failure.hits).toBe(1);
    expect(h.auth.users).toEqual([]);
  });

  it('links a buyer whose Stripe email differs only in case', async () => {
    h.stripe.customers.set('cus_guest', { id: 'cus_guest', email: ' Parent@Example.COM ', name: 'A Parent' });
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(profile());

    expect((await complete(saleSession())).status).toBe(200);

    expect(h.auth.users).toEqual([]);
    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_guest',
      stripe_subscription_id: 'sub_sale',
    });
  });

  describe.each([
    ['links an existing account', () => seedProfiles(profile())],
    ['creates an account', () => seedProfiles()],
  ])('when the signed-out write that %s', (_label, seed) => {
    it.each([
      ['errors', { data: null, error: { message: 'connection reset' } }, 'profile write failed: connection reset'],
      ['matches no row', { data: [], error: null }, 'profile write matched no row'],
    ])('%s, answers 500 and counts no purchase', async (_case, result, message) => {
      addCustomer('cus_guest');
      addSubscription('sub_sale', 'cus_guest');
      seed();
      const failure = h.db.current.failOn({ table: 'user_profiles', op: 'update', result });

      const res = await complete(saleSession());

      expect(res.status).toBe(500);
      expect(failure.hits).toBe(1);
      expect(handlerErrors()).toEqual([`[webhook] Handler error for checkout.session.completed: ${message}`]);
      expect(purchaseEvents()).toEqual([]);
    });
  });
});

describe('the purchase event', () => {
  it('goes out last, once the profile holds the sale, with its price in dollars', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(profile());
    const linkedWhenSent: unknown[] = [];
    fetchMock.mockImplementation(async (url: string) => {
      if (url.startsWith('https://www.google-analytics.com/')) {
        linkedWhenSent.push(storedProfile('user-payer')?.stripe_subscription_id);
      }
      return { ok: true, status: 204, text: () => Promise.resolve('') };
    });

    await complete(saleSession());

    expect(purchaseEvents()).toEqual([
      {
        name: 'black_friday_purchase_completed',
        params: {
          transaction_id: 'sub_sale',
          value: 47.88,
          currency: 'USD',
          promotion_id: 'black-friday-2026',
          segment: 'signed_out',
          utm_source: 'facebook',
        },
      },
    ]);
    expect(linkedWhenSent.at(-1)).toBe('sub_sale');
    expect(gaEvents().map((event) => event.name)).toEqual([
      'subscription_completed',
      'black_friday_purchase_completed',
    ]);
  });

  it.each([
    ['no amount', { amountTotal: null }],
    ['no currency', { currency: null }],
  ])('leaves out both value and currency when the session has %s', async (_label, overrides) => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');

    await complete(saleSession(overrides));

    const [event] = purchaseEvents();
    expect(event.params).not.toHaveProperty('value');
    expect(event.params).not.toHaveProperty('currency');
    expect(event.params?.transaction_id).toBe('sub_sale');
  });

  it('is not sent for a standard checkout', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_std', 'cus_guest');

    await complete(standardSession());

    expect(purchaseEvents()).toEqual([]);
    expect(gaEvents().map((event) => event.name)).toEqual(['subscription_completed']);
  });
});

describe('an expired checkout', () => {
  it("is counted for a sale, under the visitor's analytics id", async () => {
    await deliver('checkout.session.expired', saleSession({ status: 'expired', paymentStatus: 'unpaid' }));

    expect(gaEvents()).toEqual([
      { name: 'black_friday_checkout_expired', params: { promotion_id: 'black-friday-2026', segment: 'signed_out' } },
    ]);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string).client_id).toBe('123.456');
  });

  it('is not counted for a standard checkout', async () => {
    await deliver('checkout.session.expired', standardSession({ status: 'expired', paymentStatus: 'unpaid' }));

    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("the owner's by-hand clean-up of a duplicate", () => {
  it("leaves the payer's newsletter alone when refunding a purchase no profile holds", async () => {
    addCustomer('cus_guest');
    seedProfiles(profile({ plan: 'premium', stripe_customer_id: 'cus_payer', subscription_status: 'active' }));

    expect((await deliver('charge.refunded', { id: 'ch_dup', customer: 'cus_guest', refunded: true })).status).toBe(
      200
    );

    expect(setLifecycle).not.toHaveBeenCalled();
  });

  it('still routes a refund on a linked customer to the win-back sequence', async () => {
    addCustomer('cus_payer');
    seedProfiles(profile({ plan: 'premium', stripe_customer_id: 'cus_payer', subscription_status: 'active' }));

    await deliver('charge.refunded', { id: 'ch_paid', customer: 'cus_payer', refunded: true });

    expect(setLifecycle).toHaveBeenCalledWith(PAYER_EMAIL, 'paid_canceled');
  });

  it('changes no profile when cancelling a duplicate no profile holds', async () => {
    addCustomer('cus_guest');
    seedProfiles(profile({ plan: 'premium', stripe_customer_id: 'cus_payer', subscription_status: 'active' }));

    const res = await deliver('customer.subscription.deleted', {
      id: 'sub_sale',
      customer: 'cus_guest',
      status: 'canceled',
    });

    expect(res.status).toBe(200);
    expect(storedProfile('user-payer')).toEqual(
      profile({ plan: 'premium', stripe_customer_id: 'cus_payer', subscription_status: 'active' })
    );
    expect(setLifecycle).not.toHaveBeenCalled();
  });
});

describe('replays and races on a sale', () => {
  it.each([
    ['a comped premium account', { plan: 'premium' }],
    ['an admin account', { plan: 'admin' }],
  ])('leaves %s alone when a refunded duplicate is delivered again', async (_label, overrides) => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest', 'canceled');
    seedProfiles(profile(overrides));

    expect((await complete(saleSession())).status).toBe(200);

    expect(storedProfile('user-payer')).toEqual({
      id: 'user-payer',
      email: PAYER_EMAIL,
      plan: overrides.plan,
      stripe_customer_id: null,
      stripe_subscription_id: null,
      subscription_status: null,
      subscription_period_end: null,
      cancel_at_period_end: false,
    });
    expect(h.stripe.customerUpdates).toEqual([]);
    expect(alerts()).toEqual([]);
    expect(sendDuplicatePurchaseEmail).not.toHaveBeenCalled();
  });

  it("leaves a payer's own customer alone when a refunded same-customer duplicate is delivered again", async () => {
    addCustomer('cus_payer');
    addSubscription('sub_old', 'cus_payer', 'active', 1_600_000_000);
    addSubscription('sub_sale', 'cus_payer', 'canceled', 1_700_000_000);
    seedProfiles(
      profile({
        plan: 'premium',
        stripe_customer_id: 'cus_payer',
        stripe_subscription_id: 'sub_old',
        subscription_status: 'active',
      })
    );

    expect((await complete(saleSession({ customer: 'cus_payer' }))).status).toBe(200);

    expect(storedProfile('user-payer')).toEqual({
      id: 'user-payer',
      email: PAYER_EMAIL,
      plan: 'premium',
      stripe_customer_id: 'cus_payer',
      stripe_subscription_id: 'sub_old',
      subscription_status: 'active',
      subscription_period_end: null,
      cancel_at_period_end: false,
    });
    expect(alerts()).toEqual([]);
    // A customer read failing here would turn an event to ignore into a 500.
    expect(vi.mocked(stripe.customers.retrieve)).not.toHaveBeenCalled();
  });

  it('creates no account for a refunded duplicate whose own customer still holds a live subscription', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_other', 'cus_guest', 'active', 1_600_000_000);
    addSubscription('sub_sale', 'cus_guest', 'canceled', 1_700_000_000);

    expect((await complete(saleSession())).status).toBe(200);

    expect(h.auth.users).toEqual([]);
    expect(h.db.current.tableRows.user_profiles).toEqual([]);
    expect(alerts()).toEqual([]);
  });

  it('makes the second of two concurrent sales for one free account retry, then reach the owner as a duplicate', async () => {
    addCustomer('cus_one');
    addCustomer('cus_two');
    addSubscription('sub_one', 'cus_one');
    addSubscription('sub_two', 'cus_two');
    seedProfiles(profile());
    // The second delivery reads the free profile, then waits while the first links it.
    const gate = holdLists('cus_two');

    const second = complete(saleSession({ customer: 'cus_two', subscription: 'sub_two' }));
    await gate.ready;
    expect((await complete(saleSession({ customer: 'cus_one', subscription: 'sub_one' }))).status).toBe(200);
    gate.release();

    expect((await second).status).toBe(500);
    expect(handlerErrors()).toEqual([
      '[webhook] Handler error for checkout.session.completed: profile write matched no row',
    ]);
    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_one',
      stripe_subscription_id: 'sub_one',
    });

    // Stripe's retry of the second now meets the linked account.
    h.stripe.listGate = null;
    expect((await complete(saleSession({ customer: 'cus_two', subscription: 'sub_two' }))).status).toBe(200);
    expect(unlinkedLines()).toEqual([{ reason: 'duplicate', subscriptionId: 'sub_two', customerId: 'cus_two' }]);
    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_one',
      stripe_subscription_id: 'sub_one',
    });
  });

  it("makes a signed-out sale retry when a signed-in checkout links the lapsed account's own customer first", async () => {
    addCustomer('cus_guest');
    addCustomer('cus_old');
    addSubscription('sub_sale', 'cus_guest');
    addSubscription('sub_lapsed', 'cus_old', 'canceled', 1_600_000_000);
    seedProfiles(
      profile({ stripe_customer_id: 'cus_old', stripe_subscription_id: 'sub_lapsed', subscription_status: 'canceled' })
    );
    const gate = holdLists('cus_guest');

    const guest = complete(saleSession());
    await gate.ready;
    // The signed-in checkout on the old customer is paid, and its webhook links it, while the guest waits.
    addSubscription('sub_signed_in', 'cus_old', 'active', 1_700_000_100);
    expect((await complete(standardSession({ customer: 'cus_old', subscription: 'sub_signed_in' }))).status).toBe(200);
    gate.release();

    expect((await guest).status).toBe(500);
    expect(handlerErrors()).toEqual([
      '[webhook] Handler error for checkout.session.completed: profile write matched no row',
    ]);
    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_old',
      stripe_subscription_id: 'sub_signed_in',
    });

    // Stripe's retry of the guest now meets the live subscription on the old customer.
    h.stripe.listGate = null;
    expect((await complete(saleSession())).status).toBe(200);
    expect(unlinkedLines()).toEqual([{ reason: 'duplicate', subscriptionId: 'sub_sale', customerId: 'cus_guest' }]);
    expect(storedProfile('user-payer')).toMatchObject({ stripe_subscription_id: 'sub_signed_in' });
  });

  it('makes a signed-out sale retry when the account is given a Stripe customer of its own meanwhile', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(profile());
    const gate = holdLists('cus_guest');

    const guest = complete(saleSession());
    await gate.ready;
    // The buyer signs in and opens a checkout, which gives the profile a customer of its own.
    storedProfile('user-payer')!.stripe_customer_id = 'cus_signed_in';
    gate.release();

    expect((await guest).status).toBe(500);
    expect(handlerErrors()).toEqual([
      '[webhook] Handler error for checkout.session.completed: profile write matched no row',
    ]);
    expect(storedProfile('user-payer')).toMatchObject({
      stripe_customer_id: 'cus_signed_in',
      stripe_subscription_id: null,
    });
  });

  it.each([
    ['sale', 'sub_sale', 'active', () => saleSession()],
    ['standard trial', 'sub_std', 'trialing', () => standardSession()],
  ] as const)(
    'still sends the new buyer their set-password email when a twin delivery links the new account first (%s)',
    async (_label, subscriptionId, status, session) => {
      addCustomer('cus_guest');
      addSubscription(subscriptionId, 'cus_guest', status);
      // Another account exists, so the creator's re-read has to pick its own row.
      seedProfiles(profile({ id: 'user-other', email: 'other@example.com' }));
      const creation = holdCreation();
      const checkout = session();

      const creator = complete(checkout);
      await creation.inserted;
      // The twin finds the brand-new profile by email and links it while the creator waits.
      expect((await complete(checkout)).status).toBe(200);
      creation.release();

      expect((await creator).status).toBe(200);
      expect(vi.mocked(sendPasswordSetupEmail)).toHaveBeenCalledTimes(1);
      // The twin ran the signup notice and the analytics; the creator adds only the account setup.
      expect(alerts().filter((alert) => alert.includes('New Signup!'))).toHaveLength(1);
      expect(gaEvents().filter((event) => event.name === 'subscription_completed')).toHaveLength(1);
      expect(h.auth.marks).toEqual([
        {
          id: 'user-new-1',
          attributes: { app_metadata: expect.objectContaining({ checkout_session_id: checkout.id }) },
        },
      ]);
      expect(storedProfile('user-new-1')).toMatchObject({
        stripe_customer_id: 'cus_guest',
        stripe_subscription_id: checkout.subscription,
      });
    }
  );

  it('makes the creating delivery retry when a different sale links the new account first, then reach the owner', async () => {
    addCustomer('cus_a');
    addCustomer('cus_b');
    addSubscription('sub_a', 'cus_a');
    addSubscription('sub_b', 'cus_b');
    seedProfiles(profile({ id: 'user-other', email: 'other@example.com' }));
    const creation = holdCreation();
    const first = saleSession({ id: 'cs_first', customer: 'cus_a', subscription: 'sub_a' });

    const creator = complete(first);
    await creation.inserted;
    // A second sale for the same new email finds the brand-new profile and links its own subscription.
    expect((await complete(saleSession({ id: 'cs_second', customer: 'cus_b', subscription: 'sub_b' }))).status).toBe(
      200
    );
    creation.release();

    expect((await creator).status).toBe(500);
    expect(handlerErrors()).toEqual([
      '[webhook] Handler error for checkout.session.completed: profile write matched no row',
    ]);
    expect(vi.mocked(sendPasswordSetupEmail)).not.toHaveBeenCalled();

    // Stripe's retry of the same checkout meets the account the other sale holds: a duplicate.
    expect((await complete(first)).status).toBe(200);
    expect(unlinkedLines()).toEqual([{ reason: 'duplicate', subscriptionId: 'sub_a', customerId: 'cus_a' }]);
    expect(storedProfile('user-new-1')).toMatchObject({ stripe_customer_id: 'cus_b', stripe_subscription_id: 'sub_b' });
  });

  it("retries, rather than alerting, when the same sale's concurrent delivery has created the account but not linked it", async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    barrier(2);
    h.auth.late = 'creation';
    const session = saleSession();

    const responses = await Promise.all([complete(session), complete(session)]);

    expect(responses.map((res) => res.status).sort()).toEqual([200, 500]);
    expect(unlinkedLines()).toEqual([]);
    h.auth.barrier = null;
    expect((await complete(session)).status).toBe(200);
    expect(unlinkedLines()).toEqual([]);
    expect(storedProfile('user-new-1')).toMatchObject({
      stripe_customer_id: 'cus_guest',
      stripe_subscription_id: 'sub_sale',
    });
  });

  it('links, without alarm, a sale whose own customer the matched profile already holds', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(
      profile({
        plan: 'premium',
        stripe_customer_id: 'cus_guest',
        stripe_subscription_id: null,
        subscription_status: 'active',
      })
    );
    // The lookup by customer misses once, as when another delivery linked the row just after it ran.
    h.db.current.failOn({ table: 'user_profiles', op: 'select', result: { data: null, error: null }, times: 1 });

    expect((await complete(saleSession())).status).toBe(200);

    expect(unlinkedLines()).toEqual([]);
    expect(sendDuplicatePurchaseEmail).not.toHaveBeenCalled();
    expect(storedProfile('user-payer')).toMatchObject({
      plan: 'premium',
      stripe_customer_id: 'cus_guest',
      stripe_subscription_id: 'sub_sale',
    });
  });
});

describe("a standard signed-out trial under a comped account's email", () => {
  const comped = (plan: string) => ({
    id: 'user-payer',
    email: PAYER_EMAIL,
    plan,
    stripe_customer_id: null,
    stripe_subscription_id: null,
    subscription_status: null,
    subscription_period_end: null,
    cancel_at_period_end: false,
  });

  it.each([['premium'], ['admin']])('is cancelled, with no charge, and leaves a %s account as it was', async (plan) => {
    addCustomer('cus_stranger');
    addSubscription('sub_trial', 'cus_stranger', 'trialing');
    seedProfiles(profile({ plan }));

    const res = await complete(standardSession({ customer: 'cus_stranger', subscription: 'sub_trial' }));

    expect(res.status).toBe(200);
    expect(h.stripe.subscriptions.find((s) => s.id === 'sub_trial')!.status).toBe('canceled');
    expect(storedProfile('user-payer')).toEqual(comped(plan));
    expect(sendDuplicateSubscriptionEmail).toHaveBeenCalledWith(PAYER_EMAIL);
    expect(alerts()).toEqual([expect.stringContaining('Duplicate checkout blocked')]);
    expect(alerts()[0]).toContain('emailed set-password link.');
  });

  it.each([
    [true, 'emailed log-in-and-resubscribe link.'],
    [false, 'the email to the buyer did not send'],
  ])("tells the owner whether a returning subscriber's blocked-trial email went out (sent: %s)", async (sent, line) => {
    addCustomer('cus_stranger');
    addSubscription('sub_trial', 'cus_stranger', 'trialing');
    seedProfiles(profile({ stripe_customer_id: 'cus_old', subscription_status: 'canceled' }));
    vi.mocked(sendReturningSubscriberEmail).mockResolvedValueOnce(sent);

    await complete(standardSession({ customer: 'cus_stranger', subscription: 'sub_trial' }));

    expect(alerts()).toEqual([expect.stringContaining('Returning subscriber blocked from second trial')]);
    expect(alerts()[0]).toContain(line);
    expect(alerts()[0]).not.toContain(sent ? 'did not send' : 'emailed log-in');
  });

  it('tells the owner when the blocked-trial email did not send', async () => {
    addCustomer('cus_stranger');
    addSubscription('sub_trial', 'cus_stranger', 'trialing');
    seedProfiles(profile({ plan: 'premium' }));
    vi.mocked(sendDuplicateSubscriptionEmail).mockResolvedValueOnce(false);

    await complete(standardSession({ customer: 'cus_stranger', subscription: 'sub_trial' }));

    expect(alerts()[0]).toContain('the email to the buyer did not send');
    expect(alerts()[0]).not.toContain('emailed set-password link');
  });

  it.each([['premium'], ['admin']])(
    'still leaves a %s account as it was when the cancelled trial is delivered again',
    async (plan) => {
      addCustomer('cus_stranger');
      addSubscription('sub_trial', 'cus_stranger', 'canceled');
      seedProfiles(profile({ plan }));

      expect((await complete(standardSession({ customer: 'cus_stranger', subscription: 'sub_trial' }))).status).toBe(
        200
      );

      expect(storedProfile('user-payer')).toEqual(comped(plan));
      expect(h.stripe.customerUpdates).toEqual([]);
    }
  );
});

describe('a standard signed-out trial delivered twice at once', () => {
  it('keeps the trial when the other delivery linked the account between its two lookups', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_std', 'cus_guest', 'trialing');
    const linked = () =>
      profile({
        plan: 'premium',
        stripe_customer_id: 'cus_guest',
        stripe_subscription_id: 'sub_std',
        subscription_status: 'trialing',
      });
    seedProfiles(linked());
    // The lookup by customer ran just before the other delivery's write, so it missed.
    h.db.current.failOn({ table: 'user_profiles', op: 'select', result: { data: null, error: null }, times: 1 });

    expect((await complete(standardSession())).status).toBe(200);

    expect(h.stripe.subscriptions.find((s) => s.id === 'sub_std')!.status).toBe('trialing');
    expect(storedProfile('user-payer')).toEqual(linked());
    expect(sendReturningSubscriberEmail).not.toHaveBeenCalled();
    expect(alerts()).toEqual([]);
  });
});

describe('the rest of the signed-out path', () => {
  it('answers a standard checkout whose login already exists as before: a permanent error, no sale alert', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_std', 'cus_guest');
    h.auth.users = [{ id: 'user-elsewhere', email: PAYER_EMAIL }];
    seedProfiles(profile({ id: 'user-elsewhere', email: 'changed@example.com' }));

    const res = await complete(standardSession());

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ received: true, error: 'Permanent webhook error' });
    expect(unlinkedLines()).toEqual([]);
  });

  it('answers 500 when the re-read after an existing login fails', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    h.auth.users = [{ id: 'user-elsewhere', email: PAYER_EMAIL }];
    seedProfiles(profile({ id: 'user-elsewhere', email: 'changed@example.com' }));
    const failure = h.db.current.failOn({
      table: 'user_profiles',
      op: 'select',
      skip: 2,
      result: { data: null, error: { message: 'statement timeout' } },
    });

    expect((await complete(saleSession())).status).toBe(500);
    expect(failure.hits).toBe(1);
    expect(unlinkedLines()).toEqual([]);
  });

  it('answers 500 when the refund lookup fails, so the lifecycle is decided on a retry', async () => {
    addCustomer('cus_payer');
    seedProfiles(profile({ plan: 'premium', stripe_customer_id: 'cus_payer', subscription_status: 'active' }));
    h.db.current.failOn({ table: 'user_profiles', op: 'select', result: { data: null, error: { message: 'down' } } });

    const res = await deliver('charge.refunded', { id: 'ch_paid', customer: 'cus_payer', refunded: true });

    expect(res.status).toBe(500);
    expect(setLifecycle).not.toHaveBeenCalled();
  });

  it('touches no profile but the one it links', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(profile(), profile({ id: 'user-other', email: 'other@example.com' }));

    expect((await complete(saleSession())).status).toBe(200);

    expect(storedProfile('user-other')).toEqual({
      id: 'user-other',
      email: 'other@example.com',
      plan: 'free',
      stripe_customer_id: null,
      stripe_subscription_id: null,
      subscription_status: null,
      subscription_period_end: null,
      cancel_at_period_end: false,
    });
    expect(storedProfile('user-payer')).toMatchObject({ stripe_customer_id: 'cus_guest' });
  });

  it('tells the owner the buyer was promised a refund when the refund email sends', async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(profile({ plan: 'premium' }));

    await complete(saleSession());

    expect(alerts()[0]).toContain('The buyer was emailed that this purchase will be refunded within one business day.');
    expect(alerts()[0]).not.toContain('did not send');
  });

  it("tells the owner when the buyer's refund email did not send", async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');
    seedProfiles(profile({ plan: 'premium' }));
    vi.mocked(sendDuplicatePurchaseEmail).mockResolvedValueOnce(false);

    await complete(saleSession());

    expect(alerts()[0]).toContain('The refund email to the buyer did not send');
    expect(alerts()[0]).not.toContain('The buyer was emailed');
  });

  it("names a sale's events after that sale", async () => {
    addCustomer('cus_guest');
    addSubscription('sub_sale', 'cus_guest');

    await complete(saleSession({ metadata: { promotion: 'spring-2027' } }));
    await deliver(
      'checkout.session.expired',
      saleSession({ status: 'expired', metadata: { promotion: 'spring-2027' } })
    );

    expect(gaEvents().map((event) => event.name)).toEqual([
      'subscription_completed',
      'spring_sale_purchase_completed',
      'spring_sale_checkout_expired',
    ]);
  });
});
