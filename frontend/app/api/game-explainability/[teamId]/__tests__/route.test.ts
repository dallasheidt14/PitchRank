import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextResponse } from 'next/server';

const { mockCreateServiceSupabase, mockFrom, mockSelect, mockEq, mockIn, mockOrder, mockRequirePremium } = vi.hoisted(
  () => ({
    mockCreateServiceSupabase: vi.fn(),
    mockFrom: vi.fn(),
    mockSelect: vi.fn(),
    mockEq: vi.fn(),
    mockIn: vi.fn(),
    mockOrder: vi.fn(),
    mockRequirePremium: vi.fn(),
  })
);

vi.mock('@/lib/supabase/service', () => ({
  createServiceSupabase: mockCreateServiceSupabase,
}));

vi.mock('@/lib/api/requirePremium', () => ({
  requirePremium: mockRequirePremium,
}));

import { POST } from '../route';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';
const GAME_ID = '22222222-2222-2222-2222-222222222222';

function makeRequest(body: Record<string, unknown>) {
  return new Request('http://localhost/api/game-explainability', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
}

describe('POST /api/game-explainability/[teamId]', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockRequirePremium.mockResolvedValue({
      user: { id: 'test-user-id', email: 'test@example.com' },
      supabase: {},
      error: null,
    });

    mockOrder.mockReturnValue({
      data: [
        {
          team_id: TEAM_ID,
          game_uuid: GAME_ID,
          game_id: 'provider-game-1',
          opp_id: '33333333-3333-3333-3333-333333333333',
          game_date: '2026-04-01',
          gf: 3,
          ga: 1,
          rating_contribution: 0.12,
        },
      ],
      error: null,
    });
    mockIn.mockReturnValue({ order: mockOrder });
    mockEq.mockReturnValue({ in: mockIn });
    mockSelect.mockReturnValue({ eq: mockEq });
    mockFrom.mockReturnValue({ select: mockSelect });

    mockCreateServiceSupabase.mockReturnValue({ from: mockFrom });
  });

  it('returns 400 for an invalid team ID', async () => {
    const response = await POST(makeRequest({ gameIds: [GAME_ID] }), {
      params: Promise.resolve({ teamId: 'bad-id' }),
    });

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: 'Invalid team ID' });
  });

  it('returns 400 for invalid game IDs', async () => {
    const response = await POST(makeRequest({ gameIds: ['not-a-uuid'] }), {
      params: Promise.resolve({ teamId: TEAM_ID }),
    });

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ error: 'All game IDs must be valid UUIDs' });
  });

  it('returns an empty array when no game IDs are requested', async () => {
    const response = await POST(makeRequest({ gameIds: [] }), {
      params: Promise.resolve({ teamId: TEAM_ID }),
    });

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ breakdowns: [] });
  });

  it('returns breakdowns for a valid premium request', async () => {
    const response = await POST(makeRequest({ gameIds: [GAME_ID, GAME_ID] }), {
      params: Promise.resolve({ teamId: TEAM_ID }),
    });
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(mockFrom).toHaveBeenCalledWith('game_explainability');
    expect(mockEq).toHaveBeenCalledWith('team_id', TEAM_ID);
    expect(mockIn).toHaveBeenCalledWith('game_uuid', [GAME_ID]);
    expect(body.breakdowns).toHaveLength(1);
    expect(body.breakdowns[0].rating_contribution).toBe(0.12);
  });

  it('returns 401 when requirePremium fails', async () => {
    mockRequirePremium.mockResolvedValueOnce({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Not authenticated' }, { status: 401 }),
    });

    const response = await POST(makeRequest({ gameIds: [GAME_ID] }), {
      params: Promise.resolve({ teamId: TEAM_ID }),
    });

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: 'Not authenticated' });
  });
});
