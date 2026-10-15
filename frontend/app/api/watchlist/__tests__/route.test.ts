// Each watchlist card says "Not ranked yet" only for a team short of games, so the route must carry the status.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { serviceClientMock } from '@/test/supabase-mock';

const { mockRequirePremium, mockResolveDefaultWatchlist } = vi.hoisted(() => ({
  mockRequirePremium: vi.fn(),
  mockResolveDefaultWatchlist: vi.fn(),
}));

vi.mock('@/lib/api/requirePremium', () => ({ requirePremium: mockRequirePremium }));
vi.mock('@/lib/api/watchlist', () => ({ resolveDefaultWatchlist: mockResolveDefaultWatchlist }));

import { GET } from '../route';

const FRESH = '11111111-1111-4111-8111-111111111111';
const QUIET = '22222222-2222-4222-8222-222222222222';

let db: ReturnType<typeof serviceClientMock>;

beforeEach(() => {
  vi.clearAllMocks();
  db = serviceClientMock();
  mockRequirePremium.mockResolvedValue({ user: { id: 'user-1' }, supabase: db.client, error: null });
  mockResolveDefaultWatchlist.mockResolvedValue({
    watchlist: { id: 'wl-1', name: 'My teams', is_default: true, created_at: '', updated_at: '' },
    error: null,
  });
});

describe('GET /api/watchlist', () => {
  it("carries each team's ranking status, and none for a team without a ranking row", async () => {
    db.queueFrom('watchlist_items', {
      data: [
        { team_id_master: FRESH, created_at: '2026-10-01T00:00:00Z' },
        { team_id_master: QUIET, created_at: '2026-10-02T00:00:00Z' },
      ],
      error: null,
    });
    db.queueFrom('team_merge_map', { data: [], error: null });
    db.queueFrom('teams', {
      data: [
        { team_id_master: FRESH, team_name: 'Fresh FC', club_name: null, state: 'AZ', age_group: 'u13', gender: 'M' },
        { team_id_master: QUIET, team_name: 'Quiet FC', club_name: null, state: 'AZ', age_group: 'u13', gender: 'M' },
      ],
      error: null,
    });
    db.queueFrom('rankings_view', {
      data: [{ team_id_master: FRESH, rank_in_cohort_final: null, status: 'Not Enough Ranked Games' }],
      error: null,
    });

    const body = await (await GET()).json();
    const statusOf = (id: string) => body.teams.find((t: { team_id_master: string }) => t.team_id_master === id).status;

    expect(statusOf(FRESH)).toBe('Not Enough Ranked Games');
    expect(statusOf(QUIET)).toBeNull();
  });
});
