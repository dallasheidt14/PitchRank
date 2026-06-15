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
  return new Request('http://localhost/api/link-opponent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }) as NextRequest;
}

const TEAM = 'team-1';
const validBody = { gameId: 'game-1', opponentProviderId: '999', teamIdMaster: TEAM };

const linkedTeam = {
  team_id_master: TEAM,
  team_name: 'Linked FC',
  club_name: 'Linked Club',
  age_group: 'u14',
  gender: 'Male',
};

// A game where provider 999 is the (still-unlinked) home side.
function unlinkedHomeGame() {
  return {
    id: 'game-1',
    provider_id: 'prov-1',
    home_provider_id: '999',
    away_provider_id: '222',
    home_team_master_id: null,
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

describe('POST /api/link-opponent', () => {
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

  it('returns 404 when the team does not exist', async () => {
    svc.queueFrom('teams', { data: null, error: { message: 'no rows' } });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(404);
    expect((await res.json()).error).toMatch(/team not found/i);
  });

  it('returns 404 when the game does not exist', async () => {
    svc.queueFrom('teams', { data: linkedTeam, error: null });
    svc.queueFrom('games', { data: null, error: { message: 'no rows' } });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(404);
    expect((await res.json()).error).toMatch(/game not found/i);
  });

  it('returns 400 when the opponent side is already linked', async () => {
    svc.queueFrom('teams', { data: linkedTeam, error: null });
    svc.queueFrom('games', { data: { ...unlinkedHomeGame(), home_team_master_id: 'someone-else' }, error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/already linked/i);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('returns 400 when the provider id matches neither side of the game', async () => {
    svc.queueFrom('teams', { data: linkedTeam, error: null });
    svc.queueFrom('games', { data: { ...unlinkedHomeGame(), home_provider_id: '111' }, error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/does not match any team/i);
  });

  it('links the clicked game via the link_game_team RPC and creates the alias', async () => {
    svc.queueFrom('teams', { data: linkedTeam, error: null });
    svc.queueFrom(
      'games',
      { data: unlinkedHomeGame(), error: null }, // initial lookup
      { data: { id: 'game-1', home_team_master_id: TEAM }, error: null } // verification re-fetch
    );
    svc.queueRpc({ data: true, error: null });
    svc.queueFrom('team_alias_map', { error: null });
    svc.queueFrom('team_link_audit', { error: null });

    const res = await POST(makeRequest({ ...validBody, applyToAllGames: false }));

    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({
      success: true,
      teamName: 'Linked FC',
      gamesUpdated: 1,
      aliasCreated: true,
    });
    expect(svc.rpc).toHaveBeenCalledWith(
      'link_game_team',
      expect.objectContaining({ p_game_id: 'game-1', p_team_id_master: TEAM, p_is_home_team: true })
    );
    expect(svc.from).toHaveBeenCalledWith('team_alias_map');
  });

  it('returns 500 when the database silently rejects the link (verification fails)', async () => {
    svc.queueFrom('teams', { data: linkedTeam, error: null });
    svc.queueFrom(
      'games',
      { data: unlinkedHomeGame(), error: null },
      { data: { id: 'game-1', home_team_master_id: null }, error: null } // re-fetch shows no change
    );
    svc.queueRpc({ data: false, error: null }); // RPC reports no row affected

    const res = await POST(makeRequest({ ...validBody, applyToAllGames: false }));

    expect(res.status).toBe(500);
    expect((await res.json()).error).toMatch(/rejected the change/i);
    // Alias must NOT be written when the link could not be proven.
    expect(svc.from).not.toHaveBeenCalledWith('team_alias_map');
  });

  it('returns 500 when the alias upsert fails after the game is linked', async () => {
    svc.queueFrom('teams', { data: linkedTeam, error: null });
    svc.queueFrom(
      'games',
      { data: unlinkedHomeGame(), error: null },
      { data: { id: 'game-1', home_team_master_id: TEAM }, error: null }
    );
    svc.queueRpc({ data: true, error: null });
    svc.queueFrom('team_alias_map', { error: { message: 'conflict' } });

    const res = await POST(makeRequest({ ...validBody, applyToAllGames: false }));

    expect(res.status).toBe(500);
    expect((await res.json()).error).toMatch(/alias mapping failed/i);
  });
});
