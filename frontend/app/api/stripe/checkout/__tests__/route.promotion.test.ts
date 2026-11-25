import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type Stripe from 'stripe';
import { filteringClientMock } from '@/test/supabase-mock';

/**
 * Sale checkouts against a stateful Stripe double. It models what the route depends on and refuses
 * what Stripe refuses: `discounts` beside `allow_promotion_codes`, a line item with no price, an
 * `expires_at` outside 30 minutes to 24 hours of its own clock, and expiring a session that is no
 * longer open. Lists honour `customer` and `status`, answer newest first, and page at 10 with
 * `has_more`.
 */

interface SubRow {
  id: string;
  customer: string;
  status: Stripe.Subscription.Status;
  created: number;
}

interface SessionRow {
  id: string;
  customer: string | null;
  status: 'open' | 'complete' | 'expired';
  created: number;
}

const { stripeState, mockGetUser, db } = vi.hoisted(() => ({
  stripeState: {
    subscriptions: [] as SubRow[],
    sessions: [] as SessionRow[],
    /** Every call the route made, in order, as `<resource>.<method>`. */
    calls: [] as Array<{ name: string; params: unknown }>,
    created: [] as Array<Record<string, unknown>>,
    onSessionsList: null as null | (() => void),
    /** Runs after each subscription list has answered, as when Stripe changes a subscription between two reads. */
    onSubscriptionsList: null as null | ((params: { status?: string }) => void),
    onExpire: null as null | ((id: string) => void),
    nextSessionId: 0,
  },
  mockGetUser: vi.fn(),
  db: { current: null as ReturnType<typeof import('@/test/supabase-mock').filteringClientMock> | null },
}));

const nowSeconds = () => Math.floor(Date.now() / 1000);
const newestFirst = <T extends { created: number; id: string }>(rows: T[]) =>
  [...rows].sort((a, b) => b.created - a.created || b.id.localeCompare(a.id));

vi.mock('@/lib/stripe/server', () => ({
  stripe: {
    customers: {
      create: vi.fn(async (params: unknown) => {
        stripeState.calls.push({ name: 'customers.create', params });
        return { id: 'cus_created' };
      }),
    },
    subscriptions: {
      list: vi.fn(async (params: { customer?: string; status?: string; limit?: number }) => {
        stripeState.calls.push({ name: 'subscriptions.list', params });
        const rows = newestFirst(
          stripeState.subscriptions.filter(
            (s) =>
              (params.customer === undefined || s.customer === params.customer) &&
              (params.status === 'all' || params.status === undefined
                ? params.status === 'all' || s.status !== 'canceled'
                : s.status === params.status)
          )
        );
        const limit = params.limit ?? 10;
        const answer = { data: rows.slice(0, limit).map((row) => ({ ...row })), has_more: rows.length > limit };
        stripeState.onSubscriptionsList?.(params);
        return answer;
      }),
    },
    checkout: {
      sessions: {
        list: vi.fn(async (params: { customer?: string; status?: string; starting_after?: string; limit?: number }) => {
          stripeState.calls.push({ name: 'checkout.sessions.list', params });
          stripeState.onSessionsList?.();
          let rows = newestFirst(
            stripeState.sessions.filter(
              (s) =>
                (params.customer === undefined || s.customer === params.customer) &&
                (params.status === undefined || s.status === params.status)
            )
          );
          if (params.starting_after) rows = rows.slice(rows.findIndex((r) => r.id === params.starting_after) + 1);
          const limit = params.limit ?? 10;
          return { data: rows.slice(0, limit).map((r) => ({ ...r })), has_more: rows.length > limit };
        }),
        expire: vi.fn(async (id: string) => {
          stripeState.calls.push({ name: 'checkout.sessions.expire', params: id });
          stripeState.onExpire?.(id);
          const session = stripeState.sessions.find((s) => s.id === id);
          if (!session || session.status !== 'open') {
            throw new Error('Only Checkout Sessions with a status of `open` can be expired.');
          }
          session.status = 'expired';
          return { ...session };
        }),
        retrieve: vi.fn(async (id: string) => {
          stripeState.calls.push({ name: 'checkout.sessions.retrieve', params: id });
          return { ...stripeState.sessions.find((s) => s.id === id) };
        }),
        create: vi.fn(async (params: Record<string, unknown>) => {
          stripeState.calls.push({ name: 'checkout.sessions.create', params });
          if (!(params.line_items as Array<{ price?: string }> | undefined)?.[0]?.price) {
            throw new Error('Missing required param: line_items[0][price].');
          }
          if (params.discounts !== undefined && params.allow_promotion_codes !== undefined) {
            throw new Error('You may only specify one of these parameters: allow_promotion_codes, discounts.');
          }
          if (params.expires_at !== undefined) {
            const expiresAt = params.expires_at as number;
            if (expiresAt < nowSeconds() + 30 * 60 || expiresAt > nowSeconds() + 24 * 60 * 60) {
              throw new Error('The `expires_at` timestamp must be between 30 minutes and 24 hours from now.');
            }
          }
          const id = `cs_created_${++stripeState.nextSessionId}`;
          stripeState.sessions.push({
            id,
            customer: (params.customer as string) ?? null,
            status: 'open',
            created: nowSeconds(),
          });
          stripeState.created.push(params);
          return { id, url: `https://checkout.stripe.com/c/pay/${id}` };
        }),
      },
    },
  },
  getStripePriceIds: () => ({
    MONTHLY: process.env.STRIPE_PRICE_MONTHLY || process.env.NEXT_PUBLIC_STRIPE_PRICE_MONTHLY || '',
    YEARLY: process.env.STRIPE_PRICE_YEARLY || process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY || '',
  }),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn().mockResolvedValue({ get: vi.fn(), getAll: vi.fn().mockReturnValue([]), set: vi.fn() }),
}));
vi.mock('@/lib/api/rateLimit', () => ({ checkRateLimit: vi.fn(() => true), getClientIp: vi.fn(() => '203.0.113.1') }));
vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: vi.fn(async () => ({ auth: { getUser: mockGetUser }, from: db.current!.client.from })),
}));
vi.mock('@/lib/supabase/service', () => ({ getSupabaseAdmin: () => db.current!.client }));

import { POST } from '../route';

const USER_ID = '11111111-1111-1111-1111-111111111111';
const BLACK_FRIDAY = { startsAt: Date.parse('2026-11-25T07:00:00Z'), endsAt: Date.parse('2026-12-01T07:00:00Z') };
const DURING = new Date('2026-11-28T12:00:00Z');
const ENDED_NOTICE = 'The Black Friday sale has ended.';
const HOUR = 60 * 60 * 1000;
const MINUTE = 60 * 1000;

function request(body: Record<string, unknown>): Request {
  return new Request('http://localhost/api/stripe/checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

const saleBody = (overrides: Record<string, unknown> = {}) => ({
  priceId: 'price_public_yearly',
  promotion: 'black-friday-2026',
  ...overrides,
});

function signIn(profile: Record<string, unknown> = {}) {
  mockGetUser.mockResolvedValue({ data: { user: { id: USER_ID, email: 'parent@example.com' } }, error: null });
  db.current!.tableRows.user_profiles = [
    { id: USER_ID, plan: 'free', subscription_status: null, stripe_customer_id: 'cus_parent', ...profile },
  ];
}

function signOut() {
  mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
}

function subscription(status: Stripe.Subscription.Status, created: number, customer = 'cus_parent'): SubRow {
  return { id: `sub_${status}_${created}`, customer, status, created };
}

function openSession(id: string, customer: string | null = 'cus_parent', created = 100): SessionRow {
  return { id, customer, status: 'open', created };
}

const callNames = () => stripeState.calls.map((call) => call.name);
const stripeCalls = (name: string) => stripeState.calls.filter((call) => call.name === name);
const createdParams = () => stripeState.created.at(-1) as Record<string, Record<string, unknown>>;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(DURING);
  stripeState.subscriptions = [];
  stripeState.sessions = [];
  stripeState.calls = [];
  stripeState.created = [];
  stripeState.onSessionsList = null;
  stripeState.onSubscriptionsList = null;
  stripeState.onExpire = null;
  stripeState.nextSessionId = 0;
  db.current = filteringClientMock();
  vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://pitchrank.io');
  vi.stubEnv('NEXT_PUBLIC_STRIPE_PRICE_MONTHLY', 'price_public_monthly');
  vi.stubEnv('NEXT_PUBLIC_STRIPE_PRICE_YEARLY', 'price_public_yearly');
  vi.stubEnv('STRIPE_PRICE_MONTHLY', 'price_server_monthly');
  vi.stubEnv('STRIPE_PRICE_YEARLY', 'price_server_yearly');
  vi.stubEnv('STRIPE_COUPON_BLACK_FRIDAY_2026', 'coupon_bf_test');
  vi.stubEnv('PROMOTIONS_DISABLED', '');
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('a sale checkout session', () => {
  it('applies the coupon in place of promotion codes, with no trial, and records the sale signed out', async () => {
    signOut();

    const res = await POST(
      request(saleBody({ attribution: { campaign: 'black-friday-2026', source: 'banner', utm_source: 'facebook' } }))
    );

    expect(res.status).toBe(200);
    const params = createdParams();
    expect(params.discounts).toEqual([{ coupon: 'coupon_bf_test' }]);
    expect(params).not.toHaveProperty('allow_promotion_codes');
    expect(params.line_items).toEqual([{ price: 'price_public_yearly', quantity: 1 }]);
    const saleMetadata = {
      promotion: 'black-friday-2026',
      segment: 'signed_out',
      campaign: 'black-friday-2026',
      source: 'banner',
      utm_source: 'facebook',
    };
    expect(params.metadata).toEqual({
      anonymous_checkout: 'true',
      browser_key_hash: expect.any(String),
      ...saleMetadata,
    });
    expect(params.subscription_data).toEqual({ metadata: { anonymous_checkout: 'true', ...saleMetadata } });
    expect(res.cookies.get('checkout_browser')).toBeDefined();
  });

  it.each([
    ['new', [] as SubRow[]],
    ['returning', [subscription('canceled', 50)]],
  ])('labels a signed-in buyer %s on both the session and the subscription', async (segment, subs) => {
    signIn();
    stripeState.subscriptions = subs;

    await POST(request(saleBody()));

    const params = createdParams();
    expect(params.subscription_data).toEqual({
      metadata: { supabase_user_id: USER_ID, promotion: 'black-friday-2026', segment },
    });
    expect(params.metadata).toEqual({ supabase_user_id: USER_ID, promotion: 'black-friday-2026', segment });
    expect(params.discounts).toEqual([{ coupon: 'coupon_bf_test' }]);
    expect(params.customer).toBe('cus_parent');
  });

  it('caps attribution again on the server and drops keys it does not know', async () => {
    signOut();

    await POST(
      request(saleBody({ attribution: { utm_source: `fb\u0007${'x'.repeat(200)}`, utm_term: 'nope', gclid: 'nope' } }))
    );

    expect(createdParams().metadata).toEqual(expect.objectContaining({ utm_source: `fb${'x'.repeat(98)}` }));
    expect(createdParams().metadata).not.toHaveProperty('utm_term');
    expect(createdParams().metadata).not.toHaveProperty('gclid');
  });
});

describe('the price a sale charges', () => {
  it('charges the yearly price the page posts, and refuses the server-only one', async () => {
    signOut();

    expect((await POST(request(saleBody({ priceId: 'price_public_yearly' })))).status).toBe(200);
    expect(createdParams().line_items).toEqual([{ price: 'price_public_yearly', quantity: 1 }]);

    const refused = await POST(request(saleBody({ priceId: 'price_server_yearly' })));
    expect(refused.status).toBe(400);
    expect(await refused.json()).toEqual({ error: 'Invalid price ID' });
  });

  it('accepts the server yearly price only when the public one is unset', async () => {
    signOut();
    vi.stubEnv('NEXT_PUBLIC_STRIPE_PRICE_YEARLY', '');

    expect((await POST(request(saleBody({ priceId: 'price_server_yearly' })))).status).toBe(200);
    expect(createdParams().line_items).toEqual([{ price: 'price_server_yearly', quantity: 1 }]);
  });

  it.each([[undefined], ['']])('refuses %j when no yearly price is configured', async (priceId) => {
    signIn();
    stripeState.sessions = [openSession('cs_open')];
    vi.stubEnv('NEXT_PUBLIC_STRIPE_PRICE_YEARLY', '');
    vi.stubEnv('STRIPE_PRICE_YEARLY', '');

    const res = await POST(request(saleBody({ priceId })));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'Invalid price ID' });
    expect(stripeState.calls).toEqual([]);
  });

  it('refuses a yearly price variable that holds no price id before expiring anything', async () => {
    signIn();
    stripeState.sessions = [openSession('cs_open')];
    vi.stubEnv('NEXT_PUBLIC_STRIPE_PRICE_YEARLY', 'prod_yearly');

    const res = await POST(request(saleBody({ priceId: 'prod_yearly' })));

    expect(res.status).toBe(400);
    expect(stripeState.calls).toEqual([]);
    expect(stripeState.sessions[0].status).toBe('open');
  });

  it.each([['price_public_monthly'], ['price_unknown'], ['']])('refuses %j with no fallback', async (priceId) => {
    signOut();

    const res = await POST(request(saleBody({ priceId })));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'Invalid price ID' });
    expect(stripeCalls('checkout.sessions.create')).toEqual([]);
  });
});

describe('a sale that is not on', () => {
  it('refuses an unknown sale', async () => {
    signOut();

    const res = await POST(request(saleBody({ promotion: 'cyber-week-1999' })));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "This offer isn't available." });
  });

  it.each([
    ['before it starts', '2026-11-25T06:59:59Z', ''],
    ['at its end', '2026-12-01T07:00:00Z', ''],
    ['after it ends', '2026-12-02T00:00:00Z', ''],
    ['with the kill switch on', '2026-11-28T12:00:00Z', 'true'],
  ])('refuses it %s with the ended notice, not a 500', async (_label, iso, disabled) => {
    signOut();
    vi.setSystemTime(new Date(iso));
    vi.stubEnv('PROMOTIONS_DISABLED', disabled);

    const res = await POST(request(saleBody()));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: ENDED_NOTICE });
    expect(stripeState.calls).toEqual([]);
  });
});

describe('when a sale checkout closes', () => {
  it.each([
    ['48 hours before the end, 23 hours on', BLACK_FRIDAY.endsAt - 48 * HOUR, (now: number) => now + 23 * HOUR],
    ['10 hours before the end, at the end', BLACK_FRIDAY.endsAt - 10 * HOUR, () => BLACK_FRIDAY.endsAt],
    ['20 minutes before the end, 31 minutes on', BLACK_FRIDAY.endsAt - 20 * MINUTE, (now: number) => now + 31 * MINUTE],
  ])('opened %s', async (_label, now, closesAt) => {
    signOut();
    vi.setSystemTime(now);

    await POST(request(saleBody()));

    expect(createdParams().expires_at).toBe(Math.floor(closesAt(now) / 1000));
  });
});

describe('who a sale refuses', () => {
  it('refuses a premium account before any Stripe call', async () => {
    signIn({ plan: 'premium', subscription_status: 'past_due' });

    const res = await POST(request(saleBody()));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'You already have an active subscription' });
    expect(stripeState.calls).toEqual([]);
  });

  it('refuses a comped account with no Stripe customer without creating one', async () => {
    signIn({ plan: 'premium', stripe_customer_id: null });

    expect((await POST(request(saleBody()))).status).toBe(400);
    expect(callNames()).not.toContain('customers.create');
    expect(db.current!.tableRows.user_profiles[0].stripe_customer_id).toBeNull();
  });

  it.each([['active'], ['trialing'], ['past_due']] as const)(
    'refuses a free profile whose %s subscription sits behind ten newer cancelled ones',
    async (status) => {
      signIn({ plan: 'free' });
      stripeState.subscriptions = [
        subscription(status, 1),
        ...Array.from({ length: 10 }, (_, i) => subscription('canceled', 10 + i)),
      ];

      const res = await POST(request(saleBody()));

      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ error: 'You already have an active subscription' });
      expect(callNames()).not.toContain('checkout.sessions.create');
    }
  );

  it.each([['active'], ['trialing'], ['past_due']] as const)(
    'leaves a buyer refused for a %s subscription their open checkout',
    async (status) => {
      signIn();
      stripeState.subscriptions = [subscription(status, 1)];
      stripeState.sessions = [openSession('cs_open')];

      expect((await POST(request(saleBody()))).status).toBe(400);
      expect(callNames()).not.toContain('checkout.sessions.expire');
      expect(stripeState.sessions[0].status).toBe('open');
    }
  );

  it('fails on a missing coupon before expiring anything', async () => {
    signIn();
    stripeState.sessions = [openSession('cs_open')];
    vi.stubEnv('STRIPE_COUPON_BLACK_FRIDAY_2026', '');

    const res = await POST(request(saleBody()));

    expect(res.status).toBe(500);
    expect(stripeState.calls).toEqual([]);
    expect(stripeState.sessions[0].status).toBe('open');
  });

  it("writes the new customer onto the buyer's profile and no other", async () => {
    signIn({ stripe_customer_id: null });
    db.current!.tableRows.user_profiles.push({ id: 'someone-else', plan: 'free', stripe_customer_id: null });

    expect((await POST(request(saleBody()))).status).toBe(200);

    expect(db.current!.tableRows.user_profiles.find((row) => row.id === USER_ID)!.stripe_customer_id).toBe(
      'cus_created'
    );
    expect(db.current!.tableRows.user_profiles.find((row) => row.id === 'someone-else')!.stripe_customer_id).toBeNull();
  });

  it('answers 500, not the race 409, when the customer write itself fails', async () => {
    signIn({ stripe_customer_id: null });
    db.current!.failOn({
      table: 'user_profiles',
      op: 'update',
      result: { data: null, error: { code: '57014', message: 'canceling statement due to statement timeout' } },
    });

    const res = await POST(request(saleBody()));

    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ error: 'Failed to link billing account. Please try again.' });
    expect(callNames()).not.toContain('checkout.sessions.create');
  });

  it('keeps the customer a signed-out purchase linked while the new one was being created', async () => {
    signIn({ stripe_customer_id: null });
    const create = vi.mocked((await import('@/lib/stripe/server')).stripe.customers.create);
    create.mockImplementationOnce(async (params: unknown) => {
      stripeState.calls.push({ name: 'customers.create', params });
      db.current!.tableRows.user_profiles[0].stripe_customer_id = 'cus_linked_meanwhile';
      return { id: 'cus_created' } as Stripe.Response<Stripe.Customer>;
    });

    const res = await POST(request(saleBody()));

    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: 'Your account changed while checkout was starting. Please try again.' });
    expect(db.current!.tableRows.user_profiles[0].stripe_customer_id).toBe('cus_linked_meanwhile');
    expect(callNames()).not.toContain('checkout.sessions.create');
  });

  it('lists no subscriptions for a profile with no Stripe customer, scoped or not', async () => {
    signIn({ stripe_customer_id: null });

    expect((await POST(request(saleBody()))).status).toBe(200);
    expect(callNames()).not.toContain('subscriptions.list');
    expect(callNames()).toEqual(['customers.create', 'checkout.sessions.create']);
    expect(createdParams().customer).toBe('cus_created');
    expect(createdParams().metadata).toEqual(expect.objectContaining({ segment: 'new' }));
  });

  it('scopes every list it makes to the buyer', async () => {
    signIn();
    stripeState.sessions = [openSession('cs_open')];

    await POST(request(saleBody()));

    const lists = stripeState.calls.filter((call) => call.name.endsWith('.list'));
    expect(lists.length).toBeGreaterThan(0);
    expect(lists.every((call) => (call.params as { customer?: string }).customer === 'cus_parent')).toBe(true);
  });
});

describe('a checkout completed while the others expire', () => {
  it('refuses the sale when an earlier checkout completed just before the listing', async () => {
    signIn();
    stripeState.onSessionsList = () => {
      stripeState.subscriptions.push(subscription('active', 500));
    };

    const res = await POST(request(saleBody()));

    expect(res.status).toBe(400);
    expect(callNames()).not.toContain('checkout.sessions.create');
  });

  it('tolerates Stripe refusing to expire a session that just completed, then refuses the sale', async () => {
    signIn();
    stripeState.sessions = [openSession('cs_paying')];
    stripeState.onExpire = (id) => {
      stripeState.sessions.find((s) => s.id === id)!.status = 'complete';
      stripeState.subscriptions.push(subscription('active', 500));
    };

    const res = await POST(request(saleBody()));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'You already have an active subscription' });
    expect(callNames()).toContain('checkout.sessions.retrieve');
  });

  it('fails on any other expire error', async () => {
    signIn();
    stripeState.sessions = [openSession('cs_open')];
    stripeState.onExpire = () => {
      throw new Error('Stripe is down');
    };

    const res = await POST(request(saleBody()));

    expect(res.status).toBe(500);
    expect(callNames()).not.toContain('checkout.sessions.create');
  });
});

describe('one open checkout per customer around a sale', () => {
  it("expires every one of the buyer's open checkouts, across pages, before creating the sale's", async () => {
    signIn();
    stripeState.sessions = [
      ...Array.from({ length: 12 }, (_, i) =>
        openSession(`cs_mine_${String(i).padStart(2, '0')}`, 'cus_parent', 100 + i)
      ),
      openSession('cs_someone_else', 'cus_other', 150),
    ];

    expect((await POST(request(saleBody()))).status).toBe(200);

    const expired = stripeCalls('checkout.sessions.expire').map((call) => call.params);
    expect(expired).toHaveLength(12);
    expect(new Set(expired)).toEqual(
      new Set(
        stripeState.sessions.filter((s) => s.customer === 'cus_parent' && s.id.startsWith('cs_mine')).map((s) => s.id)
      )
    );
    expect(stripeCalls('checkout.sessions.list').length).toBe(2);
    const createIndex = callNames().indexOf('checkout.sessions.create');
    expect(callNames().lastIndexOf('checkout.sessions.expire')).toBeLessThan(createIndex);
    expect(stripeState.sessions.find((s) => s.id === 'cs_someone_else')!.status).toBe('open');
  });

  it.each([
    ['while the sale is live', DURING.getTime(), ''],
    ['5 minutes after it ends, while a late sale checkout is open', BLACK_FRIDAY.endsAt + 5 * MINUTE, ''],
    ['after the kill switch', DURING.getTime(), 'true'],
  ])('expires an open sale checkout before a standard one %s', async (_label, now, disabled) => {
    signIn();
    vi.setSystemTime(now);
    vi.stubEnv('PROMOTIONS_DISABLED', disabled);
    stripeState.sessions = [openSession('cs_open_sale')];

    expect((await POST(request({ priceId: 'price_public_yearly' }))).status).toBe(200);

    expect(stripeCalls('checkout.sessions.expire').map((call) => call.params)).toEqual(['cs_open_sale']);
    expect(callNames().indexOf('checkout.sessions.expire')).toBeLessThan(
      callNames().indexOf('checkout.sessions.create')
    );
  });

  it('makes no open-session calls for a standard checkout 25 hours after the end', async () => {
    signIn();
    vi.setSystemTime(BLACK_FRIDAY.endsAt + 25 * HOUR);
    stripeState.sessions = [openSession('cs_open')];

    expect((await POST(request({ priceId: 'price_public_yearly' }))).status).toBe(200);

    expect(callNames().filter((name) => name.startsWith('checkout.'))).toEqual(['checkout.sessions.create']);
  });
});

describe('a standard checkout', () => {
  async function standardParams(now: number, body: Record<string, unknown>) {
    stripeState.calls = [];
    vi.setSystemTime(now);
    await POST(request(body));
    return createdParams();
  }

  it.each([['price_public_monthly'], ['price_public_yearly']])(
    'creates %s exactly as before, during the sale as outside it',
    async (priceId) => {
      signIn();
      const outside = await standardParams(Date.parse('2026-10-01T12:00:00Z'), { priceId });
      const during = await standardParams(DURING.getTime(), { priceId });

      expect(outside).toEqual({
        mode: 'subscription',
        line_items: [{ price: priceId, quantity: 1 }],
        success_url: 'https://pitchrank.io/upgrade/success?session_id={CHECKOUT_SESSION_ID}',
        cancel_url: 'https://pitchrank.io/upgrade',
        allow_promotion_codes: true,
        billing_address_collection: 'auto',
        customer: 'cus_parent',
        metadata: { supabase_user_id: USER_ID },
        subscription_data: { trial_period_days: 7, metadata: { supabase_user_id: USER_ID } },
        customer_update: { address: 'auto', name: 'auto' },
      });
      expect(during).toEqual(outside);
    }
  );

  it('keeps the trial and promotion codes for a signed-out buyer during the sale', async () => {
    signOut();

    await POST(request({ priceId: 'price_public_yearly' }));

    expect(createdParams()).toEqual(
      expect.objectContaining({
        allow_promotion_codes: true,
        subscription_data: { trial_period_days: 7, metadata: { anonymous_checkout: 'true' } },
      })
    );
    expect(createdParams()).not.toHaveProperty('expires_at');
    expect(callNames()).toEqual(['checkout.sessions.create']);
  });

  it.each([['active'], ['trialing']] as const)(
    'refuses a free profile outside the sale whose %s subscription sits behind ten newer cancelled ones',
    async (status) => {
      signIn({ plan: 'free' });
      vi.setSystemTime(Date.parse('2026-10-01T12:00:00Z'));
      stripeState.subscriptions = [
        subscription(status, 1),
        ...Array.from({ length: 10 }, (_, i) => subscription('canceled', 10 + i)),
      ];

      const res = await POST(request({ priceId: 'price_public_yearly' }));

      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ error: 'You already have an active subscription' });
      expect(callNames()).not.toContain('checkout.sessions.create');
    }
  );

  it('refuses during the sale before expiring the open checkout of a buyer whose active subscription is buried', async () => {
    signIn({ plan: 'free' });
    stripeState.subscriptions = [
      subscription('active', 1),
      ...Array.from({ length: 10 }, (_, i) => subscription('canceled', 10 + i)),
    ];
    stripeState.sessions = [openSession('cs_open')];

    expect((await POST(request({ priceId: 'price_public_yearly' }))).status).toBe(400);
    expect(callNames()).not.toContain('checkout.sessions.expire');
    expect(stripeState.sessions[0].status).toBe('open');
  });

  it('offers no trial to a customer whose only history is cancelled', async () => {
    signIn({ plan: 'free' });
    vi.setSystemTime(Date.parse('2026-10-01T12:00:00Z'));
    stripeState.subscriptions = [subscription('canceled', 1)];

    expect((await POST(request({ priceId: 'price_public_yearly' }))).status).toBe(200);
    expect(createdParams().subscription_data).toEqual({ metadata: { supabase_user_id: USER_ID } });
  });

  it('lets a premium past_due profile start one, which is how it fixes its billing', async () => {
    signIn({ plan: 'premium', subscription_status: 'past_due' });
    vi.setSystemTime(Date.parse('2026-10-01T12:00:00Z'));
    stripeState.subscriptions = [subscription('past_due', 1)];

    expect((await POST(request({ priceId: 'price_public_yearly' }))).status).toBe(200);
    expect(callNames()).toContain('checkout.sessions.create');
  });

  it.each([['active'], ['trialing']])('refuses a premium %s profile before any Stripe call', async (status) => {
    signIn({ plan: 'premium', subscription_status: status });
    vi.setSystemTime(Date.parse('2026-10-01T12:00:00Z'));

    const res = await POST(request({ priceId: 'price_public_yearly' }));

    expect(res.status).toBe(400);
    expect(stripeState.calls).toEqual([]);
  });

  it('refuses a trial that turns active during the check, even behind a newer cancelled subscription', async () => {
    signIn({ plan: 'free' });
    vi.setSystemTime(Date.parse('2026-10-01T12:00:00Z'));
    stripeState.subscriptions = [subscription('trialing', 1), subscription('canceled', 2)];
    // The trial converts as soon as any active list has been read.
    stripeState.onSubscriptionsList = (params) => {
      if (params.status === 'active') stripeState.subscriptions[0].status = 'active';
    };

    const res = await POST(request({ priceId: 'price_public_yearly' }));

    expect(res.status).toBe(400);
    expect(callNames()).not.toContain('checkout.sessions.create');
  });

  it('refuses a subscription that starts while the refusals are being read, rather than offer a trial', async () => {
    signIn({ plan: 'free' });
    vi.setSystemTime(Date.parse('2026-10-01T12:00:00Z'));
    // Another tab's checkout completes just after the last filtered list was read.
    stripeState.onSubscriptionsList = (params) => {
      if (params.status === 'active' && stripeState.subscriptions.length === 0) {
        stripeState.subscriptions.push(subscription('trialing', 999));
      }
    };

    const res = await POST(request({ priceId: 'price_public_yearly' }));

    expect(res.status).toBe(400);
    expect(callNames()).not.toContain('checkout.sessions.create');
  });

  it('lets a past_due subscriber start one during the sale, which is how they fix their billing', async () => {
    signIn();
    stripeState.subscriptions = [subscription('past_due', 1)];

    expect((await POST(request({ priceId: 'price_public_yearly' }))).status).toBe(200);
    expect(callNames()).toContain('checkout.sessions.create');
  });

  it('is refused when a sale checkout is paid while the open ones expire', async () => {
    signIn();
    stripeState.sessions = [openSession('cs_sale_paying')];
    stripeState.onExpire = (id) => {
      stripeState.sessions.find((s) => s.id === id)!.status = 'complete';
      stripeState.subscriptions.push(subscription('active', 500));
    };

    const res = await POST(request({ priceId: 'price_public_yearly' }));

    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: 'You already have an active subscription' });
    expect(callNames()).not.toContain('checkout.sessions.create');
  });

  it('makes no open-session calls in the week before the sale', async () => {
    signIn();
    vi.setSystemTime(BLACK_FRIDAY.startsAt - 2 * 24 * 60 * MINUTE);
    stripeState.sessions = [openSession('cs_open')];

    expect((await POST(request({ priceId: 'price_public_yearly' }))).status).toBe(200);

    expect(callNames().filter((name) => name.startsWith('checkout.'))).toEqual(['checkout.sessions.create']);
  });
});

describe("a late sale checkout's close time", () => {
  it('is measured when the session is created, not when the request began', async () => {
    signIn();
    const requestStart = BLACK_FRIDAY.endsAt - 20 * MINUTE;
    vi.setSystemTime(requestStart);
    stripeState.sessions = [openSession('cs_open')];
    // Slow lookups: two minutes pass before the session is created.
    stripeState.onSessionsList = () => vi.setSystemTime(requestStart + 2 * MINUTE);

    expect((await POST(request(saleBody()))).status).toBe(200);

    expect(createdParams().expires_at).toBe(Math.floor((requestStart + 2 * MINUTE + 31 * MINUTE) / 1000));
  });
});
