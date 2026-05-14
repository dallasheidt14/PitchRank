import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextRequest } from 'next/server';

// Hoist mock fns for use inside vi.mock factory
const { mockGetUser, mockGetSession, mockFrom } = vi.hoisted(() => ({
  mockGetUser: vi.fn(),
  mockGetSession: vi.fn(),
  mockFrom: vi.fn(),
}));

vi.mock('@supabase/ssr', () => ({
  createServerClient: vi.fn(() => ({
    auth: {
      getUser: mockGetUser,
      getSession: mockGetSession,
    },
    from: mockFrom,
  })),
}));

import { middleware } from '../middleware';

function makeRequest(url: string, opts: { host?: string } = {}): NextRequest {
  const host = opts.host ?? 'www.pitchrank.io';
  const req = new NextRequest(url);
  // `host` is a forbidden header name in the Fetch spec, so the Request
  // constructor strips it. The middleware reads it via headers.get('host')
  // (which is set by Vercel in prod). Inject it directly on the test instance.
  Object.defineProperty(req, 'headers', {
    value: new Headers([['host', host]]),
    configurable: true,
  });
  return req;
}

/**
 * Build a profile fetch mock for `from('user_profiles').select(...).eq('id', ...).single()`.
 * Returns either a row or an error depending on the args.
 */
function profileFetchReturning(final: { data?: unknown; error?: unknown }) {
  const single = vi.fn().mockResolvedValue(final);
  const eq = vi.fn(() => ({ single }));
  const select = vi.fn(() => ({ eq }));
  return { select };
}

const ANON_AUTH = () => {
  mockGetUser.mockResolvedValue({ data: { user: null } });
  mockGetSession.mockResolvedValue({ data: { session: null } });
};

const AUTH_AS = (id: string) => {
  mockGetUser.mockResolvedValue({ data: { user: { id, email: `${id}@test.io` } } });
  mockGetSession.mockResolvedValue({ data: { session: { user: { id } } } });
};

describe('middleware', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://test.supabase.co';
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon-key';
  });

  describe('host canonicalization', () => {
    it('301-redirects apex pitchrank.io to www.pitchrank.io', async () => {
      ANON_AUTH();
      const res = await middleware(makeRequest('https://pitchrank.io/rankings', { host: 'pitchrank.io' }));

      expect(res.status).toBe(301);
      expect(res.headers.get('location')).toContain('www.pitchrank.io/rankings');
    });

    it('does not redirect www.pitchrank.io', async () => {
      ANON_AUTH();
      const res = await middleware(makeRequest('https://www.pitchrank.io/rankings'));

      // NextResponse.next() returns 200 with no location header
      expect(res.status).toBe(200);
      expect(res.headers.get('location')).toBeNull();
    });
  });

  describe('OAuth code rewrite', () => {
    it('redirects ?code=... on any non-callback path to /auth/callback', async () => {
      ANON_AUTH();
      const res = await middleware(makeRequest('https://www.pitchrank.io/?code=oauth_xyz'));

      expect(res.status).toBe(307);
      const location = res.headers.get('location') ?? '';
      expect(location).toContain('/auth/callback');
      expect(location).toContain('code=oauth_xyz');
    });

    it('redirects ?token_hash=... to /auth/callback (email magic link)', async () => {
      ANON_AUTH();
      const res = await middleware(makeRequest('https://www.pitchrank.io/login?token_hash=abc'));

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toContain('/auth/callback');
      expect(res.headers.get('location')).toContain('token_hash=abc');
    });

    it('does NOT redirect ?code=... when already on /auth/callback', async () => {
      ANON_AUTH();
      const res = await middleware(makeRequest('https://www.pitchrank.io/auth/callback?code=oauth_xyz'));

      // /auth/callback is excluded by the matcher anyway, but the in-middleware
      // check at line 31 is the actual guard.
      expect(res.status).toBe(200);
    });
  });

  describe('premium route gating', () => {
    it('redirects unauthenticated user from /watchlist to /upgrade?next=/watchlist', async () => {
      ANON_AUTH();
      const res = await middleware(makeRequest('https://www.pitchrank.io/watchlist'));

      expect(res.status).toBe(307);
      const location = res.headers.get('location') ?? '';
      expect(location).toContain('/upgrade');
      expect(location).toContain('next=%2Fwatchlist');
    });

    it('redirects authenticated free user from /watchlist to /upgrade', async () => {
      AUTH_AS('user-free');
      mockFrom.mockReturnValue(profileFetchReturning({ data: { plan: 'free' }, error: null }));

      const res = await middleware(makeRequest('https://www.pitchrank.io/watchlist'));

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toContain('/upgrade');
    });

    it('redirects to /upgrade when profile is missing (defensive — no silent bypass)', async () => {
      AUTH_AS('user-orphan');
      mockFrom.mockReturnValue(profileFetchReturning({ data: null, error: { message: 'PGRST116' } }));

      const res = await middleware(makeRequest('https://www.pitchrank.io/watchlist'));

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toContain('/upgrade');
    });

    it('allows premium user through /watchlist', async () => {
      AUTH_AS('user-premium');
      mockFrom.mockReturnValue(profileFetchReturning({ data: { plan: 'premium' }, error: null }));

      const res = await middleware(makeRequest('https://www.pitchrank.io/watchlist'));

      expect(res.status).toBe(200);
      expect(res.headers.get('location')).toBeNull();
    });

    it('allows admin user through /watchlist (admin satisfies premium)', async () => {
      AUTH_AS('user-admin');
      mockFrom.mockReturnValue(profileFetchReturning({ data: { plan: 'admin' }, error: null }));

      const res = await middleware(makeRequest('https://www.pitchrank.io/compare'));

      expect(res.status).toBe(200);
    });
  });

  describe('admin route gating', () => {
    it('redirects unauthenticated user from /mission-control to /login?next=/mission-control', async () => {
      ANON_AUTH();
      const res = await middleware(makeRequest('https://www.pitchrank.io/mission-control'));

      expect(res.status).toBe(307);
      const location = res.headers.get('location') ?? '';
      expect(location).toContain('/login');
      expect(location).toContain('next=%2Fmission-control');
    });

    it('redirects authenticated premium user from /mission-control to / (not admin)', async () => {
      AUTH_AS('user-premium');
      mockFrom.mockReturnValue(profileFetchReturning({ data: { plan: 'premium' }, error: null }));

      const res = await middleware(makeRequest('https://www.pitchrank.io/mission-control'));

      expect(res.status).toBe(307);
      const location = res.headers.get('location') ?? '';
      expect(location).toMatch(/\/$/);
    });

    it('allows admin user through /mission-control', async () => {
      AUTH_AS('user-admin');
      mockFrom.mockReturnValue(profileFetchReturning({ data: { plan: 'admin' }, error: null }));

      const res = await middleware(makeRequest('https://www.pitchrank.io/mission-control'));

      expect(res.status).toBe(200);
    });

    it('allows admin user through /analytics (covers the other admin prefix)', async () => {
      AUTH_AS('user-admin');
      mockFrom.mockReturnValue(profileFetchReturning({ data: { plan: 'admin' }, error: null }));

      const res = await middleware(makeRequest('https://www.pitchrank.io/analytics'));

      expect(res.status).toBe(200);
    });
  });

  describe('auth-route redirect for signed-in users', () => {
    it('redirects authenticated user from /login to /rankings', async () => {
      AUTH_AS('user-any');

      const res = await middleware(makeRequest('https://www.pitchrank.io/login'));

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toContain('/rankings');
    });

    it('redirects authenticated user from /signup to /rankings', async () => {
      AUTH_AS('user-any');

      const res = await middleware(makeRequest('https://www.pitchrank.io/signup'));

      expect(res.status).toBe(307);
      expect(res.headers.get('location')).toContain('/rankings');
    });

    it('allows anonymous user to reach /login', async () => {
      ANON_AUTH();

      const res = await middleware(makeRequest('https://www.pitchrank.io/login'));

      expect(res.status).toBe(200);
    });
  });

  describe('public routes', () => {
    it('passes /rankings through without auth check or profile fetch', async () => {
      ANON_AUTH();

      const res = await middleware(makeRequest('https://www.pitchrank.io/rankings'));

      expect(res.status).toBe(200);
      // Profile lookup only happens on premium/admin routes
      expect(mockFrom).not.toHaveBeenCalled();
    });

    it('passes /blog/some-post through anonymously', async () => {
      ANON_AUTH();

      const res = await middleware(makeRequest('https://www.pitchrank.io/blog/youth-soccer-rankings'));

      expect(res.status).toBe(200);
      expect(mockFrom).not.toHaveBeenCalled();
    });
  });
});
