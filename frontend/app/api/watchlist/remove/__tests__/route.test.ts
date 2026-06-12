import { describe, it, expect, vi, beforeEach } from 'vitest';

// Hoisted so they're available inside the vi.mock factory (which is hoisted)
const { mockRequirePremium, mockSupabaseFrom } = vi.hoisted(() => ({
  mockRequirePremium: vi.fn(),
  mockSupabaseFrom: vi.fn(),
}));

vi.mock('@/lib/api/requirePremium', () => ({
  requirePremium: mockRequirePremium,
}));

import { POST } from '../route';

function makeRequest(body: unknown): Request {
  return new Request('http://localhost/api/watchlist/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

describe('POST /api/watchlist/remove', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Authorized premium user with a supabase client whose `from` we can assert on
    mockRequirePremium.mockResolvedValue({
      user: { id: 'user-1' },
      supabase: { from: mockSupabaseFrom },
      error: null,
    });
  });

  it('rejects a non-UUID teamIdMaster carrying PostgREST filter syntax before any query', async () => {
    const res = await POST(makeRequest({ teamIdMaster: 'not-a-uuid; or=(1,1)' }));

    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/invalid team id/i);
    // The injection guard fires before any supabase query — no .from() call.
    expect(mockSupabaseFrom).not.toHaveBeenCalled();
  });

  it('returns 400 when teamIdMaster is missing', async () => {
    const res = await POST(makeRequest({}));

    expect(res.status).toBe(400);
    expect(mockSupabaseFrom).not.toHaveBeenCalled();
  });
});
