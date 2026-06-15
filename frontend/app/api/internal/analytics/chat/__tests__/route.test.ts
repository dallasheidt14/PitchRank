import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse } from 'next/server';

const { mockRequireAdmin } = vi.hoisted(() => ({ mockRequireAdmin: vi.fn() }));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));

import { POST } from '../route';

const URL = 'http://localhost/api/internal/analytics/chat';

function textMessage(text: string) {
  return { role: 'user', parts: [{ type: 'text', text }] };
}

function chatRequest(body: unknown): Request {
  return new Request(URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** A request whose declared content-length trips the 413 guard before parsing. */
function oversizedRequest(): Request {
  const req = new Request(URL, { method: 'POST', body: '{}' });
  Object.defineProperty(req, 'headers', {
    value: new Headers({ 'content-length': '600000' }),
    configurable: true,
  });
  return req;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockRequireAdmin.mockResolvedValue({
    user: { id: 'admin-1', email: 'admin@pitchrank.io' },
    supabase: {},
    error: null,
  });
});

describe('POST /api/internal/analytics/chat', () => {
  it('returns the requireAdmin error for a non-admin', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await POST(chatRequest({ messages: [textMessage('hi')] }));

    expect(res.status).toBe(403);
  });

  it('rejects an oversized payload by content-length before parsing it (413)', async () => {
    const res = await POST(oversizedRequest());

    expect(res.status).toBe(413);
    expect((await res.json()).error).toMatch(/too large/i);
  });

  it('returns 400 when messages is empty', async () => {
    const res = await POST(chatRequest({ messages: [] }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/messages array is required/i);
  });

  it('returns 400 when messages is missing entirely', async () => {
    const res = await POST(chatRequest({ range: 'last_7_days' }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/messages array is required/i);
  });

  it('returns 400 when there are too many messages', async () => {
    const res = await POST(chatRequest({ messages: Array.from({ length: 51 }, () => textMessage('hi')) }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/too many messages/i);
  });

  it('returns 400 when the total conversation text is too large', async () => {
    const res = await POST(chatRequest({ messages: [textMessage('x'.repeat(100_001))] }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/conversation too large/i);
  });
});
