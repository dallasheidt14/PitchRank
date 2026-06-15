import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { serviceClientMock } from '@/test/supabase-mock';

// Hoisted so they're available inside the hoisted vi.mock factories.
const { mockRequireAdmin, mockCreateServiceSupabase } = vi.hoisted(() => ({
  mockRequireAdmin: vi.fn(),
  mockCreateServiceSupabase: vi.fn(),
}));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: mockCreateServiceSupabase }));

import { POST, DELETE } from '../route';

const DEPRECATED = '11111111-1111-1111-1111-111111111111';
const CANONICAL = '22222222-2222-2222-2222-222222222222';

function makeRequest(method: 'POST' | 'DELETE', body: unknown) {
  return new Request('http://localhost/api/team-merge', {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }) as NextRequest;
}

let svc: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  svc = serviceClientMock();
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

describe('POST /api/team-merge (execute merge)', () => {
  it('returns the requireAdmin error and never touches the database for a non-admin', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await POST(
      makeRequest('POST', { deprecatedTeamId: DEPRECATED, canonicalTeamId: CANONICAL, mergedBy: 'admin-1' })
    );

    expect(res.status).toBe(403);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('returns 400 when a malformed JSON body cannot be parsed', async () => {
    const bad = new Request('http://localhost/api/team-merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{not json',
    }) as NextRequest;

    const res = await POST(bad);

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/invalid request body/i);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 400 when required fields are missing', async () => {
    const res = await POST(makeRequest('POST', { deprecatedTeamId: DEPRECATED }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/missing required fields/i);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 400 for a non-UUID team id before any query', async () => {
    const res = await POST(
      makeRequest('POST', { deprecatedTeamId: 'not-a-uuid', canonicalTeamId: CANONICAL, mergedBy: 'admin-1' })
    );

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/invalid team id format/i);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('returns 400 when merging a team with itself', async () => {
    const res = await POST(
      makeRequest('POST', { deprecatedTeamId: DEPRECATED, canonicalTeamId: DEPRECATED, mergedBy: 'admin-1' })
    );

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/with itself/i);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('executes the merge and returns both team names on success', async () => {
    svc.queueRpc({ data: { success: true, merge_id: 'merge-1' }, error: null });
    svc.queueFrom('teams', {
      data: [
        { team_id_master: DEPRECATED, team_name: 'Old FC' },
        { team_id_master: CANONICAL, team_name: 'New FC' },
      ],
      error: null,
    });

    const res = await POST(
      makeRequest('POST', {
        deprecatedTeamId: DEPRECATED,
        canonicalTeamId: CANONICAL,
        mergedBy: 'admin-1',
        mergeReason: 'dup',
      })
    );

    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({
      success: true,
      mergeId: 'merge-1',
      deprecatedTeamName: 'Old FC',
      canonicalTeamName: 'New FC',
    });
    // The merge must go through the SECURITY DEFINER RPC, not a raw update.
    expect(svc.rpc).toHaveBeenCalledWith(
      'execute_team_merge',
      expect.objectContaining({
        p_deprecated_team_id: DEPRECATED,
        p_canonical_team_id: CANONICAL,
        p_merged_by: 'admin-1',
      })
    );
  });

  it('maps an "already merged" RPC failure to 409', async () => {
    svc.queueRpc({ data: { success: false, error: 'team is already deprecated' }, error: null });

    const res = await POST(
      makeRequest('POST', { deprecatedTeamId: DEPRECATED, canonicalTeamId: CANONICAL, mergedBy: 'admin-1' })
    );

    expect(res.status).toBe(409);
    expect((await res.json()).error).toMatch(/already been merged/i);
  });

  it('maps a circular/chain RPC failure to 400', async () => {
    svc.queueRpc({ data: { success: false, error: 'canonical team is marked as deprecated' }, error: null });

    const res = await POST(
      makeRequest('POST', { deprecatedTeamId: DEPRECATED, canonicalTeamId: CANONICAL, mergedBy: 'admin-1' })
    );

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/circular or chain/i);
  });

  it('maps a "does not exist" RPC failure to 404', async () => {
    svc.queueRpc({ data: { success: false, error: 'team does not exist' }, error: null });

    const res = await POST(
      makeRequest('POST', { deprecatedTeamId: DEPRECATED, canonicalTeamId: CANONICAL, mergedBy: 'admin-1' })
    );

    expect(res.status).toBe(404);
  });

  it('returns 500 on an unexpected PostgREST error', async () => {
    svc.queueRpc({ data: null, error: { message: 'connection reset' } });

    const res = await POST(
      makeRequest('POST', { deprecatedTeamId: DEPRECATED, canonicalTeamId: CANONICAL, mergedBy: 'admin-1' })
    );

    expect(res.status).toBe(500);
  });
});

describe('DELETE /api/team-merge (revert merge)', () => {
  it('returns the requireAdmin error for a non-admin', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Not authenticated' }, { status: 401 }),
    });

    const res = await DELETE(makeRequest('DELETE', { deprecatedTeamId: DEPRECATED, revertedBy: 'admin-1' }));

    expect(res.status).toBe(401);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 400 when required fields are missing', async () => {
    const res = await DELETE(makeRequest('DELETE', { deprecatedTeamId: DEPRECATED }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/missing required fields/i);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 400 for a non-UUID team id', async () => {
    const res = await DELETE(makeRequest('DELETE', { deprecatedTeamId: 'nope', revertedBy: 'admin-1' }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/invalid team id format/i);
  });

  it('returns 404 when the team has no merge record', async () => {
    svc.queueFrom('teams', { data: { team_name: 'Old FC' }, error: null });
    svc.queueFrom('team_merge_map', { data: null, error: null });

    const res = await DELETE(makeRequest('DELETE', { deprecatedTeamId: DEPRECATED, revertedBy: 'admin-1' }));

    expect(res.status).toBe(404);
    expect((await res.json()).error).toMatch(/not currently merged/i);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('returns 500 when the merge-record lookup errors', async () => {
    svc.queueFrom('teams', { data: { team_name: 'Old FC' }, error: null });
    svc.queueFrom('team_merge_map', { data: null, error: { message: 'boom' } });

    const res = await DELETE(makeRequest('DELETE', { deprecatedTeamId: DEPRECATED, revertedBy: 'admin-1' }));

    expect(res.status).toBe(500);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('reverts the merge by resolved merge id and returns the team name', async () => {
    svc.queueFrom('teams', { data: { team_name: 'Old FC' }, error: null });
    svc.queueFrom('team_merge_map', { data: { id: 'merge-1' }, error: null });
    svc.queueRpc({ data: { success: true }, error: null });

    const res = await DELETE(
      makeRequest('DELETE', { deprecatedTeamId: DEPRECATED, revertedBy: 'admin-1', revertReason: 'oops' })
    );

    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ success: true, teamName: 'Old FC' });
    expect(svc.rpc).toHaveBeenCalledWith(
      'revert_team_merge',
      expect.objectContaining({ p_merge_id: 'merge-1', p_reverted_by: 'admin-1' })
    );
  });

  it('maps a "not merged" revert RPC failure to 404', async () => {
    svc.queueFrom('teams', { data: { team_name: 'Old FC' }, error: null });
    svc.queueFrom('team_merge_map', { data: { id: 'merge-1' }, error: null });
    svc.queueRpc({ data: { success: false, error: 'merge not found' }, error: null });

    const res = await DELETE(makeRequest('DELETE', { deprecatedTeamId: DEPRECATED, revertedBy: 'admin-1' }));

    expect(res.status).toBe(404);
  });
});
