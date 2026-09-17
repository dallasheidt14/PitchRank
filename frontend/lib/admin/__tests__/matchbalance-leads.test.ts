import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockCreateServiceSupabase } = vi.hoisted(() => ({
  mockCreateServiceSupabase: vi.fn(),
}));

vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: mockCreateServiceSupabase }));

import { fetchMatchBalanceLeads } from '../matchbalance-leads';

const NOW = Date.UTC(2026, 8, 16, 12, 0, 0);

const ROWS = [
  { id: 'lead-3', created_at: '2026-09-16T10:00:00Z', tournament_name: 'Labor Cup', status: 'new' },
  { id: 'lead-2', created_at: '2026-09-12T10:00:00Z', tournament_name: 'Fall Classic', status: 'contacted' },
  { id: 'lead-1', created_at: '2026-08-01T10:00:00Z', tournament_name: 'Summer Shootout', status: 'won' },
];

let svc: ReturnType<typeof serviceClientMock>;

/** The builder `.from()` handed back on its `index`th call. */
function builder(index: number) {
  return svc.from.mock.results[index].value;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ now: NOW });
  svc = serviceClientMock();
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

afterEach(() => {
  vi.useRealTimers();
});

describe('fetchMatchBalanceLeads', () => {
  it('returns the newest rows and reads each count from its own query', async () => {
    svc.queueFrom(
      'matchbalance_leads',
      { data: ROWS, error: null },
      { count: 11, error: null },
      { count: 7, error: null },
      { count: 5, error: null }
    );

    const result = await fetchMatchBalanceLeads();

    expect(result).toEqual({ leads: ROWS, total: 11, awaitingReply: 7, thisWeek: 5, errors: [] });
  });

  it('asks for the newest 200 rows, an unfiltered total, status new, and the last seven days', async () => {
    await fetchMatchBalanceLeads();

    expect(svc.from).toHaveBeenCalledTimes(4);
    expect(svc.from.mock.calls.every(([table]) => table === 'matchbalance_leads')).toBe(true);

    expect(builder(0).select).toHaveBeenCalledWith('*');
    expect(builder(0).order).toHaveBeenCalledWith('created_at', { ascending: false });
    expect(builder(0).limit).toHaveBeenCalledWith(200);

    expect(builder(1).select).toHaveBeenCalledWith('id', { count: 'exact', head: true });
    expect(builder(1).eq).not.toHaveBeenCalled();
    expect(builder(1).gte).not.toHaveBeenCalled();

    expect(builder(2).select).toHaveBeenCalledWith('id', { count: 'exact', head: true });
    expect(builder(2).eq).toHaveBeenCalledWith('status', 'new');
    expect(builder(2).gte).not.toHaveBeenCalled();

    expect(builder(3).select).toHaveBeenCalledWith('id', { count: 'exact', head: true });
    expect(builder(3).gte).toHaveBeenCalledWith('created_at', '2026-09-09T12:00:00.000Z');
    expect(builder(3).eq).not.toHaveBeenCalled();
  });

  // Queued in the function's query order: list, total, awaiting reply, this week.
  it.each([
    ['list', 0, 'leads list: relation missing', { leads: [], total: 11, awaitingReply: 7, thisWeek: 5 }],
    ['total', 1, 'leads total: total timed out', { leads: ROWS, total: 0, awaitingReply: 7, thisWeek: 5 }],
    [
      'awaiting reply',
      2,
      'leads awaiting reply: awaiting timed out',
      { leads: ROWS, total: 11, awaitingReply: 0, thisWeek: 5 },
    ],
    ['this week', 3, 'leads this week: week timed out', { leads: ROWS, total: 11, awaitingReply: 7, thisWeek: 0 }],
  ])('degrades only the %s figure when its query fails', async (_label, failing, message, expected) => {
    const results = [
      { data: ROWS, error: null },
      { count: 11, error: null },
      { count: 7, error: null },
      { count: 5, error: null },
    ];
    const failures = ['relation missing', 'total timed out', 'awaiting timed out', 'week timed out'];
    results[failing] = { data: null, count: null, error: { message: failures[failing] } } as never;
    svc.queueFrom('matchbalance_leads', ...results);

    const result = await fetchMatchBalanceLeads();

    expect(result).toEqual({ ...expected, errors: [message] });
  });

  it('returns empties and one error when the service client cannot be built', async () => {
    mockCreateServiceSupabase.mockImplementation(() => {
      throw new Error('Missing Supabase service environment variables');
    });

    const result = await fetchMatchBalanceLeads();

    expect(result).toEqual({
      leads: [],
      total: 0,
      thisWeek: 0,
      awaitingReply: 0,
      errors: ['leads client: Missing Supabase service environment variables'],
    });
  });
});
