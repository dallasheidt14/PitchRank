import { describe, it, expect, vi, beforeEach } from 'vitest';

// Hoisted so they're available inside the vi.mock factory (which is hoisted)
const { mockGetUser, mockUpdateUser } = vi.hoisted(() => ({
  mockGetUser: vi.fn(),
  mockUpdateUser: vi.fn(),
}));

vi.mock('@/lib/supabase/server', () => ({
  createServerSupabase: vi.fn().mockResolvedValue({
    auth: {
      getUser: mockGetUser,
      updateUser: mockUpdateUser,
    },
  }),
}));

import { updatePassword } from '../actions';

describe('updatePassword', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default to a valid recovery session unless a test overrides it
    mockGetUser.mockResolvedValue({ data: { user: { id: 'user-1' } } });
    mockUpdateUser.mockResolvedValue({ error: null });
  });

  it('rejects passwords shorter than 8 characters before touching the session', async () => {
    const res = await updatePassword('short');

    expect(res.error).toMatch(/8 characters/i);
    // Length is checked first — no session lookup or write should occur
    expect(mockGetUser).not.toHaveBeenCalled();
    expect(mockUpdateUser).not.toHaveBeenCalled();
  });

  it('rejects when the recovery session has expired (no user)', async () => {
    mockGetUser.mockResolvedValue({ data: { user: null } });

    const res = await updatePassword('a-valid-password');

    expect(res.error).toMatch(/expired/i);
    expect(mockUpdateUser).not.toHaveBeenCalled();
  });

  it('returns a friendly message and hides the raw Supabase text on same_password', async () => {
    mockUpdateUser.mockResolvedValue({ error: { code: 'same_password', message: 'raw-supabase-text' } });

    const res = await updatePassword('a-valid-password');

    expect(res.error).toMatch(/different/i);
    expect(res.error).not.toContain('raw-supabase-text');
  });

  it('returns a generic message on weak_password without leaking internal detail', async () => {
    mockUpdateUser.mockResolvedValue({ error: { code: 'weak_password', message: 'internal-detail' } });

    const res = await updatePassword('a-valid-password');

    expect(res.error).not.toBeNull();
    expect(res.error).not.toContain('internal-detail');
  });

  it('returns { error: null } on success', async () => {
    mockUpdateUser.mockResolvedValue({ error: null });

    const res = await updatePassword('a-valid-password');

    expect(res).toEqual({ error: null });
  });
});
