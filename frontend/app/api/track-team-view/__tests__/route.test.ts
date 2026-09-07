import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockRequirePremium, mockCheckRateLimit, mockCreateServiceSupabase } = vi.hoisted(() => ({
  mockRequirePremium: vi.fn(),
  mockCheckRateLimit: vi.fn(),
  mockCreateServiceSupabase: vi.fn(),
}));

vi.mock('@/lib/api/requirePremium', () => ({ requirePremium: mockRequirePremium }));
vi.mock('@/lib/api/rateLimit', () => ({ checkRateLimit: mockCheckRateLimit }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: mockCreateServiceSupabase }));

import { POST } from '../route';

function makeRequest(body: unknown) {
  return new Request('http://localhost/api/track-team-view', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  }) as NextRequest;
}

/** The insert spy for the builder `.from()` handed back on its first call. */
function insertSpy(svc: ReturnType<typeof serviceClientMock>) {
  return svc.from.mock.results[0].value.insert;
}

const TEAM_ID = '11111111-1111-1111-1111-111111111111';

let svc: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  svc = serviceClientMock();
  mockRequirePremium.mockResolvedValue({ user: { id: 'user-1' }, supabase: {}, error: null });
  mockCheckRateLimit.mockReturnValue(true);
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

describe('POST /api/track-team-view', () => {
  it('records the view and returns no content', async () => {
    const res = await POST(makeRequest({ teamId: TEAM_ID }));

    expect(res.status).toBe(204);
    expect(svc.from).toHaveBeenCalledWith('team_page_views');
    expect(insertSpy(svc)).toHaveBeenCalledWith({ team_id_master: TEAM_ID, user_id: 'user-1' });
  });

  it('stamps the authenticated user, never a user id from the body', async () => {
    await POST(makeRequest({ teamId: TEAM_ID, user_id: 'somebody-else', userId: 'somebody-else' }));

    expect(insertSpy(svc)).toHaveBeenCalledWith({ team_id_master: TEAM_ID, user_id: 'user-1' });
  });

  it('returns the requirePremium error and never builds a service client for a signed-out visitor', async () => {
    mockRequirePremium.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Not authenticated' }, { status: 401 }),
    });

    const res = await POST(makeRequest({ teamId: TEAM_ID }));

    expect(res.status).toBe(401);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns the requirePremium error and never builds a service client for a free user', async () => {
    mockRequirePremium.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Premium required' }, { status: 403 }),
    });

    const res = await POST(makeRequest({ teamId: TEAM_ID }));

    expect(res.status).toBe(403);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('caps a scripted caller by user id before anything is written', async () => {
    mockCheckRateLimit.mockReturnValue(false);

    const res = await POST(makeRequest({ teamId: TEAM_ID }));

    expect(res.status).toBe(429);
    expect(mockCheckRateLimit).toHaveBeenCalledWith('track-team-view:user-1', 300, 3_600_000);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('rejects a missing teamId', async () => {
    const res = await POST(makeRequest({}));

    expect(res.status).toBe(400);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('rejects a teamId that is not a uuid', async () => {
    const res = await POST(makeRequest({ teamId: 'teams; drop table' }));

    expect(res.status).toBe(400);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('rejects a teamId that only looks like a uuid once coerced', async () => {
    // isValidUuid coerces, so String(['<uuid>']) matches the pattern. Without a
    // typeof check the array reaches PostgREST and comes back a 500.
    const res = await POST(makeRequest({ teamId: [TEAM_ID] }));

    expect(res.status).toBe(400);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('rejects a malformed body', async () => {
    const res = await POST(makeRequest('{not json'));

    expect(res.status).toBe(400);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('surfaces a failed insert as a server error', async () => {
    svc.queueFrom('team_page_views', { data: null, error: { message: 'rls violation' } });

    const res = await POST(makeRequest({ teamId: TEAM_ID }));

    expect(res.status).toBe(500);
  });
});
