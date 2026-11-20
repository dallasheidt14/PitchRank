import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockRequireAdmin, mockCreateServiceSupabase } = vi.hoisted(() => ({
  mockRequireAdmin: vi.fn(),
  mockCreateServiceSupabase: vi.fn(),
}));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: mockCreateServiceSupabase }));
vi.mock('@/lib/supabase/server', () => ({ createServerSupabase: vi.fn() }));

import { POST } from '../route';

function makeRequest(body: unknown): NextRequest {
  return new NextRequest('http://localhost/api/announcements', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

let svc: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  svc = serviceClientMock();
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });
  mockCreateServiceSupabase.mockReturnValue(svc.client);
});

describe('POST /api/announcements', () => {
  it.each([
    ['a signed-out visitor', 401, 'Not authenticated'],
    ['a subscriber', 403, 'Admin access required'],
  ])('refuses %s and never builds the service client', async (_who, status, message) => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: message }, { status }),
    });

    const res = await POST(makeRequest({ message: 'Hello' }));

    expect(res.status).toBe(status);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });

  it("inserts through the service client, since the admin's session holds no write", async () => {
    const row = { id: 'a-1', message: 'Hello', author: 'D H', created_at: '2026-11-20T00:00:00Z' };
    svc.queueFrom('announcements', { data: row, error: null });

    const res = await POST(makeRequest({ message: 'Hello' }));

    expect(res.status).toBe(201);
    expect(await res.json()).toEqual({ announcement: row });
    expect(svc.from).toHaveBeenCalledWith('announcements');
    const builder = svc.from.mock.results[0].value as {
      insert: ReturnType<typeof vi.fn>;
      select: ReturnType<typeof vi.fn>;
    };
    expect(builder.insert).toHaveBeenCalledWith({ message: 'Hello', author: 'D H' });
    // Without select() the insert returns no row, and the response would carry no announcement.
    expect(builder.select).toHaveBeenCalled();
  });

  it('rejects a missing message before building the service client', async () => {
    const res = await POST(makeRequest({ author: 'D H' }));

    expect(res.status).toBe(400);
    expect(mockCreateServiceSupabase).not.toHaveBeenCalled();
  });
});
