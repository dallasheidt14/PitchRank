// Merge suggestions compare two teams' real schedules, so excluded games must not count.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { makeGame } from '@/test/fixtures';
import { filteringClientMock } from '@/test/supabase-mock';

const db = filteringClientMock();
const { mockRequireAdmin } = vi.hoisted(() => ({ mockRequireAdmin: vi.fn() }));

vi.mock('@/lib/supabase/admin', () => ({ requireAdmin: mockRequireAdmin }));
vi.mock('@supabase/supabase-js', () => ({ createClient: () => db.client }));

const { GET } = await import('../route');

const TEAM_A = '11111111-1111-4111-8111-111111111111';
const TEAM_B = '22222222-2222-4222-8222-222222222222';
const OPP_1 = '33333333-3333-4333-8333-333333333333';
const OPP_2 = '44444444-4444-4444-8444-444444444444';
const PHANTOM_1 = '55555555-5555-4555-8555-555555555555';
const PHANTOM_2 = '66666666-6666-4666-8666-666666666666';

beforeEach(() => {
  vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL', 'https://example.supabase.co');
  vi.stubEnv('NEXT_PUBLIC_SUPABASE_ANON_KEY', 'anon-key');
  mockRequireAdmin.mockResolvedValue({ user: { id: 'admin' }, supabase: {}, error: null });
  db.reset();
  const team = (team_id_master: string) => ({
    team_id_master,
    team_name: 'Rush AZ 2014 Blue',
    club_name: 'Rush AZ',
    state_code: 'AZ',
    age_group: 'u13',
    gender: 'Male',
    is_deprecated: false,
  });
  db.tableRows.teams = [team(TEAM_A), team(TEAM_B)];
  db.tableRows.games = [
    // Both records played the same two opponents on the same days: the same team, scraped twice.
    makeGame({ home_team_master_id: TEAM_A, away_team_master_id: OPP_1, game_date: '2026-09-06' }),
    makeGame({ home_team_master_id: TEAM_B, away_team_master_id: OPP_1, game_date: '2026-09-06' }),
    makeGame({ home_team_master_id: OPP_2, away_team_master_id: TEAM_A, game_date: '2026-09-13' }),
    makeGame({ home_team_master_id: OPP_2, away_team_master_id: TEAM_B, game_date: '2026-09-13' }),
    // Excluded rows, one home and one away, against opponents only Team A's record shows.
    makeGame({
      home_team_master_id: TEAM_A,
      away_team_master_id: PHANTOM_1,
      game_date: '2026-08-30',
      is_excluded: true,
    }),
    makeGame({
      home_team_master_id: PHANTOM_2,
      away_team_master_id: TEAM_A,
      game_date: '2026-08-23',
      is_excluded: true,
    }),
  ];
});

describe('GET /api/team-merge/suggestions', () => {
  it('compares the two records on their real games only', async () => {
    const body = await (await GET(new NextRequest('http://localhost/api/team-merge/suggestions'))).json();

    expect(body.suggestions).toHaveLength(1);
    expect(body.suggestions[0].details).toMatchObject({
      opponentOverlap: '2 shared opponents out of 2 total',
      scheduleAlignment: '2 games on similar dates',
    });
  });
});
