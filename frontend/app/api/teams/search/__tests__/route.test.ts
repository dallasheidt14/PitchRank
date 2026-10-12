import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NextRequest } from 'next/server';
import { serviceClientMock } from '@/test/supabase-mock';

vi.mock('server-only', () => ({}));

const { mockCheckRateLimit, service } = vi.hoisted(() => ({
  mockCheckRateLimit: vi.fn(),
  service: { current: null as ReturnType<typeof serviceClientMock> | null },
}));

vi.mock('@/lib/api/rateLimit', () => ({
  checkRateLimit: mockCheckRateLimit,
  getClientIp: (request: Request) => request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown',
}));

vi.mock('@/lib/supabase/service', () => ({
  createServiceSupabase: () => service.current!.client,
}));

import { GET } from '../route';

const ROW = {
  team_id_master: 'team-1',
  team_name: 'Rebels SC 2014 Premier',
  club_name: 'Rebels SC',
  age_group: 'u13',
  gender: 'Female',
  state_code: 'CA',
  league: null,
  distinction: null,
  is_ranked: true,
  match_pos: 1,
};

function request(query: string) {
  return new Request(`http://localhost/api/teams/search?${query}`, {
    headers: { 'x-forwarded-for': '203.0.113.7' },
  }) as NextRequest;
}

function rpcArgs(call: number) {
  return service.current!.rpc.mock.calls[call] as unknown as [string, Record<string, unknown>];
}

describe('GET /api/teams/search', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockReturnValue(true);
    service.current = serviceClientMock();
  });

  it('sends the parsed query to search_teams with exactly its nine arguments', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    const res = await GET(request('q=rebels%20u13%20girls&limit=8'));

    expect(res.status).toBe(200);
    expect(service.current!.rpc).toHaveBeenCalledTimes(1);
    expect(rpcArgs(0)).toEqual([
      'search_teams',
      {
        p_terms: ['rebels'],
        p_age_groups: ['u13'],
        p_age_regex: '\\m(u13|bu13|gu13|13u)\\M',
        p_gender: 'Female',
        p_mode: 'exact',
        p_age_filter: [],
        p_gender_filter: null,
        p_state: null,
        p_limit: 8,
      },
    ]);
  });

  it('keeps the band slash, so 13/14 reaches the database as u13', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    await GET(request('q=13%2F14%20girls'));

    const [, args] = rpcArgs(0);
    expect(args.p_age_groups).toEqual(['u13']);
    expect(args.p_gender).toBe('Female');
    expect(args.p_terms).toEqual([]);
  });

  it('passes the caller filters through, including a comma-separated age bridge', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    await GET(request('q=rebels&ageGroup=u19,u18&gender=Male&stateCode=AZ'));

    const [, args] = rpcArgs(0);
    expect(args.p_age_filter).toEqual(['u19', 'u18']);
    expect(args.p_gender_filter).toBe('Male');
    expect(args.p_state).toBe('AZ');
  });

  it('falls back to similar and then relaxed only after an empty result', async () => {
    service.current!.queueRpc({ data: [], error: null }, { data: [], error: null }, { data: [ROW], error: null });

    const res = await GET(request('q=rebles%20u13'));
    const body = await res.json();

    expect(
      service.current!.rpc.mock.calls.map((c) => (c as unknown as [string, { p_mode: string }])[1].p_mode)
    ).toEqual(['exact', 'similar', 'relaxed']);
    expect(body.match).toBe('relaxed');
    expect(body.teams).toHaveLength(1);
  });

  it('stops at the first mode that returns rows', async () => {
    service.current!.queueRpc({ data: [], error: null }, { data: [ROW], error: null });

    const body = await (await GET(request('q=rebles'))).json();

    expect(service.current!.rpc).toHaveBeenCalledTimes(2);
    expect(body.match).toBe('similar');
  });

  it('treats an error as an error, never as an empty result', async () => {
    service.current!.queueRpc(
      { data: null, error: { code: '57014', message: 'canceling statement due to statement timeout' } },
      { data: [ROW], error: null }
    );

    const res = await GET(request('q=rebels'));

    expect(res.status).toBe(500);
    expect(service.current!.rpc).toHaveBeenCalledTimes(1);
  });

  it('retries a transient error once', async () => {
    service.current!.queueRpc(
      { data: null, error: { code: '08006', message: 'connection failure' } },
      { data: [ROW], error: null }
    );

    const res = await GET(request('q=rebels'));

    expect(res.status).toBe(200);
    expect(service.current!.rpc).toHaveBeenCalledTimes(2);
    expect(rpcArgs(1)[1].p_mode).toBe('exact');
  });

  it('gives up after one retry', async () => {
    service.current!.queueRpc(
      { data: null, error: { code: '08006', message: 'connection failure' } },
      { data: null, error: { code: '08006', message: 'connection failure' } },
      { data: [ROW], error: null }
    );

    const res = await GET(request('q=rebels'));

    expect(res.status).toBe(500);
    expect(service.current!.rpc).toHaveBeenCalledTimes(2);
  });

  // What supabase-js actually returns when the request never reaches Postgres: '' for a
  // failed fetch, no code at all for a non-JSON gateway page, PGRST000 when PostgREST
  // cannot connect.
  it.each([
    ['a failed fetch', { code: '', message: 'TypeError: fetch failed' }],
    ['a gateway page', { message: '<html>502 Bad Gateway</html>' }],
    ['PostgREST losing its connection', { code: 'PGRST000', message: 'Could not connect with the database' }],
  ])('retries %s once', async (_case, error) => {
    service.current!.queueRpc({ data: null, error }, { data: [ROW], error: null });

    const res = await GET(request('q=rebels'));

    expect(res.status).toBe(200);
    expect(service.current!.rpc).toHaveBeenCalledTimes(2);
  });

  it('does not retry an error that would fail the same way again', async () => {
    service.current!.queueRpc(
      { data: null, error: { code: 'PGRST202', message: 'Could not find the function' } },
      { data: [ROW], error: null }
    );

    const res = await GET(request('q=rebels'));

    expect(res.status).toBe(500);
    expect(service.current!.rpc).toHaveBeenCalledTimes(1);
  });

  it('sends a plain-text search with no age or gender constraint and the default limit', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    await GET(request('q=rebels'));

    expect(rpcArgs(0)).toEqual([
      'search_teams',
      {
        p_terms: ['rebels'],
        p_age_groups: [],
        p_age_regex: null,
        p_gender: null,
        p_mode: 'exact',
        p_age_filter: [],
        p_gender_filter: null,
        p_state: null,
        p_limit: 20,
      },
    ]);
  });

  it('skips the relaxed pass when the query names no age or gender to relax', async () => {
    service.current!.queueRpc({ data: [], error: null }, { data: [], error: null }, { data: [ROW], error: null });

    const body = await (await GET(request('q=rebels'))).json();

    expect(
      service.current!.rpc.mock.calls.map((c) => (c as unknown as [string, { p_mode: string }])[1].p_mode)
    ).toEqual(['exact', 'similar']);
    expect(body).toEqual({ teams: [], match: 'similar' });
  });

  it('relaxes a query whose only constraint is a gender', async () => {
    service.current!.queueRpc({ data: [], error: null }, { data: [], error: null }, { data: [ROW], error: null });

    const body = await (await GET(request('q=rebles%20girls'))).json();

    expect(
      service.current!.rpc.mock.calls.map((c) => (c as unknown as [string, { p_mode: string }])[1].p_mode)
    ).toEqual(['exact', 'similar', 'relaxed']);
    expect(body.match).toBe('relaxed');
  });

  it('reads at most the first 100 characters of the query', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    await GET(request(`q=rebels${'%20'.repeat(95)}lost`));

    expect(rpcArgs(0)[1].p_terms).toEqual(['rebels']);
  });

  it('never cuts the query inside an emoji', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    await GET(request(`q=${encodeURIComponent(`rebels ${'a'.repeat(30)} ${'b'.repeat(30)} ${'c'.repeat(30)}😀x`)}`));

    expect(JSON.stringify(rpcArgs(0)[1].p_terms)).not.toMatch(/\\ud8/i);
  });

  it('loosens only the terms of three or more letters or digits', async () => {
    service.current!.queueRpc({ data: [], error: null }, { data: [ROW], error: null });

    await GET(request("q=fc%20rebles%2020'"));

    expect(rpcArgs(0)[1]).toMatchObject({ p_mode: 'exact', p_terms: ['fc', 'rebles', "20'"] });
    expect(rpcArgs(1)[1]).toMatchObject({ p_mode: 'similar', p_terms: ['rebles'] });
  });

  it('keeps a query of short words to the exact pass, without the name-side age regex', async () => {
    service.current!.queueRpc({ data: [], error: null }, { data: [ROW], error: null });

    const body = await (await GET(request('q=fc%20sc%20u13'))).json();

    expect(service.current!.rpc).toHaveBeenCalledTimes(1);
    expect(rpcArgs(0)[1]).toMatchObject({ p_terms: ['fc', 'sc'], p_age_groups: ['u13'], p_age_regex: null });
    expect(body).toEqual({ teams: [], match: 'exact' });
  });

  it('leaves out the name-side age regex when there is no text to narrow on first', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    await GET(request('q=2014%20girls'));

    expect(rpcArgs(0)[1]).toMatchObject({ p_terms: [], p_age_groups: ['u12', 'u13'], p_age_regex: null });
  });

  it('runs only the exact pass for a query with no text words', async () => {
    service.current!.queueRpc({ data: [], error: null }, { data: [ROW], error: null });

    const body = await (await GET(request('q=u6&stateCode=VT'))).json();

    expect(service.current!.rpc).toHaveBeenCalledTimes(1);
    expect(body).toEqual({ teams: [], match: 'exact' });
  });

  it('returns nothing for a query that parses to no words, age or gender', async () => {
    const body = await (await GET(request('q=--&stateCode=AZ'))).json();

    expect(body).toEqual({ teams: [] });
    expect(service.current!.rpc).not.toHaveBeenCalled();
  });

  it('refuses with 429 when the limiter says so', async () => {
    mockCheckRateLimit.mockReturnValue(false);

    const res = await GET(request('q=rebels'));

    expect(res.status).toBe(429);
    expect(service.current!.rpc).not.toHaveBeenCalled();
    expect(mockCheckRateLimit).toHaveBeenCalledWith('team-search:203.0.113.7', 120, 60_000);
  });

  it('returns nothing for a query under two characters without calling the database', async () => {
    const body = await (await GET(request('q=a'))).json();

    expect(body).toEqual({ teams: [] });
    expect(service.current!.rpc).not.toHaveBeenCalled();
  });

  it('clamps the limit at 100', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    await GET(request('q=rebels&limit=500'));

    expect(rpcArgs(0)[1].p_limit).toBe(100);
  });

  it('returns the match pass and state as the state code', async () => {
    service.current!.queueRpc({ data: [ROW], error: null });

    const body = await (await GET(request('q=rebels'))).json();

    expect(body.match).toBe('exact');
    expect(body.teams[0]).toEqual({
      team_id_master: 'team-1',
      team_name: 'Rebels SC 2014 Premier',
      club_name: 'Rebels SC',
      age_group: 'u13',
      gender: 'Female',
      state_code: 'CA',
      state: 'CA',
      league: null,
      distinction: null,
      is_ranked: true,
    });
  });
});
