import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse } from 'next/server';

const { mockRequireAdmin, mockRevalidateTag } = vi.hoisted(() => ({
  mockRequireAdmin: vi.fn(),
  mockRevalidateTag: vi.fn(),
}));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('next/cache', () => ({ revalidateTag: mockRevalidateTag }));

import { POST } from '../route';

beforeEach(() => {
  vi.clearAllMocks();
  mockRequireAdmin.mockResolvedValue({
    user: { id: 'admin-1', email: 'admin@pitchrank.io' },
    supabase: {},
    error: null,
  });
});

describe('POST /api/internal/analytics/refresh', () => {
  it('returns the requireAdmin error and revalidates nothing for a non-admin', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await POST();

    expect(res.status).toBe(403);
    expect(mockRevalidateTag).not.toHaveBeenCalled();
  });

  it('busts both analytics cache tags and acknowledges for an admin', async () => {
    const res = await POST();

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(typeof body.refreshed_at).toBe('string');
    expect(mockRevalidateTag).toHaveBeenCalledWith('analytics:ga4', 'max');
    expect(mockRevalidateTag).toHaveBeenCalledWith('analytics:gsc', 'max');
  });
});
