import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockExchange, mockVerifyOtp, mockCookieGet, mockCookieSet, mockCookieGetAll } = vi.hoisted(() => ({
  mockExchange: vi.fn(),
  mockVerifyOtp: vi.fn(),
  mockCookieGet: vi.fn(),
  mockCookieSet: vi.fn(),
  mockCookieGetAll: vi.fn(() => []),
}));

vi.mock('next/headers', () => ({
  cookies: vi.fn(async () => ({ get: mockCookieGet, set: mockCookieSet, getAll: mockCookieGetAll })),
}));

vi.mock('@supabase/ssr', () => ({
  createServerClient: vi.fn(() => ({ auth: { exchangeCodeForSession: mockExchange, verifyOtp: mockVerifyOtp } })),
}));

import { GET, HEAD } from '../route';

function callbackRequest(query: string): Request {
  return new Request(`http://localhost/auth/callback${query}`);
}

function recoveryCookieWasCleared(): boolean {
  return mockCookieSet.mock.calls.some(([name, , opts]) => name === 'password_reset_pending' && opts?.maxAge === 0);
}

describe('GET /auth/callback — recovery code exchange', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCookieGet.mockImplementation((name: string) =>
      name === 'password_reset_pending' ? { value: 'true' } : undefined
    );
  });

  it('preserves the recovery cookie when the code exchange fails, so a retried link still routes to reset', async () => {
    mockExchange.mockResolvedValue({ error: { message: 'temporary server error' } });

    const res = await GET(callbackRequest('?code=abc'));

    expect(res.headers.get('location')).toContain('/login');
    expect(recoveryCookieWasCleared()).toBe(false);
  });

  it('clears the recovery cookie and routes to /reset-password on a successful recovery exchange', async () => {
    mockExchange.mockResolvedValue({ error: null });

    const res = await GET(callbackRequest('?code=abc'));

    expect(res.headers.get('location')).toContain('/reset-password');
    expect(recoveryCookieWasCleared()).toBe(true);
  });

  it('clears the recovery cookie on a terminal code-verifier failure so it cannot hijack a later exchange', async () => {
    // Code-verifier/PKCE failures are non-retryable (the code is consumed); leaving
    // the flag set would route an unrelated later ?code= exchange to /reset-password.
    mockExchange.mockResolvedValue({ error: { message: 'auth code and code verifier should be non-empty' } });

    const res = await GET(callbackRequest('?code=abc'));

    expect(res.headers.get('location')).toContain('/login');
    expect(recoveryCookieWasCleared()).toBe(true);
  });
});

describe('HEAD /auth/callback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not consume the one-time token, so a mail scanner prefetch cannot invalidate a recovery link', async () => {
    const res = await HEAD(callbackRequest('?token_hash=abc&type=recovery'));

    expect(mockVerifyOtp).not.toHaveBeenCalled();
    expect(mockExchange).not.toHaveBeenCalled();
    expect(res.status).toBe(200);
  });

  it('does not exchange a PKCE code, the one credential this route still spends', async () => {
    const res = await HEAD(callbackRequest('?code=oauth_xyz'));

    expect(mockExchange).not.toHaveBeenCalled();
    expect(res.status).toBe(200);
  });
});

describe('GET /auth/callback — emailed token handoff', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCookieGet.mockReturnValue(undefined);
  });

  it('hands a recovery token to /auth/confirm instead of redeeming it on GET', async () => {
    const res = await GET(callbackRequest('?token_hash=abc&type=recovery'));

    expect(mockVerifyOtp).not.toHaveBeenCalled();
    const location = res.headers.get('location') ?? '';
    expect(location).toContain('/auth/confirm');
    expect(location).toContain('token_hash=abc');
    expect(location).toContain('type=recovery');
  });

  it('preserves a same-origin next through the handoff', async () => {
    const res = await GET(callbackRequest('?token_hash=abc&type=email&next=/watchlist'));

    expect(res.headers.get('location')).toContain('next=%2Fwatchlist');
  });

  it('drops a protocol-relative next rather than forwarding it', async () => {
    const res = await GET(callbackRequest('?token_hash=abc&type=email&next=//evil.example'));

    const location = res.headers.get('location') ?? '';
    expect(location).not.toContain('evil.example');
    expect(location).toContain('next=%2Frankings');
  });

  it('does not touch Supabase at all on the token_hash path', async () => {
    await GET(callbackRequest('?token_hash=abc&type=recovery'));

    expect(mockVerifyOtp).not.toHaveBeenCalled();
    expect(mockExchange).not.toHaveBeenCalled();
  });
});
