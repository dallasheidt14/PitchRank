import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NextRequest } from 'next/server';

vi.mock('server-only', () => ({}));

const { mockAlert, mockConfirmation, mockCheckRateLimit, mockCreateServiceSupabase } = vi.hoisted(() => ({
  mockAlert: vi.fn(),
  mockConfirmation: vi.fn(),
  mockCheckRateLimit: vi.fn(),
  mockCreateServiceSupabase: vi.fn(),
}));

vi.mock('@/lib/email', () => ({
  sendMatchBalanceInquiryAlert: mockAlert,
  sendMatchBalanceInquiryConfirmation: mockConfirmation,
}));

vi.mock('@/lib/api/rateLimit', () => ({
  checkRateLimit: mockCheckRateLimit,
  getClientIp: (request: Request) => request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown',
}));

vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: mockCreateServiceSupabase }));

import { POST } from '../route';

/**
 * A service client whose insert records only when it is awaited. A PostgREST builder
 * does nothing until it is executed, so a double that records at `.insert()` would
 * report a saved lead for a route that dropped the `await`.
 */
function deferredInsertClient(result: { error: unknown }) {
  const executed: unknown[] = [];
  const from = vi.fn(() => ({
    insert: (payload: unknown) => ({
      then: (onFulfilled: (value: unknown) => unknown, onRejected?: (reason: unknown) => unknown) => {
        executed.push(payload);
        return Promise.resolve(result).then(onFulfilled, onRejected);
      },
    }),
  }));
  return { client: { from }, from, executed };
}

function makeRequest(body: unknown, headers: Record<string, string> = {}) {
  return new Request('http://localhost/api/matchbalance-inquiry', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-forwarded-for': '203.0.113.42',
      ...headers,
    },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  }) as NextRequest;
}

const OPENED = '2026-09-16T18:00:00.000Z';
const SUBMITTED = '2026-09-16T18:01:30.000Z';

const validBody = {
  name: 'Pat Director',
  email: 'pat@example.com',
  organization: 'Alamo Soccer Events',
  tournamentName: 'Labor Cup 2026',
  eventDates: 'Sep 5-7, 2026',
  teamCount: 180,
  bracketReviewDate: '2026-08-20',
  eventUrl: 'https://system.gotsport.com/org_event/events/12345',
  requestType: 'quote',
  notes: 'We run U9-U19.',
  openedAt: OPENED,
  submittedAt: SUBMITTED,
};

const REQUIRED_BARE = {
  name: 'Pat Director',
  email: 'pat@example.com',
  organization: 'Alamo Soccer Events',
  tournamentName: 'Labor Cup 2026',
  eventDates: 'Sep 5-7, 2026',
  requestType: 'sample',
  openedAt: OPENED,
  submittedAt: SUBMITTED,
};

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

let db: ReturnType<typeof deferredInsertClient>;

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  db = deferredInsertClient({ error: null });
  mockCreateServiceSupabase.mockReturnValue(db.client);
  mockCheckRateLimit.mockReturnValue(true);
  mockAlert.mockResolvedValue(true);
  mockConfirmation.mockResolvedValue(true);
});

describe('POST /api/matchbalance-inquiry', () => {
  it('saves one lead, sends both emails and returns 201', async () => {
    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ ok: true });
    expect(db.from).toHaveBeenCalledWith('matchbalance_leads');
    expect(db.executed).toEqual([
      {
        name: 'Pat Director',
        email: 'pat@example.com',
        organization: 'Alamo Soccer Events',
        tournament_name: 'Labor Cup 2026',
        event_dates: 'Sep 5-7, 2026',
        team_count: 180,
        bracket_review_date: '2026-08-20',
        event_url: 'https://system.gotsport.com/org_event/events/12345',
        request_type: 'quote',
        notes: 'We run U9-U19.',
        source_ip_masked: '203.0.113.x',
      },
    ]);

    const lead = {
      name: 'Pat Director',
      email: 'pat@example.com',
      organization: 'Alamo Soccer Events',
      tournamentName: 'Labor Cup 2026',
      eventDates: 'Sep 5-7, 2026',
      teamCount: 180,
      bracketReviewDate: '2026-08-20',
      eventUrl: 'https://system.gotsport.com/org_event/events/12345',
      requestType: 'quote',
      notes: 'We run U9-U19.',
    };
    expect(mockAlert).toHaveBeenCalledTimes(1);
    expect(mockAlert).toHaveBeenCalledWith(lead);
    expect(mockConfirmation).toHaveBeenCalledTimes(1);
    expect(mockConfirmation).toHaveBeenCalledWith(lead);
  });

  it('keys the rate limit by IP with five per hour', async () => {
    await POST(makeRequest(validBody));

    expect(mockCheckRateLimit).toHaveBeenCalledWith('matchbalance:203.0.113.42', 5, 3_600_000);
  });

  it.each([
    ['name', 'Your name'],
    ['email', 'Email'],
    ['organization', 'Organization'],
    ['tournamentName', 'Tournament name'],
    ['eventDates', 'Event dates'],
    ['requestType', 'free sample or a quote'],
  ])('400 when required field %s is missing, and nothing is saved', async (field, message) => {
    const body: Record<string, unknown> = { ...validBody };
    delete body[field];

    const res = await POST(makeRequest(body));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toContain(message);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
    expect(mockAlert).not.toHaveBeenCalled();
  });

  it.each([
    ['name', ' '.repeat(3), 'Your name'],
    ['name', 'a'.repeat(121), 'Your name'],
    ['email', 'not-an-email', 'Email'],
    ['organization', 'o'.repeat(161), 'Organization'],
    ['tournamentName', 't'.repeat(201), 'Tournament name'],
    ['eventDates', 'd'.repeat(121), 'Event dates'],
    ['notes', 'n'.repeat(2001), 'Notes'],
    ['email', `${'a'.repeat(243)}@example.com`, 'Email'],
  ])('400 when %s is blank or too long', async (field, value, message) => {
    const res = await POST(makeRequest({ ...validBody, [field]: value }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toContain(message);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it.each([
    ['teamCount', 6000, 'Number of teams'],
    ['teamCount', -5, 'Number of teams'],
    ['teamCount', 12.5, 'Number of teams'],
    ['teamCount', '180', 'Number of teams'],
    ['bracketReviewDate', '31/12/2026', 'Bracket review date'],
    ['bracketReviewDate', '2026-02-31', 'Bracket review date'],
    ['eventUrl', 'ftp://example.com/event', 'Event link'],
    ['eventUrl', 'not a url', 'Event link'],
    ['eventUrl', `https://example.com/${'x'.repeat(490)}`, 'Event link'],
    ['requestType', 'other', 'free sample or a quote'],
  ])('400 when %s is %s, naming the field', async (field, value, message) => {
    const res = await POST(makeRequest({ ...validBody, [field]: value }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toContain(message);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
    expect(mockCheckRateLimit).not.toHaveBeenCalled();
  });

  it('accepts a submission with every optional field absent, saving them as null', async () => {
    const res = await POST(makeRequest(REQUIRED_BARE));

    expect(res.status).toBe(201);
    expect(db.executed).toEqual([
      {
        name: 'Pat Director',
        email: 'pat@example.com',
        organization: 'Alamo Soccer Events',
        tournament_name: 'Labor Cup 2026',
        event_dates: 'Sep 5-7, 2026',
        team_count: null,
        bracket_review_date: null,
        event_url: null,
        request_type: 'sample',
        notes: null,
        source_ip_masked: '203.0.113.x',
      },
    ]);
  });

  it('treats an empty string in every optional field as absent', async () => {
    const res = await POST(
      makeRequest({ ...REQUIRED_BARE, teamCount: '', bracketReviewDate: '', eventUrl: '  ', notes: '' })
    );

    expect(res.status).toBe(201);
    expect(db.executed).toEqual([
      expect.objectContaining({ team_count: null, bracket_review_date: null, event_url: null, notes: null }),
    ]);
  });

  it('201 (silent) and saves nothing when the honeypot is filled', async () => {
    const res = await POST(makeRequest({ ...validBody, website: 'http://spam.example' }));

    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ ok: true });
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
    expect(mockCheckRateLimit).not.toHaveBeenCalled();
    expect(mockAlert).not.toHaveBeenCalled();
    expect(mockConfirmation).not.toHaveBeenCalled();
  });

  it('201 (silent) and saves nothing when the form was filled too fast', async () => {
    const res = await POST(makeRequest({ ...validBody, submittedAt: '2026-09-16T18:00:00.500Z' }));

    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ ok: true });
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
    expect(mockCheckRateLimit).not.toHaveBeenCalled();
    expect(mockAlert).not.toHaveBeenCalled();
    expect(mockConfirmation).not.toHaveBeenCalled();
  });

  it('checks fill time before validation, so fast garbage is also a silent 201', async () => {
    const { name: _name, ...missingName } = validBody;

    const res = await POST(makeRequest({ ...missingName, submittedAt: '2026-09-16T18:00:00.500Z' }));

    expect(res.status).toBe(201);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  // One fixture per half: with only openedAt unparseable, the difference is NaN,
  // NaN < 2000 is false, and the dwell floor would otherwise wave the body through.
  it.each([
    ['missing', { openedAt: undefined, submittedAt: undefined }],
    ['an unparseable openedAt', { openedAt: 'not-a-date' }],
    ['an unparseable submittedAt', { submittedAt: 'not-a-date' }],
  ])('400 when timestamps are %s', async (_label, timestamps) => {
    const res = await POST(makeRequest({ ...validBody, ...timestamps }));

    expect(res.status).toBe(400);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('429 with Retry-After when the rate limit denies, saving nothing', async () => {
    mockCheckRateLimit.mockReturnValue(false);

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(429);
    expect(res.headers.get('Retry-After')).toBe('3600');
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
    expect(mockAlert).not.toHaveBeenCalled();
  });

  it('never spends a rate-limit slot on an invalid body', async () => {
    const res = await POST(makeRequest({ ...validBody, email: 'nope' }));

    expect(res.status).toBe(400);
    expect(mockCheckRateLimit).not.toHaveBeenCalled();
  });

  it('415 for a body that is not declared as JSON, so another site cannot post without a preflight', async () => {
    const res = await POST(makeRequest(validBody, { 'Content-Type': 'text/plain' }));

    expect(res.status).toBe(415);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
    expect(mockCheckRateLimit).not.toHaveBeenCalled();
  });

  it('saves an http event link, a trimmed email, and a masked IPv6 address', async () => {
    const res = await POST(
      makeRequest(
        { ...validBody, email: '  pat@example.com  ', eventUrl: 'http://example.com/cup' },
        { 'x-forwarded-for': '2001:db8::1' }
      )
    );

    expect(res.status).toBe(201);
    expect(db.executed).toEqual([
      expect.objectContaining({
        email: 'pat@example.com',
        event_url: 'http://example.com/cup',
        source_ip_masked: '2001:db8::x',
      }),
    ]);
    expect(mockConfirmation).toHaveBeenCalledWith(expect.objectContaining({ email: 'pat@example.com' }));
  });

  it('400 on malformed JSON', async () => {
    const res = await POST(makeRequest('{not valid'));

    expect(res.status).toBe(400);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('400 when the JSON body is literal null or an array', async () => {
    for (const raw of ['null', '[]']) {
      const res = await POST(makeRequest(raw));
      expect(res.status).toBe(400);
    }
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it('500 and no email when the insert fails', async () => {
    db = deferredInsertClient({ error: { message: 'relation does not exist' } });
    mockCreateServiceSupabase.mockReturnValue(db.client);

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(500);
    expect(db.executed).toHaveLength(1);
    expect(mockAlert).not.toHaveBeenCalled();
    expect(mockConfirmation).not.toHaveBeenCalled();
  });

  it('500 and no email when the service client cannot be built', async () => {
    mockCreateServiceSupabase.mockImplementation(() => {
      throw new Error('Missing Supabase service environment variables');
    });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(500);
    expect(mockAlert).not.toHaveBeenCalled();
    expect(mockConfirmation).not.toHaveBeenCalled();
  });

  it('still 201 when the owner alert fails, and the confirmation still goes out', async () => {
    mockAlert.mockResolvedValue(false);

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(201);
    expect(mockConfirmation).toHaveBeenCalledTimes(1);
  });

  it('still 201 when the confirmation fails, and the owner alert still goes out', async () => {
    mockConfirmation.mockResolvedValue(false);

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(201);
    expect(mockAlert).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['alert', 'confirmation'],
    ['confirmation', 'alert'],
  ] as const)('does not respond until both emails have finished sending (%s released first)', async (first, second) => {
    const release: Record<'alert' | 'confirmation', () => void> = { alert: () => {}, confirmation: () => {} };
    mockAlert.mockImplementation(
      () =>
        new Promise<boolean>((resolve) => {
          release.alert = () => resolve(true);
        })
    );
    mockConfirmation.mockImplementation(
      () =>
        new Promise<boolean>((resolve) => {
          release.confirmation = () => resolve(true);
        })
    );

    let settled = false;
    const pending = POST(makeRequest(validBody)).then((res) => {
      settled = true;
      return res;
    });

    // Before both senders are invoked, the route is pending on the body and the insert
    // whether or not it awaits the sends, so asserting earlier would prove nothing.
    await vi.waitFor(() => expect(mockAlert).toHaveBeenCalled());
    await vi.waitFor(() => expect(mockConfirmation).toHaveBeenCalled());
    expect(settled).toBe(false);

    release[first]();
    await flush();
    expect(settled).toBe(false);

    release[second]();
    const res = await pending;
    expect(res.status).toBe(201);
  });
});
