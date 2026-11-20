import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextResponse } from 'next/server';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockRequireAdmin, mockCreateServiceSupabase } = vi.hoisted(() => ({
  mockRequireAdmin: vi.fn(),
  mockCreateServiceSupabase: vi.fn(),
}));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: mockCreateServiceSupabase }));

import { POST } from '../route';

const GAME_A = '11111111-1111-1111-1111-111111111111';
const GAME_B = '22222222-2222-2222-2222-222222222222';

function gameId(n: number): string {
  return `${n.toString(16).padStart(8, '0')}-1111-1111-1111-111111111111`;
}

function makeRequest(body: unknown): Request {
  return new Request('http://localhost/api/game-provider-ids', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

let svc: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  svc = serviceClientMock();
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

describe('POST /api/game-provider-ids', () => {
  it.each([
    ['a signed-out visitor', 401, 'Not authenticated'],
    ['a subscriber', 403, 'Admin access required'],
  ])('refuses %s and never builds the service client', async (_who, status, message) => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: message }, { status }),
    });

    const res = await POST(makeRequest({ gameIds: [GAME_A] }));

    expect(res.status).toBe(status);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns each game with its two provider ids, read through the service client', async () => {
    const rows = [{ id: GAME_A, home_provider_id: '111', away_provider_id: '999' }];
    svc.queueFrom('games', { data: rows, error: null });

    const res = await POST(makeRequest({ gameIds: [GAME_A, GAME_B, GAME_A] }));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ games: rows });
    const query = svc.from.mock.results[0].value;
    expect(svc.from).toHaveBeenCalledWith('games');
    expect(query.select).toHaveBeenCalledWith('id, home_provider_id, away_provider_id');
    expect(query.in).toHaveBeenCalledWith('id', [GAME_A, GAME_B]);
  });

  it('answers an empty list without reading the database', async () => {
    const res = await POST(makeRequest({ gameIds: [] }));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ games: [] });
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it.each([
    ['a body that is not JSON', 'not json'],
    ['gameIds that is not a list', { gameIds: GAME_A }],
    ['a member that is not a UUID', { gameIds: [GAME_A, 'game-1'] }],
    ['a member that is not a string', { gameIds: [GAME_A, 7] }],
  ])('refuses %s', async (_what, body) => {
    const res = await POST(makeRequest(body));

    expect(res.status).toBe(400);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('accepts 150 ids and refuses 151', async () => {
    const ids = Array.from({ length: 151 }, (_, n) => gameId(n));

    expect((await POST(makeRequest({ gameIds: ids.slice(0, 150) }))).status).toBe(200);
    expect((await POST(makeRequest({ gameIds: ids }))).status).toBe(400);
  });

  it('reports a database error without passing its text on', async () => {
    svc.queueFrom('games', { data: null, error: { message: 'permission denied for table games' } });
    vi.spyOn(console, 'error').mockImplementation(() => {});

    const res = await POST(makeRequest({ gameIds: [GAME_A] }));

    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ error: 'Failed to fetch game provider ids' });
  });
});
