import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse, type NextRequest } from 'next/server';
import { filteringClientMock, serviceClientMock } from '@/test/supabase-mock';

const { mockRequirePremium, mockCheckRateLimit, mockCreateClient } = vi.hoisted(() => ({
  mockRequirePremium: vi.fn(),
  mockCheckRateLimit: vi.fn(),
  mockCreateClient: vi.fn(),
}));

vi.mock('@/lib/api/requirePremium', () => ({ requirePremium: mockRequirePremium }));
vi.mock('@/lib/api/rateLimit', () => ({ checkRateLimit: mockCheckRateLimit }));
vi.mock('@supabase/supabase-js', () => ({ createClient: mockCreateClient }));
vi.mock('@/lib/notifications/admin', () => ({ notifyAdmin: vi.fn().mockResolvedValue(undefined) }));

import { notifyAdmin } from '@/lib/notifications/admin';
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
  mockCheckRateLimit.mockReturnValue(true);
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

  it('alerts the missing-games chat once the request is queued', async () => {
    process.env.TELEGRAM_MISSING_GAMES_CHAT_ID = '-100123';
    svc.queueFrom('teams', { data: { provider_id: 1, provider_team_id: '9999' }, error: null });
    svc.queueRpc({ data: 'request-1', error: null });

    await POST(makeRequest({ ...validBody, teamName: 'A&B <FC>' }));

    expect(vi.mocked(notifyAdmin)).toHaveBeenCalledWith(
      expect.stringContaining('<b>A&amp;B &lt;FC&gt;</b>'),
      '-100123'
    );
  });

  it('sends no alert when the enqueue fails', async () => {
    svc.queueFrom('teams', { data: { provider_id: 1, provider_team_id: '9999' }, error: null });
    svc.queueRpc({ data: null, error: { message: 'boom' } });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(500);
    expect(vi.mocked(notifyAdmin)).not.toHaveBeenCalled();
  });

  describe('when the queue refuses the click because another request is already waiting', () => {
    const refused = {
      data: null,
      error: { code: '23505', message: 'An active scrape uses a different source or date; request unchanged' },
    };

    const MERGED_AWAY = '33333333-3333-3333-3333-333333333333';

    function refusingClient(scrapeRequests: Record<string, unknown>[], merges: Record<string, unknown>[] = []) {
      const db = filteringClientMock({
        // A merged-away team keeps its row, so a stale page can still post its id.
        teams: [
          { team_id_master: validBody.teamId, provider_id: 1, provider_team_id: '383011' },
          { team_id_master: MERGED_AWAY, provider_id: 1, provider_team_id: '461215' },
        ],
        team_merge_map: merges,
        scrape_requests: scrapeRequests,
      });
      const rpc = vi.fn().mockResolvedValue(refused);
      mockCreateClient.mockReturnValue({ from: db.client.from, rpc });
      return db;
    }

    // Filed under the team's other GotSport registration and a different date, which is
    // what the RPC refuses to rewrite.
    const waitingRequest = (id: string, teamIdMaster: string) => ({
      id,
      team_id_master: teamIdMaster,
      status: 'pending',
      priority: 2,
      request_type: 'yesterday_game',
      provider_id: 1,
      provider_team_id: '461215',
      game_date: '2026-11-01',
    });

    it("moves the team's waiting request to the front and reports success", async () => {
      const db = refusingClient([
        waitingRequest('waiting', validBody.teamId),
        { id: 'finished', team_id_master: validBody.teamId, status: 'completed', priority: 3 },
        { id: 'other-team', team_id_master: '22222222-2222-2222-2222-222222222222', status: 'pending', priority: 2 },
      ]);

      const res = await POST(makeRequest(validBody));

      expect(res.status).toBe(200);
      expect(await res.json()).toEqual({ success: true, requestId: 'waiting' });
      expect(db.tableRows.scrape_requests).toEqual([
        { ...waitingRequest('waiting', validBody.teamId), priority: 1 },
        { id: 'finished', team_id_master: validBody.teamId, status: 'completed', priority: 3 },
        { id: 'other-team', team_id_master: '22222222-2222-2222-2222-222222222222', status: 'pending', priority: 2 },
      ]);
      expect(vi.mocked(notifyAdmin)).toHaveBeenCalledTimes(1);
    });

    it('moves a waiting request filed under a team merged into this one, and no other merged team', async () => {
      const otherMerged = '44444444-4444-4444-4444-444444444444';
      const db = refusingClient(
        [waitingRequest('before-merge', MERGED_AWAY), waitingRequest('unrelated-merge', otherMerged)],
        [
          { deprecated_team_id: MERGED_AWAY, canonical_team_id: validBody.teamId },
          { deprecated_team_id: otherMerged, canonical_team_id: '55555555-5555-5555-5555-555555555555' },
        ]
      );

      const res = await POST(makeRequest(validBody));

      expect(res.status).toBe(200);
      expect(await res.json()).toEqual({ success: true, requestId: 'before-merge' });
      expect(db.tableRows.scrape_requests).toEqual([
        { ...waitingRequest('before-merge', MERGED_AWAY), priority: 1 },
        waitingRequest('unrelated-merge', otherMerged),
      ]);
    });

    it("moves the surviving team's waiting request when the click names a merged-away team", async () => {
      const db = refusingClient(
        [waitingRequest('survivor', validBody.teamId)],
        [{ deprecated_team_id: MERGED_AWAY, canonical_team_id: validBody.teamId }]
      );

      const res = await POST(makeRequest({ ...validBody, teamId: MERGED_AWAY }));

      expect(res.status).toBe(200);
      expect(await res.json()).toEqual({ success: true, requestId: 'survivor' });
      expect(db.tableRows.scrape_requests[0].priority).toBe(1);
    });

    it('still reports success when the waiting request is already being scraped', async () => {
      const db = refusingClient([
        { id: 'running', team_id_master: validBody.teamId, status: 'processing', priority: 2 },
      ]);

      const res = await POST(makeRequest(validBody));

      expect(res.status).toBe(200);
      expect(await res.json()).toEqual({ success: true, requestId: null });
      expect(db.tableRows.scrape_requests[0].priority).toBe(2);
      expect(vi.mocked(notifyAdmin)).toHaveBeenCalledTimes(1);
    });

    it('reports the failure and sends no alert when the request cannot be moved', async () => {
      const db = refusingClient([waitingRequest('waiting', validBody.teamId)]);
      db.failing.scrape_requests = { code: '57014', message: 'canceling statement due to statement timeout' };

      const res = await POST(makeRequest(validBody));

      expect(res.status).toBe(500);
      expect(db.tableRows.scrape_requests[0].priority).toBe(2);
      expect(vi.mocked(notifyAdmin)).not.toHaveBeenCalled();
    });
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

  it('caps a scripted caller by user id before anything reaches the queue', async () => {
    mockCheckRateLimit.mockReturnValue(false);

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(429);
    expect(mockCheckRateLimit).toHaveBeenCalledWith('scrape-missing-game:user-1', 10, 3_600_000);
    expect(mockCreateClient).not.toHaveBeenCalled();
  });
});
