import { describe, it, expect } from 'vitest';
import { generateFormBadge } from '../formBadge';
import type { InsightInputData } from '../types';

const TEAM_ID = 'team-a';

function inputWith(opts: {
  recentResults: ('W' | 'L' | 'D')[]; // newest first
  rankNow: number;
  rankThen: number;
  daysAgo: number;
}): InsightInputData {
  const games = opts.recentResults.map((r, i) => ({
    game_date: `2026-05-${(10 - i).toString().padStart(2, '0')}`,
    home_team_master_id: TEAM_ID,
    away_team_master_id: 'opp',
    home_score: r === 'W' ? 2 : r === 'L' ? 0 : 1,
    away_score: r === 'W' ? 0 : r === 'L' ? 2 : 1,
    opponent_rank: 50,
    opponent_power_score: null,
  }));

  const newestSnapshot = new Date('2026-05-10');
  const oldestSnapshot = new Date(newestSnapshot.getTime() - opts.daysAgo * 24 * 60 * 60 * 1000);

  return {
    team: { team_id_master: TEAM_ID, team_name: 'T', state: 'WI', age: 14, gender: 'F' },
    ranking: {
      rank_in_cohort_final: opts.rankNow,
      power_score_final: 0.5,
      sos_norm: null,
      wins: 0,
      losses: 0,
      draws: 0,
      games_played: 0,
      rank_change_7d: null,
      rank_change_30d: null,
      offense_norm: null,
      defense_norm: null,
      perf_centered: null,
    },
    games,
    rankingHistory: [
      {
        snapshot_date: newestSnapshot.toISOString().slice(0, 10),
        rank_in_cohort_final: opts.rankNow,
        rank_in_cohort: opts.rankNow,
        power_score_final: 0.5,
      },
      {
        snapshot_date: oldestSnapshot.toISOString().slice(0, 10),
        rank_in_cohort_final: opts.rankThen,
        rank_in_cohort: opts.rankThen,
        power_score_final: 0.5,
      },
    ],
    cohortStats: { totalTeams: 100, medianPowerScore: 50, percentile: 50 },
    stateCohort: null,
  };
}

describe('generateFormBadge', () => {
  it('returns Surging when rank improved >=10 spots over >=21 days AND last 5 are >=4W with 0 losses', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'W', 'W', 'D'],
      rankNow: 20,
      rankThen: 45,
      daysAgo: 30,
    });
    const result = generateFormBadge(data);
    expect(result?.label).toBe('Surging');
    expect(result?.rankDelta).toBe(-25);
    expect(result?.recentRecord).toBe('4-0-1');
  });

  it('returns Slumping when rank dropped >=10 spots AND last 5 include >=3 losses', () => {
    const data = inputWith({
      recentResults: ['L', 'L', 'L', 'W', 'D'],
      rankNow: 60,
      rankThen: 40,
      daysAgo: 30,
    });
    const result = generateFormBadge(data);
    expect(result?.label).toBe('Slumping');
    expect(result?.rankDelta).toBe(20);
    expect(result?.recentRecord).toBe('1-3-1');
  });

  it('returns null when rank improved but only 1 loss in last 5 — neither trigger fires', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'L', 'W', 'W'], // 4W 1L → fails Surging (loss present); rank dropped? no, improved
      rankNow: 20,
      rankThen: 45,
      daysAgo: 30,
    });
    expect(generateFormBadge(data)).toBeNull();
  });

  it('returns null when rank dropped but last 5 only have 2 losses', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'W', 'L', 'L'],
      rankNow: 60,
      rankThen: 40,
      daysAgo: 30,
    });
    expect(generateFormBadge(data)).toBeNull();
  });

  it('returns null when daySpan is below 21', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'W', 'W', 'W'],
      rankNow: 10,
      rankThen: 40,
      daysAgo: 14,
    });
    expect(generateFormBadge(data)).toBeNull();
  });

  it('returns null when ranking history has fewer than 2 snapshots', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'W', 'W', 'W'],
      rankNow: 10,
      rankThen: 40,
      daysAgo: 30,
    });
    data.rankingHistory = [data.rankingHistory[0]];
    expect(generateFormBadge(data)).toBeNull();
  });
});
