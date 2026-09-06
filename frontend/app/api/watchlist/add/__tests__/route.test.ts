import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NextResponse } from 'next/server';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockRequirePremium, mockResolveDefaultWatchlist, mockCheckRateLimit, mockCreateServiceSupabase } = vi.hoisted(
  () => ({
    mockRequirePremium: vi.fn(),
    mockResolveDefaultWatchlist: vi.fn(),
    mockCheckRateLimit: vi.fn(),
    mockCreateServiceSupabase: vi.fn(),
  })
);

vi.mock('@/lib/api/requirePremium', () => ({ requirePremium: mockRequirePremium }));
vi.mock('@/lib/api/watchlist', () => ({ resolveDefaultWatchlist: mockResolveDefaultWatchlist }));
vi.mock('@/lib/api/rateLimit', () => ({ checkRateLimit: mockCheckRateLimit }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: mockCreateServiceSupabase }));

import { POST } from '../route';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';
const PROVIDER_ID = '22222222-2222-2222-2222-222222222222';

const TEAM_ROW = {
  team_id_master: TEAM_ID,
  team_name: 'Sporting KC Academy 14B',
  provider_id: PROVIDER_ID,
  provider_team_id: '998877',
};

function makeRequest(body: unknown): Request {
  return new Request('http://localhost/api/watchlist/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

let auth: ReturnType<typeof serviceClientMock>;
let svc: ReturnType<typeof serviceClientMock>;

/** Queue the two reads/writes a successful add makes on the caller's client. */
function queueSuccessfulAdd(team: Record<string, unknown> | null = TEAM_ROW) {
  auth.queueFrom('teams', { data: team, error: team ? null : { message: 'not found' } });
  auth.queueFrom('watchlist_items', { data: [{ id: 'item-1' }], error: null });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  // A date whose UTC and local calendar days differ for a US operator, so the
  // assertion below pins the UTC day the RPC is actually given.
  vi.setSystemTime(new Date('2026-09-06T03:00:00Z'));
  auth = serviceClientMock();
  svc = serviceClientMock();
  mockRequirePremium.mockResolvedValue({ user: { id: 'user-1' }, supabase: auth.client, error: null });
  mockResolveDefaultWatchlist.mockResolvedValue({ watchlist: { id: 'wl-1' }, error: null });
  mockCheckRateLimit.mockReturnValue(true);
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('POST /api/watchlist/add', () => {
  it('enqueues the watchlisted team at priority 1 through the service client', async () => {
    queueSuccessfulAdd();

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(200);
    expect(svc.rpc).toHaveBeenCalledWith('enqueue_scrape_request', {
      p_team_id_master: TEAM_ID,
      p_team_name: 'Sporting KC Academy 14B',
      p_provider_id: PROVIDER_ID,
      p_provider_team_id: '998877',
      p_game_date: '2026-09-06',
      p_request_type: 'watchlist_add',
      p_priority: 1,
    });
  });

  it('uses the service client for the RPC, which authenticated has no grant to execute', async () => {
    queueSuccessfulAdd();

    await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(auth.rpc).not.toHaveBeenCalled();
  });

  it('skips the enqueue for a team with no provider, which the drainer cannot serve', async () => {
    queueSuccessfulAdd({ ...TEAM_ROW, provider_id: null });

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(200);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('does not enqueue when the watchlist write itself failed', async () => {
    auth.queueFrom('teams', { data: TEAM_ROW, error: null });
    auth.queueFrom('watchlist_items', { data: null, error: { message: 'insert failed' } });

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(500);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('still reports success when the enqueue RPC errors, since the team is already watchlisted', async () => {
    queueSuccessfulAdd();
    svc.queueRpc({ data: null, error: { message: 'rpc exploded' } });

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ success: true, teamIdMaster: TEAM_ID });
  });

  it('still adds the team when the enqueue rate limit is hit, and skips only the scrape', async () => {
    mockCheckRateLimit.mockReturnValue(false);
    queueSuccessfulAdd();

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(200);
    expect(auth.from).toHaveBeenCalledWith('watchlist_items');
    expect(svc.rpc).not.toHaveBeenCalled();
    expect(mockCheckRateLimit).toHaveBeenCalledWith('watchlist-enqueue:user-1', 100, 3_600_000);
  });

  it('leaves a pending priority-1 row alone, so a user-chosen game date is not re-anchored to today', async () => {
    queueSuccessfulAdd();
    svc.queueFrom('scrape_requests', { data: [{ id: 'req-1' }], error: null });

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(200);
    expect(svc.rpc).not.toHaveBeenCalled();

    // The lookup must be the one teams_with_pending_user_request makes: this
    // team's pending rows at priority 1, not merely any row for the team.
    const lookup = svc.from.mock.results[0].value;
    expect(lookup.eq).toHaveBeenCalledWith('team_id_master', TEAM_ID);
    expect(lookup.eq).toHaveBeenCalledWith('status', 'pending');
    expect(lookup.eq).toHaveBeenCalledWith('priority', 1);
  });

  it('enqueues when the team holds no pending priority-1 row', async () => {
    queueSuccessfulAdd();
    svc.queueFrom('scrape_requests', { data: [], error: null });

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(200);
    expect(svc.from).toHaveBeenCalledWith('scrape_requests');
    expect(svc.rpc).toHaveBeenCalledOnce();
  });

  it('skips the enqueue when the pending lookup fails, rather than overwriting blind', async () => {
    queueSuccessfulAdd();
    svc.queueFrom('scrape_requests', { data: null, error: { message: 'lookup exploded' } });

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(200);
    expect(svc.rpc).not.toHaveBeenCalled();
  });

  it('rejects a non-UUID teamIdMaster before any query', async () => {
    const res = await POST(makeRequest({ teamIdMaster: 'not-a-uuid; or=(1,1)' }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/invalid team id/i);
    expect(auth.from).not.toHaveBeenCalled();
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('never enqueues for a free user', async () => {
    mockRequirePremium.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Premium required' }, { status: 403 }),
    });

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(403);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('returns 404 without enqueueing when the team does not exist', async () => {
    queueSuccessfulAdd(null);

    const res = await POST(makeRequest({ teamIdMaster: TEAM_ID }));

    expect(res.status).toBe(404);
    expect(svc.rpc).not.toHaveBeenCalled();
  });
});
