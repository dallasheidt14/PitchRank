import { describe, expect, it } from 'vitest';
import { makeRankingRow as makeTeam } from '@/test/fixtures';
import { generateMoverData } from './rankingMoversRenderer';

describe('generateMoverData', () => {
  it('reads the stored rank change rather than inventing one', () => {
    const rankings = [
      makeTeam({ team_id_master: 'a', rank_change_7d: 4, rank_in_cohort_final: 12 }),
      makeTeam({ team_id_master: 'b', rank_change_7d: -9, rank_in_cohort_final: 40 }),
    ];

    const { climbers, fallers } = generateMoverData(rankings);

    expect(climbers.map((t) => [t.team_id_master, t.change])).toEqual([['a', 4]]);
    expect(fallers.map((t) => [t.team_id_master, t.change])).toEqual([['b', -9]]);
  });

  it('is deterministic across calls on the same input', () => {
    const rankings = Array.from({ length: 20 }, (_, i) =>
      makeTeam({ team_id_master: `t${i}`, rank_change_7d: i - 10, rank_in_cohort_final: i + 1 })
    );

    const first = generateMoverData(rankings);
    const second = generateMoverData(rankings);

    expect(first).toEqual(second);
  });

  it('reports the team its real cohort rank, not its position in the array', () => {
    const rankings = [
      makeTeam({ team_id_master: 'a', rank_change_7d: 3, rank_in_cohort_final: 87 }),
      makeTeam({ team_id_master: 'b', rank_change_7d: 2, rank_in_cohort_final: 91 }),
    ];

    const { climbers } = generateMoverData(rankings);

    expect(climbers.map((t) => t.rank)).toEqual([87, 91]);
  });

  it('takes the five biggest movers in each direction, largest first', () => {
    const rankings = [
      ...Array.from({ length: 7 }, (_, i) => makeTeam({ team_id_master: `up${i}`, rank_change_7d: i + 1 })),
      ...Array.from({ length: 7 }, (_, i) => makeTeam({ team_id_master: `down${i}`, rank_change_7d: -(i + 1) })),
    ];

    const { climbers, fallers } = generateMoverData(rankings);

    expect(climbers.map((t) => t.change)).toEqual([7, 6, 5, 4, 3]);
    expect(fallers.map((t) => t.change)).toEqual([-7, -6, -5, -4, -3]);
  });

  it('omits a team whose rank change is unknown or zero', () => {
    const rankings = [
      makeTeam({ team_id_master: 'undefined', rank_change_7d: undefined }),
      makeTeam({ team_id_master: 'null', rank_change_7d: null }),
      makeTeam({ team_id_master: 'flat', rank_change_7d: 0 }),
      makeTeam({ team_id_master: 'moved', rank_change_7d: 5 }),
    ];

    const { climbers, fallers } = generateMoverData(rankings);

    expect([...climbers, ...fallers].map((t) => t.team_id_master)).toEqual(['moved']);
  });

  it('returns empty sides when nothing moved', () => {
    const { climbers, fallers } = generateMoverData([makeTeam({ rank_change_7d: null })]);

    expect(climbers).toEqual([]);
    expect(fallers).toEqual([]);
  });
});
