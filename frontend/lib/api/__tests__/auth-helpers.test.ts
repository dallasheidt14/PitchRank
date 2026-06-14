import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';

// Hoisted so it's available inside the hoisted vi.mock factory.
const { mockGetUser } = vi.hoisted(() => ({ mockGetUser: vi.fn() }));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: vi.fn(async () => ({ auth: { getUser: mockGetUser } }) as unknown as SupabaseClient),
}));

import { parseJsonBody } from '../parseJsonBody';
import { requireAuth } from '../requireAuth';
import { optionalAuth } from '../optionalAuth';

function jsonRequest(raw: string): Request {
  return new Request('http://localhost/api/x', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: raw,
  });
}

describe('parseJsonBody', () => {
  it('returns parsed data for a valid JSON body', async () => {
    const result = await parseJsonBody<{ a: number }>(jsonRequest('{"a":1}'));
    expect(result.error).toBeNull();
    expect(result.data).toEqual({ a: 1 });
  });

  it('returns a 400 NextResponse for malformed JSON', async () => {
    const result = await parseJsonBody(jsonRequest('{not valid json'));
    expect(result.data).toBeNull();
    expect(result.error?.status).toBe(400);
    expect(await result.error?.json()).toEqual({ error: 'Invalid request body' });
  });
});

describe('requireAuth', () => {
  beforeEach(() => vi.clearAllMocks());

  it('returns the user and supabase client when authenticated', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'u1', email: 'a@b.com' } }, error: null });
    const auth = await requireAuth();
    expect(auth.error).toBeNull();
    expect(auth.user).toEqual({ id: 'u1', email: 'a@b.com' });
    expect(auth.supabase).toBeTruthy();
  });

  it('returns 401 when no user is present', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
    const auth = await requireAuth();
    expect(auth.user).toBeNull();
    expect(auth.supabase).toBeNull();
    expect(auth.error?.status).toBe(401);
  });

  it('returns 401 when getUser reports an auth error', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: { message: 'bad jwt' } });
    const auth = await requireAuth();
    expect(auth.error?.status).toBe(401);
  });

  it('returns 500 when getUser throws', async () => {
    mockGetUser.mockRejectedValue(new Error('network down'));
    const auth = await requireAuth();
    expect(auth.user).toBeNull();
    expect(auth.error?.status).toBe(500);
  });
});

describe('optionalAuth', () => {
  beforeEach(() => vi.clearAllMocks());

  it('returns the user and supabase client when authenticated', async () => {
    mockGetUser.mockResolvedValue({ data: { user: { id: 'u1' } }, error: null });
    const { user, supabase } = await optionalAuth();
    expect(user).toEqual({ id: 'u1' });
    expect(supabase).toBeTruthy();
  });

  it('returns nulls (no error) when not authenticated', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
    const { user, supabase } = await optionalAuth();
    expect(user).toBeNull();
    expect(supabase).toBeNull();
  });

  it('returns nulls (never throws) when getUser throws', async () => {
    mockGetUser.mockRejectedValue(new Error('boom'));
    const { user, supabase } = await optionalAuth();
    expect(user).toBeNull();
    expect(supabase).toBeNull();
  });
});
