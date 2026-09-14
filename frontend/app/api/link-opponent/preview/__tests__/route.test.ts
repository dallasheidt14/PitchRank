import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockRequireAdmin, mockCreateServiceSupabase } = vi.hoisted(() => ({
  mockRequireAdmin: vi.fn(),
  mockCreateServiceSupabase: vi.fn(),
}));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: mockCreateServiceSupabase }));

import { POST } from '../route';

function makeRequest(body: unknown) {
  return new Request('http://localhost/api/link-opponent/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }) as NextRequest;
}

const validBody = { gameId: 'game-1', opponentProviderId: '999' };

let svc: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  svc = serviceClientMock();
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

describe('POST /api/link-opponent/preview', () => {
  it('returns the requireAdmin error and never touches the database for a non-admin', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(403);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 400 when required fields are missing', async () => {
    const res = await POST(makeRequest({ gameId: 'game-1' }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/missing required fields/i);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it.each(['None', 'null', '  '])('refuses the placeholder provider id %j before touching the database', async (id) => {
    const res = await POST(makeRequest({ ...validBody, opponentProviderId: id }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe('Opponent has no provider ID');
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('previews the games a real provider id would link', async () => {
    // Bound to variables: an inline literal with `count` fails QueryResult's excess-property check.
    const homeCount = { count: 1, error: null };
    const awayCount = { count: 0, error: null };
    svc.queueFrom(
      'games',
      { data: { provider_id: 'prov-1' }, error: null }, // clicked game
      {
        data: [
          {
            id: 'g1',
            game_date: '2026-09-01',
            home_score: 2,
            away_score: 1,
            competition: 'League',
            home_team_master_id: null,
            away_team_master_id: 'team-2',
          },
        ],
        error: null,
      }, // as home
      { data: [], error: null }, // as away
      homeCount,
      awayCount
    );
    svc.queueFrom('providers', { data: { name: 'GotSport', code: 'gotsport' }, error: null });
    svc.queueFrom('teams', { data: [{ team_id_master: 'team-2', team_name: 'Rivals FC' }], error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({
      success: true,
      opponentProviderId: '999',
      providerName: 'GotSport',
      totalGamesAffected: 1,
      asHomeTeam: 1,
      asAwayTeam: 0,
      previewGames: [{ id: 'g1', score: '2 - 1', otherTeam: 'Rivals FC' }],
    });
  });
});
