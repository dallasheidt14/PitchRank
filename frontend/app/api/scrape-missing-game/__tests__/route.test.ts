import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockRequirePremium, mockCreateClient } = vi.hoisted(() => ({
  mockRequirePremium: vi.fn(),
  mockCreateClient: vi.fn(),
}));

vi.mock('@/lib/api/requirePremium', () => ({ requirePremium: mockRequirePremium }));
vi.mock('@supabase/supabase-js', () => ({ createClient: mockCreateClient }));

import { POST } from '../route';

function makeRequest(body: unknown) {
  return new Request('http://localhost/api/scrape-missing-game', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }) as NextRequest;
}

const validBody = {
  teamId: '11111111-1111-1111-1111-111111111111',
  teamName: 'Test FC 14B',
  gameDate: '2026-01-15',
};

let svc: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  svc = serviceClientMock();
  process.env.SUPABASE_SERVICE_ROLE_KEY = 'service-key';
  process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://project.supabase.co';
  mockRequirePremium.mockResolvedValue({ user: { id: 'user-1' }, supabase: {}, error: null });
  mockCreateClient.mockReturnValue(svc.client);
});

describe('POST /api/scrape-missing-game', () => {
  it('enqueues for a premium non-admin — the Missing Games button is not admin-only', async () => {
    svc.queueFrom('teams', { data: { provider_id: 1, provider_team_id: '9999' }, error: null });
    svc.queueRpc({ data: 'request-1', error: null });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ success: true, requestId: 'request-1' });
    expect(svc.rpc).toHaveBeenCalledWith(
      'enqueue_scrape_request',
      expect.objectContaining({ p_team_id_master: validBody.teamId, p_priority: 1 })
    );
  });

  it('returns the requirePremium error and never touches the database for a free user', async () => {
    mockRequirePremium.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Premium required' }, { status: 403 }),
    });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(403);
    expect(mockCreateClient).not.toHaveBeenCalled();
  });
});
