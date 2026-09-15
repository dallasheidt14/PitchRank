import type { SupabaseClient } from '@supabase/supabase-js';
import { describe, expect, it, vi } from 'vitest';

vi.mock('server-only', () => ({}));

import { buildSeedingPredictions } from './seedingPredictions';
import { buildMatchPrediction, fetchPredictionGames, fetchPredictionTeam } from './matchPredictionService';
import { predictMatch, warmMatchPredictorCalibration } from './matchPredictor';

const A = '11111111-1111-1111-1111-111111111111';
const B = '22222222-2222-2222-2222-222222222222';
const C = '33333333-3333-3333-3333-333333333333';
const OLD_A = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
type Row = Record<string, unknown>;
type Query = { table: string; rows: Row[]; range?: [number, number]; filters: Row; or?: string };

/** Applies filters and records only executed reads; unsupported operations fail. */
function database(
  tables: Record<string, Row[]>,
  failTable?: string,
  failure: unknown = new Error('database unavailable')
) {
  const queries: Query[] = [];
  const from = (table: string) => {
    let rows = [...(tables[table] ?? [])];
    const query: Query = { table, rows: [], filters: {} };
    const orders: Array<[string, boolean]> = [];
    let maximum: number | undefined;
    const execute = (single = false) => {
      if (failTable === table) return { data: null, error: failure };
      rows.sort((a, b) => {
        for (const [field, ascending] of orders) {
          if (a[field] !== b[field]) return (String(a[field]) < String(b[field]) ? -1 : 1) * (ascending ? 1 : -1);
        }
        return 0;
      });
      if (query.range) rows = rows.slice(query.range[0], query.range[1] + 1);
      if (maximum !== undefined) rows = rows.slice(0, maximum);
      // PostgREST's local cap, independent of a caller remembering range().
      rows = rows.slice(0, 1000);
      query.rows = rows;
      queries.push(query);
      if (single && rows.length > 1) return { data: null, error: new Error('multiple rows') };
      return { data: single ? (rows[0] ?? null) : rows, error: null };
    };
    const builder = {
      select: () => builder,
      eq: (field: string, value: unknown) => {
        query.filters[field] = value;
        // Alias provider join fixtures contain no rows in these tests.
        rows = rows.filter((row) => row[field] === value);
        return builder;
      },
      gte: (field: string, value: string) => {
        rows = rows.filter((row) => String(row[field]) >= value);
        return builder;
      },
      not: (field: string, operator: string, value: unknown) => {
        if (operator !== 'is' || value !== null) throw new Error('unsupported not filter');
        rows = rows.filter((row) => row[field] != null);
        return builder;
      },
      or: (filter: string) => {
        query.or = filter;
        const terms = [...filter.matchAll(/(home_team_master_id|away_team_master_id)\.in\.\(([^)]*)\)/g)];
        if (terms.length !== 2) throw new Error('unsupported OR filter');
        rows = rows.filter((row) => terms.some((term) => term[2].split(',').includes(String(row[term[1]]))));
        return builder;
      },
      order: (field: string, options: { ascending: boolean }) => {
        orders.push([field, options.ascending]);
        return builder;
      },
      range: (start: number, end: number) => {
        query.range = [start, end];
        return builder;
      },
      limit: (value: number) => {
        maximum = value;
        return builder;
      },
      maybeSingle: async () => execute(true),
      then: (resolve: (result: unknown) => unknown) => Promise.resolve(execute()).then(resolve),
    };
    return builder;
  };
  return { client: { from } as unknown as SupabaseClient, queries };
}

function game(id: string, home: string, away: string, fields: Row = {}): Row {
  return {
    id,
    game_date: new Date().toISOString().slice(0, 10),
    home_team_master_id: home,
    away_team_master_id: away,
    home_score: 2,
    away_score: 1,
    is_excluded: false,
    ...fields,
  };
}

function fixtures(): Record<string, Row[]> {
  return {
    teams: [A, B, C].map((id, index) => ({
      team_id_master: id,
      team_name: ['Alpha FC', 'Beta FC', 'Gamma FC'][index],
      age_group: 'u14',
      gender: 'Male',
      state: 'AZ',
    })),
    team_merge_map: [{ deprecated_team_id: OLD_A, canonical_team_id: A }],
    rankings_full: [A, B, C].map((id, index) => ({
      team_id: id,
      age_group: 'u14',
      gender: 'Male',
      rank_in_cohort_final: 5 + index,
      power_score_final: 0.55 - index * 0.02,
      glicko_rating: 1750 - index * 240,
      glicko_rd: 40,
      sos_norm: 0.65,
      off_norm: 0.7 - index * 0.18,
      def_norm: 0.7 - index * 0.18,
      games_played: 20,
      wins: 12,
      losses: 6,
      draws: 2,
      last_calculated: index ? '2026-09-14T01:00:00Z' : '2026-09-07T01:00:00Z',
      status: 'Active',
    })),
    games: [
      game('game-z', A, B),
      game('game-a', A, C, { home_score: 5, away_score: 0 }),
      game('game-merged', OLD_A, B),
      game('game-b', B, C),
      game('game-unrelated', 'unrelated-1', 'unrelated-2'),
    ],
  };
}

describe('Seeding canonical Compare bridge', () => {
  it('matches real Compare and direct predictMatch with exact pair games, then mirrors the result', async () => {
    const db = database(fixtures());
    const result = await buildSeedingPredictions(db.client, { 'u14:Male': { '6': OLD_A, '7': B, '8': C } });
    const output = result.cohorts['u14:Male'];
    const row = output.predictions.find((prediction) => prediction.entrant_a === '6' && prediction.entrant_b === '7')!;
    expect(output.predictions).toHaveLength(6);
    expect(output.teams['6'].team_id_master).toBe(A);
    expect(output.teams['6'].prediction_game_count).toBe(2);
    expect(output.teams['6'].ratings_as_of).toBe('2026-09-07T01:00:00Z');
    expect(result.ratings_as_of).toBe('2026-09-07T01:00:00Z');
    expect(db.queries.filter((query) => query.table === 'teams')).toHaveLength(3);
    expect(db.queries.filter((query) => query.table === 'games')).toHaveLength(1);

    const compare = await buildMatchPrediction(db.client, OLD_A, B);
    const teamA = await fetchPredictionTeam(db.client, A);
    const teamB = await fetchPredictionTeam(db.client, B);
    const games = await fetchPredictionGames(db.client, [A, OLD_A, B]);
    await warmMatchPredictorCalibration();
    const direct = predictMatch(teamA, teamB, games);
    expect(compare.prediction).toEqual(direct);
    expect(row).toMatchObject({
      expected_margin: direct.expectedMargin,
      expected_absolute_goal_difference: direct.expectedAbsoluteGoalDifference,
      expected_score: direct.expectedScore,
      win_probability_a: direct.winProbabilityA,
      win_probability_b: direct.winProbabilityB,
      draw_probability: direct.drawProbability,
      blowout_4plus_probability: direct.blowout4PlusProbability,
      confidence: direct.confidence,
      confidence_score: direct.confidence_score,
    });
    const reverse = output.predictions.find(
      (prediction) => prediction.entrant_a === '7' && prediction.entrant_b === '6'
    )!;
    expect(reverse.expected_margin).toBe(-row.expected_margin);
    expect(reverse.win_probability_a).toBe(row.win_probability_b);
    expect(reverse.expected_score).toEqual({ teamA: row.expected_score.teamB, teamB: row.expected_score.teamA });
    expect(games.map((item) => item.id)).toEqual(['game-a', 'game-b', 'game-merged', 'game-z']);
  });

  it('loads shared entrants only once across selected cohorts and excludes unresolved duplicates', async () => {
    const db = database(fixtures());
    const result = await buildSeedingPredictions(db.client, {
      'u14:Male': { '1': A, '2': OLD_A, '3': B },
      'u15:Male': { '4': A, '5': C },
    });
    expect(db.queries.filter((query) => query.table === 'teams')).toHaveLength(3);
    expect(Object.keys(result.cohorts['u14:Male'].unavailable)).toEqual(['1', '2']);
    expect(result.cohorts['u14:Male'].predictions).toEqual([]);
    expect(result.cohorts['u15:Male'].predictions).toHaveLength(2);
  });

  it('preserves missing rank and empty history as placement review instead of predicting a weak team', async () => {
    const data = fixtures();
    data.rankings_full[1].rank_in_cohort_final = null;
    data.games = [game('only-a', A, 'opponent')];
    const db = database(data);
    const result = await buildSeedingPredictions(db.client, { cohort: { a: A, b: B, c: C } });
    expect(result.cohorts.cohort.unavailable.b).toMatch(/No published cohort rank/);
    expect(result.cohorts.cohort.unavailable.c).toMatch(/No scored games/);
    expect(result.cohorts.cohort.predictions).toEqual([]);
  });

  it('does not count merged-only history that Compare does not consume in its team profile', async () => {
    const data = fixtures();
    data.games = Array.from({ length: 4 }, (_, index) => game(`merged-only-${index}`, OLD_A, B));
    const result = await buildSeedingPredictions(database(data).client, { cohort: { a: A, b: B } });
    expect(result.cohorts.cohort.unavailable.a).toMatch(/No scored games/);
    expect(result.cohorts.cohort.teams.a).toBeUndefined();
    expect(result.cohorts.cohort.teams.b.prediction_game_count).toBe(4);
    expect(result.cohorts.cohort.predictions).toEqual([]);
  });

  it('fails the whole batch on a failed predictive input read', async () => {
    const db = database(fixtures(), 'team_predictive_view');
    await expect(buildSeedingPredictions(db.client, { cohort: { a: A, b: B } })).rejects.toThrow(
      'database unavailable'
    );
  });

  it('matches Compare when the optional predictive view is absent from the database schema', async () => {
    const db = database(fixtures(), 'team_predictive_view', { code: 'PGRST205', message: 'Missing optional view' });
    const result = await buildSeedingPredictions(db.client, { cohort: { a: A, b: B } });
    const compare = await buildMatchPrediction(db.client, A, B);
    expect(result.cohorts.cohort.teams.a.exp_margin).toBeNull();
    expect(result.cohorts.cohort.predictions[0].expected_margin).toBe(compare.prediction.expectedMargin);
    expect(result.cohorts.cohort.predictions[0].win_probability_a).toBe(compare.prediction.winProbabilityA);
  });

  it.each(['rankings_view', 'state_rankings_view'])(
    'matches Compare rankings_full inputs when %s lacks optional Glicko columns',
    async (view) => {
      const db = database(fixtures(), view, { code: '42703', message: `column ${view}.glicko_rating does not exist` });
      const result = await buildSeedingPredictions(db.client, { cohort: { a: A, b: B } });
      const compare = await buildMatchPrediction(db.client, A, B);
      expect(result.cohorts.cohort.teams.a.glicko_rating).toBe(1750);
      expect(result.cohorts.cohort.predictions[0].expected_margin).toBe(compare.prediction.expectedMargin);
    }
  );

  it.each([
    { code: '42501', message: 'column rankings_view.glicko_rating does not exist' },
    { code: '42703', message: 'column rankings_view.power_score_final does not exist' },
  ])('does not hide a ranking view error outside the exact legacy Glicko case: $code $message', async (error) => {
    const db = database(fixtures(), 'rankings_view', error);
    await expect(buildSeedingPredictions(db.client, { cohort: { a: A, b: B } })).rejects.toEqual(error);
  });

  it('pages capped games, preserves every score filter, batches IDs, and deduplicates cross-batch games', async () => {
    const ids = [A, ...Array.from({ length: 100 }, (_, index) => `team-${String(index).padStart(3, '0')}`)];
    const data = fixtures();
    data.games = [
      ...Array.from({ length: 1002 }, (_, index) => game(`valid-${String(index).padStart(4, '0')}`, A, ids[100])),
      game('null-home', A, B, { home_score: null }),
      game('null-away', A, B, { away_score: null }),
      game('excluded', A, B, { is_excluded: true }),
      game('old', A, B, { game_date: '2000-01-01' }),
      game('other', B, C),
    ];
    const db = database(data);
    const games = await fetchPredictionGames(db.client, ids);
    expect(games).toHaveLength(1002);
    expect(games[0].id).toBe('valid-0000');
    expect(games[1001].id).toBe('valid-1001');
    expect(db.queries.map((query) => query.range)).toEqual([
      [0, 999],
      [1000, 1999],
      [0, 999],
      [1000, 1999],
    ]);
    expect(db.queries[0].or?.match(/home_team_master_id\.in\.\(([^)]*)\)/)?.[1].split(',')).toHaveLength(100);
  });
});
