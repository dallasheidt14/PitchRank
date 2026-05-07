import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NextRequest } from 'next/server';

vi.mock('server-only', () => ({}));

const { mockSendFeedback, mockCheckRateLimit, mockGetUser } = vi.hoisted(() => ({
  mockSendFeedback: vi.fn(),
  mockCheckRateLimit: vi.fn(),
  mockGetUser: vi.fn(),
}));

vi.mock('@/lib/email', () => ({
  sendFeedbackEmail: mockSendFeedback,
}));

vi.mock('@/lib/api/rateLimit', () => ({
  checkRateLimit: mockCheckRateLimit,
}));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: async () => ({
    auth: { getUser: mockGetUser },
  }),
}));

import { POST } from '../route';

const VALID_OPENED = '2026-05-06T18:00:00.000Z';
const VALID_SUBMITTED = '2026-05-06T18:00:05.000Z'; // 5s after open

function makeRequest(body: unknown) {
  return new Request('http://localhost/api/feedback', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-forwarded-for': '203.0.113.42',
    },
    body: JSON.stringify(body),
  }) as NextRequest;
}

const validBody = {
  category: 'rankings-wrong',
  message: 'My team is ranked too low for sure',
  context: {
    pathname: '/teams/abc-u14-boys',
    openedAt: VALID_OPENED,
    submittedAt: VALID_SUBMITTED,
  },
};

describe('POST /api/feedback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockReturnValue(true);
    mockSendFeedback.mockResolvedValue(true);
    mockGetUser.mockResolvedValue({ data: { user: null }, error: null });
  });

  it('200s on a valid signed-in submission and dispatches email', async () => {
    mockGetUser.mockResolvedValue({
      data: { user: { id: 'user-1', email: 'coach@example.com' } },
      error: null,
    });

    const res = await POST(makeRequest(validBody));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(mockSendFeedback).toHaveBeenCalledTimes(1);
    const sent = mockSendFeedback.mock.calls[0][0];
    expect(sent.identity).toEqual({ kind: 'signed-in', userId: 'user-1', email: 'coach@example.com' });
  });

  it('200s on a valid anonymous submission with replyTo email', async () => {
    const res = await POST(makeRequest({ ...validBody, email: 'anon@example.com' }));
    expect(res.status).toBe(200);
    expect(mockSendFeedback).toHaveBeenCalledOnce();
    const sent = mockSendFeedback.mock.calls[0][0];
    expect(sent.identity).toEqual({ kind: 'anonymous', email: 'anon@example.com' });
  });

  it('200s on a valid anonymous submission with no email', async () => {
    const res = await POST(makeRequest(validBody));
    expect(res.status).toBe(200);
    expect(mockSendFeedback).toHaveBeenCalledOnce();
    expect(mockSendFeedback.mock.calls[0][0].identity).toEqual({ kind: 'anonymous' });
  });

  it('400 when category is missing', async () => {
    const { category: _category, ...rest } = validBody;
    const res = await POST(makeRequest(rest));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when category is unknown', async () => {
    const res = await POST(makeRequest({ ...validBody, category: 'something-else' }));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when message is too short', async () => {
    const res = await POST(makeRequest({ ...validBody, message: 'short' }));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when message exceeds 2000 chars', async () => {
    const res = await POST(makeRequest({ ...validBody, message: 'a'.repeat(2001) }));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when an anonymous email is malformed', async () => {
    const res = await POST(makeRequest({ ...validBody, email: 'not-an-email' }));
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('200 (silent) but does not send when honeypot is filled', async () => {
    const res = await POST(makeRequest({ ...validBody, website: 'http://spam.example' }));
    expect(res.status).toBe(200);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('200 (silent) but does not send when min-time floor is violated', async () => {
    const res = await POST(
      makeRequest({
        ...validBody,
        context: {
          ...validBody.context,
          submittedAt: '2026-05-06T18:00:01.000Z', // only 1s after open
        },
      })
    );
    expect(res.status).toBe(200);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('429 when rate limit denies', async () => {
    mockCheckRateLimit.mockReturnValue(false);
    const res = await POST(makeRequest(validBody));
    expect(res.status).toBe(429);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('502 when sendFeedbackEmail returns false', async () => {
    mockSendFeedback.mockResolvedValue(false);
    const res = await POST(makeRequest(validBody));
    expect(res.status).toBe(502);
  });

  it('400 on malformed JSON body', async () => {
    const req = new Request('http://localhost/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-forwarded-for': '203.0.113.42' },
      body: '{not valid',
    }) as NextRequest;
    const res = await POST(req);
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('masks the IP last octet in the dispatched payload', async () => {
    await POST(makeRequest(validBody));
    expect(mockSendFeedback.mock.calls[0][0].ipMasked).toBe('203.0.113.x');
  });

  it('400 when the JSON body is literal null', async () => {
    const req = new Request('http://localhost/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-forwarded-for': '203.0.113.42' },
      body: 'null',
    }) as NextRequest;
    const res = await POST(req);
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when context.pathname is missing', async () => {
    const res = await POST(
      makeRequest({
        ...validBody,
        context: { openedAt: VALID_OPENED, submittedAt: VALID_SUBMITTED },
      })
    );
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('400 when timestamps fail to parse', async () => {
    const res = await POST(
      makeRequest({
        ...validBody,
        context: {
          pathname: '/teams/abc',
          openedAt: 'not-a-date',
          submittedAt: 'also-not-a-date',
        },
      })
    );
    expect(res.status).toBe(400);
    expect(mockSendFeedback).not.toHaveBeenCalled();
  });

  it('500 when the Supabase auth lookup throws', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockGetUser.mockRejectedValue(new Error('supabase unreachable'));
    const res = await POST(makeRequest(validBody));
    expect(res.status).toBe(500);
    expect(mockSendFeedback).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it('masks IPv6 addresses by dropping the last segment', async () => {
    const req = new Request('http://localhost/api/feedback', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-forwarded-for': '2001:db8:abcd:1234:5678:9abc:def0:1111',
      },
      body: JSON.stringify(validBody),
    }) as NextRequest;
    await POST(req);
    expect(mockSendFeedback).toHaveBeenCalled();
    const masked = mockSendFeedback.mock.calls[0][0].ipMasked;
    // Last segment replaced with 'x'.
    expect(masked.endsWith(':x')).toBe(true);
    expect(masked.startsWith('2001:db8:')).toBe(true);
  });

  it('returns "masked" for IPs that are neither IPv4 nor IPv6', async () => {
    const req = new Request('http://localhost/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-forwarded-for': 'garbage' },
      body: JSON.stringify(validBody),
    }) as NextRequest;
    await POST(req);
    expect(mockSendFeedback.mock.calls[0][0].ipMasked).toBe('masked');
  });

  it('demotes signed-in user with null email to anonymous and warns', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockGetUser.mockResolvedValue({
      data: { user: { id: 'user-no-email', email: null } },
      error: null,
    });

    const res = await POST(makeRequest({ ...validBody, email: 'fallback@example.com' }));

    expect(res.status).toBe(200);
    expect(mockSendFeedback).toHaveBeenCalledOnce();
    expect(mockSendFeedback.mock.calls[0][0].identity).toEqual({
      kind: 'anonymous',
      email: 'fallback@example.com',
    });
    expect(warnSpy).toHaveBeenCalledWith('[feedback] signed-in user has no email; treating as anonymous', {
      userId: 'user-no-email',
    });

    warnSpy.mockRestore();
  });
});
