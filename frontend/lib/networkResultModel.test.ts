import { expect, it, vi } from 'vitest';
vi.mock('server-only', () => ({}));
import {
  buildNetworkEvidence as build,
  predictNetworkResult as predict,
  withoutNetworkGame as without,
  resampleNetworkEvidence as resample,
} from './networkResultModel';
import type { Game, TeamWithRanking } from './types';
const team = (id: string): TeamWithRanking => ({
  team_id_master: id,
  team_name: id,
  club_name: null,
  league: null,
  distinction: null,
  state: null,
  age: 14,
  gender: 'F',
  rank_in_cohort_final: null,
  power_score_final: 0.5,
  glicko_rating: 1500,
  glicko_rd: 60,
  sos_norm: 0.5,
  offense_norm: 0.5,
  defense_norm: 0.5,
  wins: 10,
  losses: 5,
  draws: 2,
  games_played: 17,
  last_scraped_at: null,
  win_percentage: 60,
});
const game = (id: string, score: number, date = '2026-10-01'): Game =>
  ({
    id,
    game_date: date,
    home_team_master_id: 'a',
    away_team_master_id: 'b',
    home_score: score,
    away_score: 0,
    is_excluded: false,
  }) as Game;
const teams = { a: team('a'), b: team('b') };

it('fits the connected opponent network, not just an independent adjustment to each rating', () => {
  const field = { ...teams, c: team('c'), d: team('d') };
  const games = [
    game('ab', 1),
    { ...game('bc', 4), home_team_master_id: 'b', away_team_master_id: 'c' },
    { ...game('dc', 1), home_team_master_id: 'd', away_team_master_id: 'c' },
  ];
  const evidence = build(field, games, '2026-10-16');
  expect(evidence.a.strength).toBeGreaterThan(evidence.d.strength);
  expect(evidence.b.strength).toBeGreaterThan(evidence.c.strength);
  expect(evidence.a.componentEntrants).toBe(4);
  expect(without(evidence, 'bc')).toEqual(
    build(
      field,
      games.filter((g) => g.id !== 'bc'),
      '2026-10-16'
    )
  );
  expect(build(Object.fromEntries(Object.entries(field).reverse()), [...games].reverse(), '2026-10-16')).toEqual(
    evidence
  );
});
it('caps repeated opponents, deduplicates games, and records unsupported comparisons', () => {
  const repeated = build(
    teams,
    Array.from({ length: 20 }, (_, i) => game(String(i), 4)),
    '2026-10-16'
  );
  expect(repeated.a.effectiveOpponentWeight).toBeCloseTo(1);
  expect(repeated.a.distinctOpponents).toBe(1);
  expect(repeated.a.limited).toBe(true);
  expect(build(teams, [game('one', 4), game('one', 4)], '2026-10-16')).toEqual(
    build(teams, [game('one', 4)], '2026-10-16')
  );
  expect(() => build(teams, [game('one', 4), game('one', 1)], '2026-10-16')).toThrow('Conflicting duplicate');
  const missing = build(teams, [{ ...game('unknown', 2), away_team_master_id: 'missing' }], '2026-10-16');
  expect(missing.a.unknownOpponentGames).toBe(1);
  expect(missing.a.componentEntrants).toBe(1);
  expect(missing.a.correction).toBe(0);
});
it('uses recency, filters future/excluded games, and caps goal-margin leverage', () => {
  const now = build(teams, [game('one', 4)], '2026-10-16');
  expect(build(teams, [game('one', 14)], '2026-10-16').a.strength).toBe(now.a.strength);
  expect(build(teams, [game('one', 4, '2026-01-01')], '2026-10-16').a.strength).toBeLessThan(now.a.strength);
  expect(
    build(teams, [game('one', 4, '2026-10-20'), { ...game('two', 3), is_excluded: true }], '2026-10-16').a.games
  ).toBe(0);
  expect(() => build(teams, [game('one', 1.5)], '2026-10-16')).toThrow('Invalid scored game');
});
it('uses the same continuous distribution in both directions and resamples shared fixtures', () => {
  const evidence = build(teams, [game('one', 4)], '2026-10-16');
  const ab = predict(teams.a, teams.b, evidence),
    ba = predict(teams.b, teams.a, evidence);
  expect(ab.expectedMargin).toBeCloseTo(-ba.expectedMargin, 12);
  expect(ab.blowout4PlusProbability).toBeCloseTo(ba.blowout4PlusProbability!, 12);
  expect(ab.expectedAbsoluteGoalDifference).toBeCloseTo(ba.expectedAbsoluteGoalDifference!, 12);
  expect(ab.winProbabilityA).toBeCloseTo(ba.winProbabilityB, 12);
  expect(ab.confidence).toBe('low');
  for (let i = 0; i < 12; i++) {
    const sample = resample(evidence, i);
    expect(sample.a.games).toBe(sample.b.games);
    expect(sample.a.effectiveOpponentWeight).toBe(sample.b.effectiveOpponentWeight);
    expect(sample.a.effectiveOpponentWeight).toBeLessThanOrEqual(1);
  }
  expect(() => predict(teams.a, teams.b, {})).toThrow('Missing game-evidence strength');
});

it('retains distinct disconnected priors and solves a two-team weighted fit', () => {
  const field = {
    a: { ...team('a'), power_score_final: 0.8, glicko_rating: 1900 },
    b: { ...team('b'), power_score_final: 0.3, glicko_rating: 1200 },
  };
  const pa = build({ a: field.a }, [], '2026-10-01').a.strength;
  const pb = build({ b: field.b }, [], '2026-10-01').b.strength;
  const separate = build(field, [], '2026-10-01');
  expect(pa).toBeGreaterThan(pb);
  expect(separate.a.strength).toBe(pa);
  expect(separate.b.strength).toBe(pb);
  const joined = build(field, [game('one', 2)], '2026-10-01');
  const difference = (0.5 * (pa - pb) + 2 * 2) / (0.5 + 2);
  expect(joined.a.strength).toBeCloseTo((pa + pb + difference) / 2, 10);
  expect(joined.b.strength).toBeCloseTo((pa + pb - difference) / 2, 10);
});
it('counts only accepted entrants in connected evidence components', () => {
  const field = { ...teams, x: team('x') };
  const ax = { ...game('ax', 2), away_team_master_id: 'x' };
  const alone = build(field, [ax], '2026-10-16', ['a', 'b']);
  expect(alone.a.componentEntrants).toBe(1);
  expect(alone.x.componentEntrants).toBe(1);
  const together = build(field, [ax, { ...game('xb', 1), home_team_master_id: 'x' }], '2026-10-16', ['a', 'b']);
  expect(together.a.componentEntrants).toBe(2);
  expect(together.b.componentEntrants).toBe(2);
});
