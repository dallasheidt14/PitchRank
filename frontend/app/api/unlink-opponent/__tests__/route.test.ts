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
  return new Request('http://localhost/api/unlink-opponent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }) as NextRequest;
}

const TEAM = 'team-1';
const validBody = { gameId: 'game-1', opponentProviderId: '999', teamIdMaster: TEAM };

// A game where provider 999 is the home side, currently linked to TEAM.
function linkedHomeGame() {
  return {
    id: 'game-1',
    provider_id: 'prov-1',
    home_provider_id: '999',
    away_provider_id: '222',
    home_team_master_id: TEAM,
    away_team_master_id: null,
  };
}

let svc: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  svc = serviceClientMock();
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

describe('POST /api/unlink-opponent', () => {
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

  it('returns 404 when the game does not exist', async () => {
    svc.queueFrom('games', { data: null, error: { message: 'no rows' } });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(404);
    expect((await res.json()).error).toMatch(/game not found/i);
  });

  it('returns 400 when the game has no provider', async () => {
    svc.queueFrom('games', { data: { ...linkedHomeGame(), provider_id: null }, error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/no provider/i);
  });

  it('returns 400 when the provider id matches neither side of the game', async () => {
    svc.queueFrom('games', { data: { ...linkedHomeGame(), home_provider_id: '111' }, error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/does not match any team/i);
  });

  it('returns 400 when the linked team does not match the expected team', async () => {
    svc.queueFrom('games', { data: { ...linkedHomeGame(), home_team_master_id: 'someone-else' }, error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/team mismatch/i);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('returns 500 when the unlink RPC fails', async () => {
    svc.queueFrom('games', { data: linkedHomeGame(), error: null });
    svc.queueRpc({ error: { message: 'constraint violation', code: '23503' } });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(500);
    expect((await res.json()).error).toMatch(/failed to unlink/i);
  });

  it('unlinks the single clicked game via RPC and removes the alias', async () => {
    svc.queueFrom('games', { data: linkedHomeGame(), error: null });
    svc.queueRpc({ error: null });
    svc.queueFrom('team_alias_map', { error: null });
    svc.queueFrom('team_link_audit', { error: null });

    const res = await POST(makeRequest({ ...validBody, unlinkAllGames: false }));

    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ success: true, gamesUpdated: 1, aliasRemoved: true });
    expect(svc.rpc).toHaveBeenCalledWith(
      'unlink_game_team',
      expect.objectContaining({ p_game_id: 'game-1', p_team_id_master: TEAM, p_is_home_team: true })
    );
  });

  it('also unlinks matching games and reports aliasRemoved false when the alias delete errors', async () => {
    svc.queueFrom(
      'games',
      { data: linkedHomeGame(), error: null }, // initial lookup
      { data: [{ id: 'g2' }], error: null }, // home bulk unlink (1 row)
      { data: [], error: null } // away bulk unlink (0 rows)
    );
    svc.queueRpc({ error: null });
    svc.queueFrom('team_alias_map', { error: { message: 'fk still referenced' } });
    svc.queueFrom('team_link_audit', { error: null });

    const res = await POST(makeRequest({ ...validBody, unlinkAllGames: true }));

    expect(res.status).toBe(200);
    // 1 clicked game + 1 matching game unlinked; alias delete failed (non-fatal).
    expect(await res.json()).toMatchObject({ success: true, gamesUpdated: 2, aliasRemoved: false });
  });

  it('surfaces a failed bulk unlink to logs instead of silently swallowing the error', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    svc.queueFrom(
      'games',
      { data: linkedHomeGame(), error: null }, // initial lookup
      { data: null, error: { message: 'deadlock detected' } }, // home bulk unlink FAILS
      { data: [], error: null } // away bulk unlink
    );
    svc.queueRpc({ error: null });
    svc.queueFrom('team_alias_map', { error: null });
    svc.queueFrom('team_link_audit', { error: null });

    const res = await POST(makeRequest({ ...validBody, unlinkAllGames: true }));

    expect(res.status).toBe(200);
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining('bulk-unlink'),
      expect.objectContaining({ message: 'deadlock detected' })
    );
    errorSpy.mockRestore();
  });
});
