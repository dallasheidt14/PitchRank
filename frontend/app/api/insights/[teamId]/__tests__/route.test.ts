import { beforeEach, describe, expect, it, vi } from 'vitest';
import { filteringClientMock } from '@/test/supabase-mock';
import { makeGame } from '@/test/fixtures';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';
const OPPONENT_ID = '22222222-2222-2222-2222-222222222222';

const supabaseMock = filteringClientMock();

vi.mock('@/lib/api/requirePremium', () => ({
  requirePremium: vi.fn(async () => ({ error: null, user: { id: 'user-1' }, supabase: supabaseMock.client })),
}));

vi.mock('@/lib/team-merge', () => ({
  resolveMergedTeamIds: vi.fn(async (_client: unknown, id: string) => ({
    canonicalTeamId: id,
    teamIdsToQuery: new Set([id]),
    teamIdList: [id],
  })),
}));

const { GET } = await import('../route');

const GAME_WINDOW = 50;
const PLAYED_COUNT = 55;
const SCHEDULED_COUNT = 20;

const dayAfter = (start: string, offset: number) => {
  const date = new Date(`${start}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
};

/** Every fifth game is away, so dropping either half of the OR filter is visible. */
const sides = (index: number) =>
  index % 5 === 0
    ? { home_team_master_id: OPPONENT_ID, away_team_master_id: TEAM_ID }
    : { home_team_master_id: TEAM_ID, away_team_master_id: OPPONENT_ID };

const callRoute = () =>
  GET(new Request(`http://localhost/api/insights/${TEAM_ID}`), { params: Promise.resolve({ teamId: TEAM_ID }) });

describe('GET /api/insights/[teamId]', () => {
  beforeEach(() => {
    supabaseMock.reset();
    supabaseMock.tableRows.teams = [
      { team_id_master: TEAM_ID, team_name: 'U13 Lightning', state_code: 'AZ', gender: 'Female' },
    ];
    supabaseMock.tableRows.rankings_view = [];
    supabaseMock.tableRows.ranking_history = [];
    supabaseMock.tableRows.games = [
      // More results than the window holds, with varied margins.
      ...Array.from({ length: PLAYED_COUNT }, (_, i) =>
        makeGame({ game_date: dayAfter('2026-01-01', i), home_score: (i % 4) + 1, away_score: i % 3, ...sides(i) })
      ),
      // Newer than every result, so anything that leaks past a guard lands inside
      // the window rather than below it. One row per score guard, then fixtures.
      makeGame({ game_date: '2026-03-01', home_score: 3, away_score: null, ...sides(1) }),
      makeGame({ game_date: '2026-03-02', home_score: null, away_score: 2, ...sides(1) }),
      ...Array.from({ length: SCHEDULED_COUNT }, (_, i) =>
        makeGame({ game_date: dayAfter('2026-03-10', i), home_score: null, away_score: null, ...sides(i) })
      ),
    ];
  });

  it('spends the whole window on results rather than on scheduled fixtures', async () => {
    await callRoute();

    const [gameRows] = supabaseMock.queriesFor('games');
    expect(gameRows).toHaveLength(GAME_WINDOW);
    expect(gameRows.every((row) => row.home_score !== null && row.away_score !== null)).toBe(true);
  });

  it('returns insights computed from those results', async () => {
    const response = await callRoute();
    expect(response.status).toBe(200);

    const body = await response.json();
    const consistency = body.insights.find((insight: { type: string }) => insight.type === 'consistency_score');
    // The <3-games fallback reports a flat 0 here, so a non-zero spread is only
    // reachable if real results reached the generator.
    expect(consistency.details.goalDifferentialStdDev).toBeGreaterThan(0);
  });

  it('returns 404 for a team that does not exist', async () => {
    supabaseMock.tableRows.teams = [];

    const response = await callRoute();

    expect(response.status).toBe(404);
  });

  describe('with a ranked team', () => {
    beforeEach(() => {
      const inCohort = { age: 13, gender: 'F', status: 'Active' };
      supabaseMock.tableRows.rankings_view = [
        { ...inCohort, team_id_master: TEAM_ID, state: 'AZ', power_score_final: 0.7, rank_in_cohort_final: 1 },
        ...Array.from({ length: 5 }, (_, i) => ({
          ...inCohort,
          team_id_master: `arizona-${i}`,
          state: 'AZ',
          power_score_final: 0.1 * i,
        })),
        ...Array.from({ length: 3 }, (_, i) => ({
          ...inCohort,
          team_id_master: `texas-${i}`,
          state: 'TX',
          power_score_final: 0.1 * i,
        })),
        // Each row below fails exactly one cohort condition; the Texas rows above are the ones that fail only on state.
        { ...inCohort, gender: 'M', team_id_master: 'boys-0', state: 'AZ', power_score_final: 0.5 },
        { ...inCohort, age: 14, team_id_master: 'older-0', state: 'AZ', power_score_final: 0.5 },
        { ...inCohort, status: 'Inactive', team_id_master: 'inactive-0', state: 'AZ', power_score_final: 0.5 },
      ];
    });

    it('reads the age cohort and the state cohort for the team once its ranking is known', async () => {
      const response = await callRoute();
      expect(response.status).toBe(200);

      const cohortSizes = supabaseMock.queriesFor('rankings_view').map((rows) => rows.length);
      const AGE_COHORT = 9;
      const STATE_COHORT = 6;
      expect(cohortSizes).toContain(AGE_COHORT);
      expect(cohortSizes).toContain(STATE_COHORT);
    });

    it('turns both cohorts into the stats it reports', async () => {
      const response = await callRoute();

      const text = JSON.stringify(await response.json());
      expect(text).toContain('#1 in AZ U13 Girls');
      expect(text).toContain('#1 of 9 Girls U13 teams (top 11%)');
    });

    it('sends the independent reads of each wave out before any of them has answered', async () => {
      const events: string[] = [];
      let inFlight = 0;
      let peak = 0;
      const answerLater = <T>(table: string, run: () => PromiseLike<T>) => {
        events.push(`start:${table}`);
        inFlight += 1;
        peak = Math.max(peak, inFlight);
        return new Promise((resolve) => setTimeout(resolve, 0)).then(run).finally(() => {
          inFlight -= 1;
          events.push(`end:${table}`);
        });
      };
      const originalFrom = supabaseMock.client.from.bind(supabaseMock.client);
      vi.spyOn(supabaseMock.client, 'from').mockImplementation((table: string) => {
        const target = originalFrom(table) as unknown as Record<string, unknown>;
        const gated: Record<string, unknown> = new Proxy(target, {
          get(source, prop) {
            const value = source[prop as string];
            if (prop === 'then') {
              return (resolve: (v: unknown) => unknown, reject: (e: unknown) => unknown) =>
                answerLater(table, () => new Promise((done) => (source.then as typeof resolve)(done as never))).then(
                  resolve,
                  reject
                );
            }
            if (prop === 'single') {
              return () => ({
                then: (resolve: (v: unknown) => unknown, reject: (e: unknown) => unknown) =>
                  answerLater(table, () => (value as () => Promise<unknown>).call(source)).then(resolve, reject),
              });
            }
            if (typeof value !== 'function') return value;
            return (...args: unknown[]) => {
              const out = (value as (...a: unknown[]) => unknown).apply(source, args);
              return out === source ? gated : out;
            };
          },
        });
        return gated as never;
      });

      const response = await callRoute();
      expect(response.status).toBe(200);

      const firstAnswer = events.findIndex((event) => event.startsWith('end:'));
      expect(events.slice(0, firstAnswer)).toEqual(['start:teams', 'start:rankings_view']);
      // Only the second wave (games, ranking history, both cohort scans) ever has four reads in flight at once.
      expect(peak).toBeGreaterThanOrEqual(4);
    });
  });
});
