import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const TEAM_PATH = '/teams/11111111-1111-1111-1111-111111111111';
const SESSION_ID = 'cs_test_guest';
const EMAIL = 'buyer@example.com';
const MINUTE = 60 * 1000;
// sha256 of 'browser-key', the cookie value the buyer's browser holds in these tests.
const BROWSER_KEY_HASH = '82c971973ccbf22b209995e2c1505e04201d2a488e19d471feb69662b8fb93d0';

const {
  mockSessionsRetrieve,
  mockCaller,
  mockMaybeSingle,
  mockEq,
  mockGetUserById,
  mockGenerateLink,
  mockVerifyOtp,
  mockCheckRateLimit,
  mockCookieGet,
} = vi.hoisted(() => ({
  mockSessionsRetrieve: vi.fn(),
  mockCaller: vi.fn(),
  mockMaybeSingle: vi.fn(),
  mockEq: vi.fn(),
  mockGetUserById: vi.fn(),
  mockGenerateLink: vi.fn(),
  mockVerifyOtp: vi.fn(),
  mockCheckRateLimit: vi.fn(),
  mockCookieGet: vi.fn(),
}));

vi.mock('next/headers', () => ({
  cookies: async () => ({ get: mockCookieGet }),
}));

vi.mock('@/lib/stripe/server', () => ({
  stripe: { checkout: { sessions: { retrieve: mockSessionsRetrieve } } },
  isSessionPaymentSettled: (s: { payment_status?: string }) =>
    s.payment_status === 'paid' || s.payment_status === 'no_payment_required',
}));
vi.mock('@/lib/api/rateLimit', () => ({
  checkRateLimit: mockCheckRateLimit,
  getClientIp: () => '203.0.113.1',
}));
vi.mock('@/lib/api/optionalAuth', () => ({
  optionalAuth: async () => ({ user: mockCaller(), supabase: null }),
}));
vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: async () => ({ auth: { verifyOtp: mockVerifyOtp } }),
}));
vi.mock('@/lib/supabase/service', () => ({
  getSupabaseAdmin: () => ({
    from: (table: string) => ({
      select: (columns: string) => ({
        eq: (column: string, value: string) => {
          mockEq(table, columns, column, value);
          return { maybeSingle: mockMaybeSingle };
        },
      }),
    }),
    auth: { admin: { getUserById: mockGetUserById, generateLink: mockGenerateLink } },
  }),
}));

import { POST } from '../route';

function guestSession(overrides: Record<string, unknown> = {}) {
  return {
    id: SESSION_ID,
    status: 'complete',
    payment_status: 'no_payment_required',
    customer: 'cus_guest',
    metadata: { anonymous_checkout: 'true', browser_key_hash: BROWSER_KEY_HASH, return_to: TEAM_PATH },
    ...overrides,
  };
}

function newAccount(overrides: Record<string, unknown> = {}) {
  return {
    id: 'user-new',
    email: EMAIL,
    created_at: new Date(Date.now() - 5 * MINUTE).toISOString(),
    last_sign_in_at: null,
    app_metadata: { provider: 'email', checkout_session_id: SESSION_ID },
    ...overrides,
  };
}

function givenAccount(account: Record<string, unknown>) {
  mockGetUserById.mockResolvedValue({ data: { user: account }, error: null });
}

function post(body: unknown = { sessionId: SESSION_ID }, contentType = 'application/json') {
  return POST(
    new Request('http://localhost/api/stripe/checkout-login', {
      method: 'POST',
      headers: { 'Content-Type': contentType },
      body: JSON.stringify(body),
    })
  );
}

function expectNothingMinted() {
  expect(mockGenerateLink).not.toHaveBeenCalled();
  expect(mockVerifyOtp).not.toHaveBeenCalled();
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  mockCookieGet.mockImplementation((name: string) =>
    name === 'checkout_browser' ? { value: 'browser-key' } : undefined
  );
  mockCheckRateLimit.mockReturnValue(true);
  mockSessionsRetrieve.mockResolvedValue(guestSession());
  mockCaller.mockReturnValue(null);
  mockMaybeSingle.mockResolvedValue({ data: { id: 'user-new' }, error: null });
  givenAccount(newAccount());
  mockGenerateLink.mockResolvedValue({ data: { properties: { hashed_token: 'hashed-token' } }, error: null });
  mockVerifyOtp.mockResolvedValue({ data: {}, error: null });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('POST /api/stripe/checkout-login', () => {
  it('signs in the account this checkout created and opens the tapped team', async () => {
    const res = await post();

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ status: 'signed_in', next: TEAM_PATH });
    expect(res.headers.get('Cache-Control')).toBe('no-store');
    expect(mockSessionsRetrieve).toHaveBeenCalledWith(SESSION_ID);
    expect(mockEq).toHaveBeenCalledWith('user_profiles', 'id', 'stripe_customer_id', 'cus_guest');
    expect(mockGetUserById).toHaveBeenCalledWith('user-new');
    expect(mockGenerateLink).toHaveBeenCalledWith({ type: 'magiclink', email: EMAIL });
    expect(mockVerifyOtp).toHaveBeenCalledWith({ token_hash: 'hashed-token', type: 'magiclink' });
  });

  it.each([
    ['no team was tapped', { anonymous_checkout: 'true', browser_key_hash: BROWSER_KEY_HASH }],
    [
      'the stored path is not a team page',
      { anonymous_checkout: 'true', browser_key_hash: BROWSER_KEY_HASH, return_to: '//evil.example' },
    ],
  ])('falls back to rankings when %s', async (_name, metadata) => {
    mockSessionsRetrieve.mockResolvedValue(guestSession({ metadata }));

    expect(await (await post()).json()).toEqual({ status: 'signed_in', next: '/rankings' });
  });

  describe('each gate refuses alone', () => {
    it.each<[string, Record<string, unknown>]>([
      ['a session that is not complete', { status: 'open' }],
      ['an unsettled payment', { payment_status: 'unpaid' }],
      [
        "a signed-in checkout's session, even from the browser that started it",
        { metadata: { supabase_user_id: 'user-new', browser_key_hash: BROWSER_KEY_HASH, return_to: TEAM_PATH } },
      ],
      ['a session with no customer', { customer: null }],
      ['a session that never stored a browser key', { metadata: { anonymous_checkout: 'true', return_to: TEAM_PATH } }],
    ])('%s', async (_name, sessionOverrides) => {
      mockSessionsRetrieve.mockResolvedValue(guestSession(sessionOverrides));

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expectNothingMinted();
    });

    it.each<[string, Record<string, unknown>]>([
      ['a marker from a different checkout', { app_metadata: { checkout_session_id: 'cs_test_other' } }],
      ['an account that has already signed in', { last_sign_in_at: new Date().toISOString() }],
      ['an account past 30 minutes', { created_at: new Date(Date.now() - 31 * MINUTE).toISOString() }],
      ['an account whose age cannot be read', { created_at: 'not a date' }],
      ['an account with no email', { email: null }],
      ['an older account with no marker', { created_at: '2024-01-01T00:00:00Z', app_metadata: {} }],
      ['a used account with no marker', { last_sign_in_at: new Date().toISOString(), app_metadata: {} }],
    ])('%s', async (_name, accountOverrides) => {
      givenAccount(newAccount(accountOverrides));

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expectNothingMinted();
    });

    it.each<[string, { value: string } | undefined]>([
      ['a browser with no checkout cookie', undefined],
      ["a browser holding another checkout's cookie", { value: 'other-browser-key' }],
    ])('%s', async (_name, cookie) => {
      mockCookieGet.mockReturnValue(cookie);

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expectNothingMinted();
      expect(mockGetUserById).not.toHaveBeenCalled();
      expect(console.warn).toHaveBeenCalledWith('[checkout-login] Refused: not the browser that started this checkout');
      expect(console.error).not.toHaveBeenCalled();
    });

    it('a browser already signed in as someone else', async () => {
      mockCaller.mockReturnValue({ id: 'user-other' });

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expectNothingMinted();
    });
  });

  describe('while the webhook is still working', () => {
    it('waits when no profile holds this customer yet', async () => {
      mockMaybeSingle.mockResolvedValue({ data: null, error: null });

      const res = await post();

      expect(res.status).toBe(202);
      expect(await res.json()).toEqual({ status: 'pending' });
      expectNothingMinted();
    });

    it('waits when a brand-new account has no marker yet', async () => {
      givenAccount(newAccount({ app_metadata: { provider: 'email' } }));

      const res = await post();

      expect(res.status).toBe(202);
      expect(await res.json()).toEqual({ status: 'pending' });
      expectNothingMinted();
    });
  });

  describe('a caller already signed in needs no minting', () => {
    it('the buyer behind a signed-in checkout', async () => {
      mockSessionsRetrieve.mockResolvedValue(
        guestSession({ metadata: { supabase_user_id: 'user-1', return_to: TEAM_PATH } })
      );
      mockCaller.mockReturnValue({ id: 'user-1' });

      expect(await (await post()).json()).toEqual({ status: 'signed_in', next: TEAM_PATH });
      expectNothingMinted();
    });

    it('a guest whose browser this route already signed in', async () => {
      mockCaller.mockReturnValue({ id: 'user-new' });
      givenAccount(newAccount({ last_sign_in_at: new Date().toISOString() }));

      expect(await (await post()).json()).toEqual({ status: 'signed_in', next: TEAM_PATH });
      expectNothingMinted();
    });
  });

  describe('every failure answers with the email route', () => {
    it.each([
      ['no session id', {}],
      ['a session id that is not a string', { sessionId: ['cs_test_guest'] }],
    ])('%s', async (_name, body) => {
      expect(await (await post(body)).json()).toEqual({ status: 'email' });
      expect(mockSessionsRetrieve).not.toHaveBeenCalled();
    });

    it('a profile lookup error', async () => {
      mockMaybeSingle.mockResolvedValue({ data: null, error: { code: 'PGRST000' } });

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expectNothingMinted();
      expect(console.error).toHaveBeenCalledWith('[checkout-login] Profile lookup failed:', 'PGRST000');
    });

    it('an account that cannot be loaded', async () => {
      mockGetUserById.mockResolvedValue({ data: { user: newAccount() }, error: { code: 'unexpected_failure' } });

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expectNothingMinted();
      expect(console.error).toHaveBeenCalledWith('[checkout-login] Could not load account user-new');
    });

    it('a sign-in that cannot be minted', async () => {
      mockGenerateLink.mockResolvedValue({
        data: { properties: { hashed_token: 'hashed-token' } },
        error: { code: 'unexpected_failure' },
      });

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expect(mockVerifyOtp).not.toHaveBeenCalled();
      expect(console.error).toHaveBeenCalledWith('[checkout-login] Could not mint a sign-in for account user-new');
    });

    it('a minted link with no token', async () => {
      mockGenerateLink.mockResolvedValue({ data: { properties: {} }, error: null });

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expect(mockVerifyOtp).not.toHaveBeenCalled();
    });

    it('a sign-in that cannot be redeemed', async () => {
      mockVerifyOtp.mockResolvedValue({ data: {}, error: { code: 'otp_expired' } });

      expect(await (await post()).json()).toEqual({ status: 'email' });
      expect(console.error).toHaveBeenCalledWith(
        '[checkout-login] Could not redeem the sign-in for account user-new:',
        'otp_expired'
      );
    });
  });

  it('refuses a body that a plain cross-site form could send', async () => {
    const res = await post({ sessionId: SESSION_ID }, 'text/plain');

    expect(res.status).toBe(415);
    expect(mockSessionsRetrieve).not.toHaveBeenCalled();
  });

  it('throttles under its own key, before reaching Stripe', async () => {
    mockCheckRateLimit.mockReturnValue(false);

    const res = await post();

    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ status: 'email' });
    expect(mockCheckRateLimit).toHaveBeenCalledWith('stripe-checkout-login:203.0.113.1', 10, 60_000);
    expect(mockSessionsRetrieve).not.toHaveBeenCalled();
  });

  it('logs the user id on a sign-in, and never the email or the session id', async () => {
    await post();

    const logged = JSON.stringify([...vi.mocked(console.warn).mock.calls, ...vi.mocked(console.error).mock.calls]);
    expect(logged).toContain('user-new');
    expect(logged).not.toContain(EMAIL);
    expect(logged).not.toContain(SESSION_ID);
  });

  it('keeps the session id out of the log when Stripe quotes it in an error', async () => {
    mockSessionsRetrieve.mockRejectedValue(new Error(`No such checkout.session: '${SESSION_ID}'`));

    expect(await (await post()).json()).toEqual({ status: 'email' });
    expect(vi.mocked(console.error).mock.calls).toEqual([['[checkout-login] Failed:', 'Error']]);
  });
});
