import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeGame } from '@/test/fixtures';
import { filteringClientMock } from '@/test/supabase-mock';

const db = filteringClientMock();
const { mockRequireAdmin } = vi.hoisted(() => ({ mockRequireAdmin: vi.fn() }));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@/lib/supabase/service', () => ({ createServiceSupabase: () => db.client }));

const { GET } = await import('../route');

beforeEach(() => {
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin' }, supabase: {}, error: null });
  db.reset();
  db.tableRows.prospective_match_predictions = [];
  db.tableRows.prediction_feature_history = [];
  db.tableRows.model_training_runs = [];
  db.tableRows.games = [
    makeGame({ game_date: '2026-09-06' }),
    makeGame({ game_date: '2026-09-13' }),
    // One row per part of the filter, each failing exactly one part.
    makeGame({ game_date: '2026-09-20', is_excluded: true }),
    makeGame({ game_date: '2026-09-27', home_score: null }),
    makeGame({ game_date: '2026-10-04', away_score: null }),
  ];
});

describe('GET /api/mission-control/model-snapshot', () => {
  it('counts only scored games that are not excluded', async () => {
    const body = await (await GET()).json();

    expect(body.pitCoverage.totalScoredGames).toBe(2);
  });
});
