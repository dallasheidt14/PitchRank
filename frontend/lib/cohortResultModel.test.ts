import { describe, expect, it, vi } from 'vitest';
vi.mock('server-only', () => ({}));
import { buildResultEvidence, predictCohortResult, resampleResultEvidence } from './cohortResultModel';
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

it('perturbs shared team/event clusters coherently across asymmetric histories', () => {
  const field = Object.fromEntries(['a', 'b', 'c', 'd', 'e', 'f'].map((id) => [id, team(id)]));
  const games = [
    { ...game('ab-one', 4), event_name: 'Cup' },
    { ...game('ab-two', 1, '2026-09-01'), event_name: 'Cup' },
    { ...game('bc', 0), home_team_master_id: 'b', away_team_master_id: 'c', away_score: 2, event_name: 'Cup' },
    { ...game('ad', 0), away_team_master_id: 'd', away_score: 3, event_name: 'League' },
    { ...game('ce', 3), home_team_master_id: 'c', away_team_master_id: 'e', event_name: 'League' },
    { ...game('df', 2), home_team_master_id: 'd', away_team_master_id: 'f', event_name: 'Friendly' },
  ];
  const evidence = buildResultEvidence(field, games, '2026-10-16');
  const original = structuredClone(evidence);
  const samples = Array.from({ length: 12 }, (_, sample) => resampleResultEvidence(evidence, sample));
  expect(
    new Set(samples.map((sample) => JSON.stringify(Object.values(sample).map((p) => p.correction)))).size
  ).toBeGreaterThan(1);
  expect(samples.some((sample) => sample.a.correction !== evidence.a.correction)).toBe(true);
  expect(
    samples.some((sample) => Object.values(sample).every((p) => p.influentialGames.every((row) => row.event !== 'Cup')))
  ).toBe(true);
  let observedRepeat = false;
  for (const sample of samples) {
    for (const fixture of games) {
      const home = sample[fixture.home_team_master_id!].influentialGames.find((row) => row.game_id === fixture.id);
      const away = sample[fixture.away_team_master_id!].influentialGames.find((row) => row.game_id === fixture.id);
      expect(Boolean(home)).toBe(Boolean(away));
      if (home && away) expect(home.raw_weight).toBe(away.raw_weight);
    }
    const repeats = sample.a.influentialGames.filter((row) => row.game_id.startsWith('ab-'));
    expect([0, 2]).toContain(repeats.length);
    if (repeats.length) {
      observedRepeat = true;
      const factors = repeats.map(
        (row) => row.raw_weight / evidence.a.influentialGames.find((base) => base.game_id === row.game_id)!.raw_weight
      );
      expect(factors[0]).toBeCloseTo(factors[1]);
    }
  }
  expect(observedRepeat).toBe(true);
  expect(evidence).toEqual(original);
});

describe('experimental opponent-adjusted results', () => {
  it('caps blowout influence, decays by calendar date, and caps repeat support', () => {
    const score4 = buildResultEvidence(teams, [game('1', 4)], '2026-10-16');
    const score14 = buildResultEvidence(teams, [game('1', 14)], '2026-10-16');
    expect(score4.a.correction).toBe(score14.a.correction);
    const old = buildResultEvidence(teams, [game('1', 4, '2025-11-01')], '2026-10-16');
    expect(old.a.correction).toBeLessThan(score4.a.correction);
    const repeated = buildResultEvidence(
      teams,
      Array.from({ length: 20 }, (_, i) => game(String(i), 4)),
      '2026-10-16'
    );
    expect(repeated.a.effectiveOpponentWeight).toBeCloseTo(1);
    expect(repeated.a.limited).toBe(true);
  });
  it('keeps unknown opponents explicit and produces symmetric coherent risk', () => {
    const missing = { ...game('unknown', 2), away_team_master_id: 'missing' };
    const evidence = buildResultEvidence(teams, [game('known', 1), missing], '2026-10-16');
    expect(evidence.a.unknownOpponentGames).toBe(1);
    const ab = predictCohortResult(teams.a, teams.b, evidence);
    const ba = predictCohortResult(teams.b, teams.a, evidence);
    expect(ab.expectedMargin).toBeCloseTo(-ba.expectedMargin);
    expect(ab.winProbabilityA).toBeCloseTo(ba.winProbabilityB);
    expect(ab.winProbabilityA + ab.winProbabilityB + ab.drawProbability!).toBeCloseTo(1);
    expect(ab.expectedAbsoluteGoalDifference).toBeGreaterThanOrEqual(Math.abs(ab.expectedMargin));
    expect(ab.confidence).toBe('low');
  });
});

it('removes both participants observations and reproduces a clean rebuild', async () => {
  const { withoutResultGame, resampleResultEvidence } = await import('./cohortResultModel');
  const games = [game('one', 4), game('two', 1, '2026-09-01')];
  const evidence = buildResultEvidence(teams, games, '2026-10-16');
  const without = withoutResultGame(evidence, 'one');
  expect(without).toEqual(buildResultEvidence(teams, [games[1]], '2026-10-16'));
  expect(without.a.correction).not.toBe(evidence.a.correction);
  expect(without.b.correction).not.toBe(evidence.b.correction);
  expect(evidence.a.games).toBe(2);
  const sampled = resampleResultEvidence(evidence, 3);
  expect(sampled).toEqual(resampleResultEvidence(evidence, 3));
  expect(sampled.a.correction).toBeCloseTo(-sampled.b.correction);
  expect(sampled.a.effectiveOpponentWeight).toBeLessThanOrEqual(1);
});
