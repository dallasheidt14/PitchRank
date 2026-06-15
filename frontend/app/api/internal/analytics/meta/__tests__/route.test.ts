import { describe, it, expect, vi, beforeEach } from 'vitest';
import { NextResponse } from 'next/server';

const { mockRequireAdmin } = vi.hoisted(() => ({ mockRequireAdmin: vi.fn() }));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));

import { GET } from '../route';

beforeEach(() => {
  vi.clearAllMocks();
  mockRequireAdmin.mockResolvedValue({
    user: { id: 'admin-1', email: 'admin@pitchrank.io' },
    supabase: {},
    error: null,
  });
});

describe('GET /api/internal/analytics/meta', () => {
  it('returns the requireAdmin error for a non-admin', async () => {
    mockRequireAdmin.mockResolvedValue({
      user: null,
      supabase: null,
      error: NextResponse.json({ error: 'Admin access required' }, { status: 403 }),
    });

    const res = await GET();

    expect(res.status).toBe(403);
  });

  it('returns the analytics config for an admin', async () => {
    const res = await GET();

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ admin_email: 'admin@pitchrank.io', timezone: 'America/Phoenix' });
    expect(Array.isArray(body.presets)).toBe(true);
    expect(body.default_preset).toBeTruthy();
    expect(body.ga4_property_id).toBeTruthy();
    expect(body.gsc_site_url).toBeTruthy();
  });

  it('reports a null admin_email when the admin has no email', async () => {
    mockRequireAdmin.mockResolvedValue({ user: { id: 'admin-1' }, supabase: {}, error: null });

    const res = await GET();

    expect(res.status).toBe(200);
    expect((await res.json()).admin_email).toBeNull();
  });
});
