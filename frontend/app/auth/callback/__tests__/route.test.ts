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

import { GET } from '../route';

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
});
