import type { SupabaseClient } from '@supabase/supabase-js';
import { describe, expect, it, vi } from 'vitest';

vi.mock('server-only', () => ({}));

import { buildSeedingPredictions } from './seedingPredictions';
import {
  buildMatchPrediction,
  buildMatchPredictionWithShadowContext,
  fetchPredictionGames,
  fetchPredictionTeam,
  resolvePredictionTeamIds,
  fetchPredictionEvidence,
} from './matchPredictionService';
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
        rows = rows.filter((row) => row[field] === value);
        return builder;
      },
      in: (field: string, values: readonly unknown[]) => {
        query.filters[field] = values;
        // Alias provider join fixtures contain no rows in these tests.
        rows = rows.filter((row) => values.includes(row[field]));
        return builder;
      },
      gte: (field: string, value: string) => {
        rows = rows.filter((row) => String(row[field]) >= value);
        return builder;
      },
      lte: (field: string, value: string) => {
        rows = rows.filter((row) => String(row[field]) <= value);
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
      game('game-merged', OLD_A, B, { home_score: 3 }),
      game('game-b', B, C),
      game('game-unrelated', 'unrelated-1', 'unrelated-2'),
    ],
  };
}

describe('Seeding canonical Compare bridge', () => {
  it('digests the actual rating and merged game inputs without depending on request order', async () => {
    const data = fixtures();
    const digest = async (entries = { a: A, b: B }) =>
      (await buildSeedingPredictions(database(data).client, { 'u14|Male': entries })).input_digests['u14|Male'];
    const original = await digest();
    expect(original).toMatch(/^[a-f0-9]{64}$/);
    expect(await digest({ b: B, a: A })).toBe(original);
    data.rankings_full[0].off_norm = 0.99;
    const newRating = await digest();
    expect(newRating).not.toBe(original);
    data.games.find((row) => row.id === 'game-merged')!.home_score = 8;
    expect(await digest()).not.toBe(newRating);
    const mergedHistory = await digest();
    data.games.find((row) => row.id === 'game-unrelated')!.home_score = 9;
    expect(await digest()).toBe(mergedHistory);
  });

  it('keeps freshness stable when merged identity rows arrive in another order', async () => {
    const data = fixtures();
    data.team_merge_map.push({ deprecated_team_id: '00000000-0000-4000-8000-000000000099', canonical_team_id: A });
    const before = await buildSeedingPredictions(database(data).client, { cohort: { a: A, b: B } });
    data.team_merge_map.reverse();
    const after = await buildSeedingPredictions(database(data).client, { cohort: { a: A, b: B } });
    expect(after.cohorts).toEqual(before.cohorts);
    expect(after.input_digests).toEqual(before.input_digests);
  });

  it.each(['rankings_full', 'rankings_view', 'state_rankings_view'])(
    'identifies age disagreement in %s and recovers after rankings are updated',
    async (table) => {
      const data = fixtures();
      if (table === 'rankings_full') data[table][0].age_group = 'u15';
      else data[table] = [{ team_id_master: A, age: 15, gender: 'M' }];
      const db = database(data);
      await expect(buildMatchPrediction(db.client, A, B)).rejects.toMatchObject({
        code: 'prediction_metadata_conflict',
        statusCode: 422,
        message: expect.stringContaining('team record U14, calculated ratings U15'),
      });
      const result = await buildSeedingPredictions(db.client, { 'u14|Male': { a: A, b: B } });
      expect(result.cohorts['u14|Male'].unavailable.a).toContain('Recalculate rankings');
      expect(result.cohorts['u14|Male'].unavailable.a).toContain('Your team match is saved');
      expect(result.cohorts['u14|Male'].unavailable_codes).toEqual({ a: 'metadata_conflict' });
      expect(result.cohorts['u14|Male'].teams.a).toBeUndefined();
      expect(result.cohorts['u14|Male'].predictions).toEqual([]);
      if (table === 'rankings_full') data[table][0].age_group = 'u14';
      else data[table][0].age = 14;
      const updated = await buildSeedingPredictions(db.client, { 'u15|Male': { a: A, b: B } });
      expect(updated.cohorts['u15|Male'].unavailable).toEqual({});
      expect(updated.cohorts['u15|Male'].unavailable_codes).toEqual({});
      expect(updated.cohorts['u15|Male'].teams.a).toMatchObject({ age: 14, ratings_age: 14 });
      const compare = await buildMatchPrediction(db.client, A, B);
      expect(updated.cohorts['u15|Male'].predictions[0].expected_margin).toBe(compare.prediction.expectedMargin);
    }
  );

  it.each(['rankings_full', 'rankings_view', 'state_rankings_view'])(
    'distinguishes a database gender disagreement in %s from a tournament assignment',
    async (table) => {
      const data = fixtures();
      if (table === 'rankings_full') data[table][0].gender = 'Female';
      else data[table] = [{ team_id_master: A, age: 14, gender: 'F' }];
      const db = database(data);
      await expect(fetchPredictionTeam(db.client, A)).rejects.toMatchObject({
        code: 'prediction_metadata_conflict',
        message: expect.stringContaining('team record Boys, calculated ratings Girls'),
      });
    }
  );

  it.each([{ gender: 'Unknown' }, { gender: null }, { age_group: 'u0' }, { age_group: null }])(
    'does not silently substitute ranking metadata for an invalid team record: %j',
    async (change) => {
      const data = fixtures();
      Object.assign(data.teams[0], change);
      await expect(fetchPredictionTeam(database(data).client, A)).rejects.toMatchObject({
        code: 'prediction_metadata_conflict',
        message: expect.stringContaining('missing a valid age or gender'),
      });
    }
  );

  it('normalizes gender aliases and the shared U18/U19 board without reporting a conflict', async () => {
    const data = fixtures();
    Object.assign(data.teams[0], { age_group: 'u18', gender: ' boys ' });
    Object.assign(data.rankings_full[0], { age_group: 'u19', gender: 'M' });
    expect(await fetchPredictionTeam(database(data).client, A)).toMatchObject({
      age: 19,
      ratings_age: 19,
      gender: 'M',
      ratings_gender: 'M',
    });
  });

  it('matches real Compare and direct predictMatch with exact pair games, then mirrors the result', async () => {
    const db = database(fixtures());
    const result = await buildSeedingPredictions(db.client, { 'u14:Male': { '6': OLD_A, '7': B, '8': C } });
    const output = result.cohorts['u14:Male'];
    const row = output.predictions.find((prediction) => prediction.entrant_a === '6' && prediction.entrant_b === '7')!;
    expect(output.predictions).toHaveLength(6);
    expect(output.teams['6'].team_id_master).toBe(A);
    expect(output.teams['6'].prediction_game_count).toBe(3);
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
    expect(result.cohorts['u14:Male'].unavailable['1']).toBe(
      'Two roster entries appear to be the same team. Confirm both team matches before seeding.'
    );
    expect(result.cohorts['u14:Male'].unavailable_codes).toEqual({ '1': 'duplicate_entry', '2': 'duplicate_entry' });
    expect(result.cohorts['u14:Male'].predictions).toEqual([]);
    expect(result.cohorts['u15:Male'].predictions).toHaveLength(2);
  });

  it('predicts every pair when teams have PowerScores despite a missing rank or no recent games', async () => {
    const data = fixtures();
    data.rankings_full[1].rank_in_cohort_final = null;
    data.games = [game('only-a', A, 'opponent')];
    const db = database(data);
    const result = await buildSeedingPredictions(db.client, { cohort: { a: A, b: B, c: C } });
    expect(result.cohorts.cohort.unavailable).toEqual({});
    expect(result.cohorts.cohort.teams.b.rank_in_cohort_final).toBeNull();
    expect(result.cohorts.cohort.teams.b.prediction_game_count).toBe(0);
    expect(result.cohorts.cohort.teams.c.prediction_game_count).toBe(0);
    expect(result.cohorts.cohort.predictions).toHaveLength(6);
  });

  it('gives the director a clear identity check when the matched team no longer exists', async () => {
    const data = fixtures();
    data.teams = data.teams.filter((row) => row.team_id_master !== B);
    const result = await buildSeedingPredictions(database(data).client, { cohort: { a: A, b: B } });
    expect(result.cohorts.cohort.unavailable.b).toBe('Confirm the club, team name, and age group before seeding.');
    expect(result.cohorts.cohort.unavailable_codes).toEqual({ b: 'team_not_found' });
  });

  it('includes a PowerScore team with zero ranked games and zero recent prediction games', async () => {
    const data = fixtures();
    data.rankings_full[1].games_played = 0;
    data.games = [];
    const db = database(data);
    const result = await buildSeedingPredictions(db.client, { cohort: { a: A, b: B } });
    expect(result.cohorts.cohort.unavailable).toEqual({});
    expect(result.cohorts.cohort.teams.b.power_score_final).toBe(0.53);
    expect(result.cohorts.cohort.teams.b.prediction_game_count).toBe(0);
    expect(result.cohorts.cohort.predictions).toHaveLength(2);
    await expect(fetchPredictionTeam(db.client, B)).rejects.toMatchObject({ code: 'prediction_unavailable' });
  });

  it('excludes a team when it has no PowerScore', async () => {
    const data = fixtures();
    data.rankings_full[1].power_score_final = null;
    const result = await buildSeedingPredictions(database(data).client, { cohort: { a: A, b: B } });
    expect(result.cohorts.cohort.unavailable.b).toBe('No usable current PitchRank rating is available.');
    expect(result.cohorts.cohort.unavailable_codes).toEqual({ b: 'no_current_rating' });
    expect(result.cohorts.cohort.teams.b).toBeUndefined();
    expect(result.cohorts.cohort.predictions).toEqual([]);
  });

  it('counts merged history consumed by both Compare and Seeding', async () => {
    const data = fixtures();
    data.games = Array.from({ length: 4 }, (_, index) => game(`merged-only-${index}`, OLD_A, B));
    const result = await buildSeedingPredictions(database(data).client, { cohort: { a: A, b: B } });
    expect(result.cohorts.cohort.unavailable).toEqual({});
    expect(result.cohorts.cohort.teams.a.prediction_game_count).toBe(4);
    expect(result.cohorts.cohort.teams.b.prediction_game_count).toBe(4);
    expect(result.cohorts.cohort.predictions).toHaveLength(2);
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

  it('pages capped games, keeps the combined ID filter within the URI budget, and deduplicates games', async () => {
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
    expect(db.queries.filter((query) => query.table === 'games').map((query) => query.range)).toEqual([
      [0, 999],
      [1000, 1999],
      [0, 999],
      [0, 999],
      [1000, 1999],
    ]);
    const distinctFilters = [
      ...new Set(db.queries.filter((query) => query.table === 'games').map((query) => query.or)),
    ];
    expect(distinctFilters).toHaveLength(3);
    expect(
      distinctFilters.map((filter) =>
        [...(filter ?? '').matchAll(/(?:home_team_master_id|away_team_master_id)\.in\.\(([^)]*)\)/g)].reduce(
          (count, match) => count + match[1].split(',').length,
          0
        )
      )
    ).toEqual([100, 100, 2]);
  });
});

describe('canonical input safeguards', () => {
  it('follows multi-hop aliases on both sides and excludes canonicalized excluded teams', async () => {
    const data = fixtures();
    const older = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    const oldB = 'cccccccc-cccc-cccc-cccc-cccccccccccc';
    data.team_merge_map.push(
      { deprecated_team_id: older, canonical_team_id: OLD_A },
      { deprecated_team_id: oldB, canonical_team_id: B }
    );
    data.games = [game('merged', older, oldB), game('future', A, C, { game_date: '2099-01-01' })];
    const db = database(data);
    expect((await resolvePredictionTeamIds(db.client, older)).allTeamIds.sort()).toEqual([A, OLD_A, older].sort());
    const evidence = await fetchPredictionEvidence(db.client, [A, OLD_A, older]);
    expect(evidence.games).toHaveLength(1);
    expect(evidence.games[0]).toMatchObject({
      home_team_master_id: A,
      away_team_master_id: B,
      original_home_team_id: older,
      original_away_team_id: oldB,
    });
    data.team_ranking_exclusions = [{ team_id_master: oldB }];
    expect((await fetchPredictionEvidence(database(data).client, [A, OLD_A, older])).games).toEqual([]);
  });
  it('fails closed on cyclic merges or exclusion lookup failures', async () => {
    const data = fixtures();
    data.team_merge_map.push({ deprecated_team_id: A, canonical_team_id: OLD_A });
    await expect(resolvePredictionTeamIds(database(data).client, A)).rejects.toThrow('Cyclic');
    await expect(fetchPredictionGames(database(fixtures(), 'team_ranking_exclusions').client, [A])).rejects.toThrow();
  });
  it('freezes preview inputs, keeps cohort digests independent, and uses each opponent once', async () => {
    const one = await buildSeedingPredictions(
      database(fixtures()).client,
      { one: { a: A, b: B } },
      { model: 'results' }
    );
    const two = await buildSeedingPredictions(
      database(fixtures()).client,
      { two: { c: C }, one: { b: B, a: A } },
      { model: 'results' }
    );
    expect(one.input_digests.one).toBe(two.input_digests.one);
    expect(one.cohorts.one.predictions).toHaveLength(2);
    const saved = one.evidence.one as { canonical_json: string };
    expect(JSON.parse(saved.canonical_json)).toMatchObject({
      model: 'results',
      model_parameters: { status: 'preview_unvalidated' },
    });
  });
});

it('uses the privileged client only for exclusion reads on authenticated Compare', async () => {
  const user = database(fixtures(), 'team_ranking_exclusions', new Error('permission denied'));
  const service = database({ team_ranking_exclusions: [] });
  await buildMatchPredictionWithShadowContext(user.client, A, B, service.client);
  expect(service.queries.map((q) => q.table)).toEqual(['team_ranking_exclusions']);
  expect(user.queries.some((q) => q.table === 'games')).toBe(true);
});

it('normalizes uppercase deprecated UUIDs before merge traversal', async () => {
  const tables = fixtures();
  tables.team_merge_map = [{ deprecated_team_id: OLD_A, canonical_team_id: A }];
  const result = await resolvePredictionTeamIds(database(tables).client, OLD_A.toUpperCase());
  expect(result.canonicalTeamId).toBe(A);
  expect(result.allTeamIds).toContain(OLD_A);
});

it('preserves same-provider reversed-home-away rematches', async () => {
  const tables = fixtures();
  tables.games = [
    game('first', A, B, { event_name: 'Cup', provider_id: 'one' }),
    game('second', B, A, { home_score: 1, away_score: 2, event_name: 'Cup', provider_id: 'one' }),
  ];
  const result = await fetchPredictionEvidence(database(tables).client, [A, B]);
  expect(result.games.map((g) => g.id)).toEqual(['first', 'second']);
  expect(result.omitted).toEqual([]);
});

it.each([
  ['https://example.test/match/101', 'https://example.test/match/102'],
  ['https://example.test/matches/101', 'https://example.test/matches/102'],
  ['https://example.test/game/101', 'https://example.test/game/102'],
  ['https://example.test/games/101', 'https://example.test/games/102'],
  ['https://example.test/fixture/101', 'https://example.test/fixture/102'],
  ['https://example.test/fixtures/101', 'https://example.test/fixtures/102'],
  ['https://example.test/results?match_id=101', 'https://example.test/results?match_id=102'],
])('retains distinct source fixtures across merged identities: %s', async (first, second) => {
  const tables = fixtures();
  tables.games = [
    game('first', A, B, { event_name: 'Cup', provider_id: 'one', source_url: first }),
    game('second', OLD_A, B, { event_name: 'Cup', provider_id: 'one', source_url: second }),
  ];
  const result = await fetchPredictionEvidence(database(tables).client, [A, OLD_A, B]);
  expect(result.games.map((g) => g.id)).toEqual(['first', 'second']);
  expect(result.review_team_ids).toEqual([]);
});

it('does not mistake different team-history pages for proof of separate fixtures', async () => {
  const tables = fixtures();
  tables.games = [
    game('first', A, B, {
      event_name: 'Cup',
      provider_id: 'one',
      source_url: 'https://example.test/teams/101/game-history',
    }),
    game('second', OLD_A, B, {
      event_name: 'Cup',
      provider_id: 'one',
      source_url: 'https://example.test/teams/102/game-history',
    }),
  ];
  const result = await fetchPredictionEvidence(database(tables).client, [A, OLD_A, B]);
  expect(result.games).toEqual([]);
  expect(result.review_team_ids).toEqual([A, B]);
  expect(result.omitted.map((row) => row.record.id)).toEqual(['first', 'second']);
});

it('quarantines ambiguous copies without discarding a known distinct fixture', async () => {
  const tables = fixtures();
  tables.games = [
    game('a-original', A, B, { event_name: 'Cup', provider_id: 'one', source_url: 'https://example.test/matches/101' }),
    game('b-copy', OLD_A, B, { event_name: 'Cup', provider_id: 'one', source_url: 'https://example.test/matches/101' }),
    game('c-distinct', OLD_A, B, {
      event_name: 'Cup',
      provider_id: 'one',
      source_url: 'https://example.test/matches/102',
    }),
  ];
  const result = await fetchPredictionEvidence(database(tables).client, [A, OLD_A, B]);
  expect(result.games.map((g) => g.id)).toEqual(['c-distinct']);
  expect(result.omitted.map((row) => row.record.id)).toEqual(['a-original', 'b-copy']);
});

it('keeps a one-assessed-team preview usable and generates real cluster trials for a full field', async () => {
  const tables = fixtures();
  tables.games = [game('history', A, C)];
  const one = await buildSeedingPredictions(database(tables).client, { 'u14|Male': { '0': A } }, { model: 'results' });
  expect(one.cohorts['u14|Male'].sensitivity).toEqual([]);
  const two = await buildSeedingPredictions(
    database(tables).client,
    { 'u14|Male': { '0': A, '1': B } },
    { model: 'results' }
  );
  const variants = two.cohorts['u14|Male'].sensitivity!;
  expect(variants.filter((row) => row.kind === 'cluster_resample')).toHaveLength(12);
  expect(variants.every((row) => row.predictions.length === 2)).toBe(true);
});

it('preserves ambiguous cross-provider records for review without recommending their affected teams', async () => {
  const tables = fixtures();
  tables.games = [
    game('one', A, B, { event_name: 'Cup', provider_id: 'first' }),
    game('two', A, B, { event_name: 'Cup', provider_id: 'second' }),
  ];
  const evidence = await fetchPredictionEvidence(database(tables).client, [A, B]);
  expect(evidence.games).toHaveLength(0);
  expect(evidence.omitted.map((row) => row.record.id)).toEqual(['one', 'two']);
  expect(evidence.review_team_ids).toEqual([A, B]);
  const batch = await buildSeedingPredictions(database(tables).client, { 'u14|Male': { '0': A, '1': B } });
  expect(batch.cohorts['u14|Male'].unavailable_codes).toEqual({ '0': 'metadata_conflict', '1': 'metadata_conflict' });
  expect(batch.cohorts['u14|Male'].predictions).toEqual([]);
});

it('does not count external history opponents as accepted entrants', async () => {
  const tables = fixtures();
  tables.games = [game('external', A, C)];
  const batch = await buildSeedingPredictions(
    database(tables).client,
    { 'u14|Male': { '0': A, '1': B } },
    { model: 'results' }
  );
  const saved = JSON.parse((batch.evidence['u14|Male'] as { canonical_json: string }).canonical_json);
  expect(saved.teams['0'].result_evidence.componentEntrants).toBe(1);
  expect(saved.teams['1'].result_evidence.componentEntrants).toBe(1);
});
