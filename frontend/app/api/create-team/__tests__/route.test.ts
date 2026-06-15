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
  return new Request('http://localhost/api/create-team', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }) as NextRequest;
}

// Valid base payload: opponentProviderId matches the game's home side below.
const validBody = {
  gameId: 'game-1',
  opponentProviderId: '999',
  teamName: 'New Team FC',
  ageGroup: 'u14',
  gender: 'Male',
};

let svc: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  svc = serviceClientMock();
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

describe('POST /api/create-team', () => {
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
    const { teamName: _omit, ...withoutName } = validBody;
    const res = await POST(makeRequest(withoutName));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/missing required fields/i);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 400 for an invalid gender', async () => {
    const res = await POST(makeRequest({ ...validBody, gender: 'Coed' }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/male.*female/i);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 400 for a malformed age group', async () => {
    const res = await POST(makeRequest({ ...validBody, ageGroup: '14' }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/age group/i);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 404 when the game does not exist', async () => {
    svc.queueFrom('games', { data: null, error: { message: 'no rows' } });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(404);
    expect((await res.json()).error).toMatch(/game not found/i);
  });

  it('returns 400 when the opponent provider id is not referenced by the game', async () => {
    svc.queueFrom('games', {
      data: { provider_id: null, home_provider_id: '111', away_provider_id: '222' },
      error: null,
    });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/does not match any team/i);
    // Bailed before creating anything.
    expect(svc.from).not.toHaveBeenCalledWith('teams');
  });

  it('returns 500 when the team insert fails', async () => {
    svc.queueFrom('games', {
      data: { provider_id: null, home_provider_id: '999', away_provider_id: '222' },
      error: null,
    });
    svc.queueFrom('teams', { error: { message: 'duplicate key' } });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(500);
    expect((await res.json()).error).toMatch(/failed to create team/i);
  });

  it('returns 500 when the alias mapping fails after the team is created', async () => {
    svc.queueFrom('games', {
      data: { provider_id: null, home_provider_id: '999', away_provider_id: '222' },
      error: null,
    });
    svc.queueFrom('teams', { error: null });
    svc.queueFrom('team_alias_map', { error: { message: 'conflict' } });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(500);
    expect((await res.json()).error).toMatch(/alias mapping failed/i);
  });

  it('creates the team, backfills games, and reports the linked count', async () => {
    svc.queueFrom(
      'games',
      { data: { provider_id: null, home_provider_id: '999', away_provider_id: '222' }, error: null }, // initial lookup
      { data: [{ id: 'g1' }, { id: 'g2' }], error: null }, // home backfill (2 rows)
      { data: [], error: null } // away backfill (0 rows)
    );
    svc.queueFrom('teams', { error: null });
    svc.queueFrom('team_alias_map', { error: null });
    svc.queueFrom('team_link_audit', { error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ success: true, teamName: 'New Team FC', gamesUpdated: 2 });
    expect(body.teamIdMaster).toBeTruthy();
    expect(svc.from).toHaveBeenCalledWith('teams');
    expect(svc.from).toHaveBeenCalledWith('team_alias_map');
    // provider_id was null, so the GotSport scrape enqueue is skipped.
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('enqueues a priority scrape when the new team belongs to a GotSport game', async () => {
    svc.queueFrom(
      'games',
      { data: { provider_id: 'prov-1', home_provider_id: '999', away_provider_id: '222' }, error: null },
      { data: [{ id: 'g1' }], error: null },
      { data: [], error: null }
    );
    svc.queueFrom('teams', { error: null });
    svc.queueFrom('team_alias_map', { error: null });
    svc.queueFrom('team_link_audit', { error: null });
    svc.queueFrom('providers', { data: { code: 'gotsport' }, error: null });
    svc.queueRpc({ error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(200);
    expect(svc.rpc).toHaveBeenCalledWith(
      'enqueue_scrape_request',
      expect.objectContaining({ p_priority: 1, p_request_type: 'new_team' })
    );
  });

  it('still succeeds when the non-fatal scrape enqueue throws', async () => {
    svc.queueFrom(
      'games',
      { data: { provider_id: 'prov-1', home_provider_id: '999', away_provider_id: '222' }, error: null },
      { data: [{ id: 'g1' }], error: null },
      { data: [], error: null }
    );
    svc.queueFrom('teams', { error: null });
    svc.queueFrom('team_alias_map', { error: null });
    svc.queueFrom('team_link_audit', { error: null });
    svc.queueFrom('providers', { data: { code: 'gotsport' }, error: null });
    svc.rpc.mockRejectedValueOnce(new Error('queue down'));

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(200);
    expect((await res.json()).success).toBe(true);
  });
});
