import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockVerifyOtp, mockRedirect, mockCookieSet } = vi.hoisted(() => ({
  mockVerifyOtp: vi.fn(),
  mockCookieSet: vi.fn(),
  mockRedirect: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
}));

vi.mock('next/navigation', () => ({ redirect: mockRedirect }));

vi.mock('next/headers', () => ({ cookies: vi.fn(async () => ({ set: mockCookieSet })) }));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: vi.fn(async () => ({ auth: { verifyOtp: mockVerifyOtp } })),
}));

import { confirmEmailLink } from '../actions';

function confirmForm(fields: Record<string, string>): FormData {
  const formData = new FormData();
  Object.entries(fields).forEach(([name, value]) => formData.set(name, value));
  return formData;
}

async function redirectTarget(formData: FormData): Promise<string> {
  await expect(confirmEmailLink(formData)).rejects.toThrow(/NEXT_REDIRECT/);
  return mockRedirect.mock.calls.at(-1)![0];
}

describe('confirmEmailLink', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('redeems a recovery token and routes to /reset-password', async () => {
    mockVerifyOtp.mockResolvedValue({ error: null });

    const target = await redirectTarget(confirmForm({ token_hash: 'abc', type: 'recovery' }));

    expect(mockVerifyOtp).toHaveBeenCalledWith({ token_hash: 'abc', type: 'recovery' });
    expect(target).toBe('/reset-password');
  });

  it('clears the recovery marker so a later OAuth sign-in is not misrouted', async () => {
    // forgot-password sets password_reset_pending for 24h; the callback treats
    // any bare ?code= as a recovery while it is set. Leaving it behind sends an
    // unrelated Google sign-in to /reset-password for the rest of the day.
    mockVerifyOtp.mockResolvedValue({ error: null });

    await redirectTarget(confirmForm({ token_hash: 'abc', type: 'recovery' }));

    expect(mockCookieSet).toHaveBeenCalledWith('password_reset_pending', '', { path: '/', maxAge: 0 });
  });

  it('leaves the recovery marker alone when confirming a non-recovery link', async () => {
    mockVerifyOtp.mockResolvedValue({ error: null });

    await redirectTarget(confirmForm({ token_hash: 'abc', type: 'email' }));

    expect(mockCookieSet).not.toHaveBeenCalled();
  });

  it('routes a confirmed email to the requested next path', async () => {
    mockVerifyOtp.mockResolvedValue({ error: null });

    const target = await redirectTarget(confirmForm({ token_hash: 'abc', type: 'email', next: '/watchlist' }));

    expect(target).toBe('/watchlist');
  });

  it('rejects a protocol-relative next value instead of redirecting off-site', async () => {
    mockVerifyOtp.mockResolvedValue({ error: null });

    const target = await redirectTarget(confirmForm({ token_hash: 'abc', type: 'email', next: '//evil.example' }));

    expect(target).toBe('/rankings');
  });

  it('sends a spent token back to login without reaching the password form', async () => {
    mockVerifyOtp.mockResolvedValue({ error: { code: 'otp_expired', message: 'Token has invalid claims: xyz' } });

    const target = await redirectTarget(confirmForm({ token_hash: 'abc', type: 'recovery' }));

    expect(target).toContain('/login?error=');
    expect(target).not.toContain('/reset-password');
  });

  it('keeps raw Supabase error text out of the login banner', async () => {
    mockVerifyOtp.mockResolvedValue({ error: { code: 'unexpected_failure', message: 'Database error finding user' } });

    const target = await redirectTarget(confirmForm({ token_hash: 'abc', type: 'recovery' }));

    expect(target).not.toContain('Database');
    expect(decodeURIComponent(target)).toContain('expired or was already used');
  });

  it('rejects a backslash authority in next, which browsers resolve off-origin', async () => {
    mockVerifyOtp.mockResolvedValue({ error: null });
    const backslash = String.fromCharCode(92);

    const target = await redirectTarget(
      confirmForm({ token_hash: 'abc', type: 'email', next: `/${backslash}evil.example` })
    );

    expect(target).toBe('/rankings');
  });

  it('rejects an absolute next URL', async () => {
    mockVerifyOtp.mockResolvedValue({ error: null });

    const target = await redirectTarget(
      confirmForm({ token_hash: 'abc', type: 'email', next: 'https://evil.example' })
    );

    expect(target).toBe('/rankings');
  });

  it('never calls verifyOtp when the token is missing', async () => {
    const target = await redirectTarget(confirmForm({ type: 'recovery' }));

    expect(mockVerifyOtp).not.toHaveBeenCalled();
    expect(target).toContain('/login?error=');
  });

  it('never calls verifyOtp for a type Supabase does not verify', async () => {
    await redirectTarget(confirmForm({ token_hash: 'abc', type: 'magiclink_or_bogus' }));

    expect(mockVerifyOtp).not.toHaveBeenCalled();
  });
});
