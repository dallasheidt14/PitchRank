import { describe, it, expect } from 'vitest';
import { generateConsistencyScore } from '../consistency';
import type { InsightInputData } from '../types';

const TEAM_ID = 'team-a';

function buildInput(opts: {
  recentResultsNewestFirst?: Array<{ teamScore: number; oppScore: number }>;
  rankingHistoryScoresNewestFirst?: Array<number | null>;
}): InsightInputData {
  const games = (opts.recentResultsNewestFirst ?? []).map((r, i) => ({
    game_date: `2026-05-${(20 - i).toString().padStart(2, '0')}`,
    home_team_master_id: TEAM_ID,
    away_team_master_id: 'opp',
    home_score: r.teamScore,
    away_score: r.oppScore,
    opponent_rank: null,
    opponent_power_score: null,
  }));

  const rankingHistory = (opts.rankingHistoryScoresNewestFirst ?? []).map((s, i) => ({
    snapshot_date: `2026-05-${(20 - i).toString().padStart(2, '0')}`,
    rank_in_cohort: 50,
    rank_in_cohort_ml: 50,
    rank_in_cohort_final: 50,
    power_score_final: s,
  }));

  return {
    team: { team_id_master: TEAM_ID, team_name: 'T', state: 'WI', age: 14, gender: 'F' },
    ranking: {
      rank_in_cohort_final: 50,
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
    rankingHistory,
    cohortStats: { totalTeams: 100, medianPowerScore: 50, percentile: 50 },
    stateCohort: null,
  };
}

describe('generateConsistencyScore', () => {
  it('windows to most recent 15 played games — old chaos does not drag down a clean recent stretch', () => {
    // 20 chaotic older games + 10 clean recent wins → only the 15 newest count.
    const recent: Array<{ teamScore: number; oppScore: number }> = [];
    for (let i = 0; i < 10; i++) recent.push({ teamScore: 2, oppScore: 1 }); // 10 clean 2-1 wins (newest)
    for (let i = 0; i < 20; i++)
      recent.push(i % 2 === 0 ? { teamScore: 5, oppScore: 0 } : { teamScore: 0, oppScore: 5 }); // 20 chaotic
    const data = buildInput({ recentResultsNewestFirst: recent });

    const result = generateConsistencyScore(data);

    // Only the 10 wins + the first 5 chaotic games (5-0 win, 0-5 loss, etc) count.
    // That still produces a relatively clean score — proves windowing happens.
    // Without windowing, full-season chaos would push the score below 35.
    expect(result.score).toBeGreaterThan(50);
  });

  it('detects chaos in recent games even when older history was clean', () => {
    // 10 clean wins (oldest) followed by 5 chaotic games (newest)
    const recent: Array<{ teamScore: number; oppScore: number }> = [];
    recent.push({ teamScore: 5, oppScore: 0 });
    recent.push({ teamScore: 0, oppScore: 5 });
    recent.push({ teamScore: 6, oppScore: 1 });
    recent.push({ teamScore: 1, oppScore: 6 });
    recent.push({ teamScore: 4, oppScore: 0 });
    for (let i = 0; i < 10; i++) recent.push({ teamScore: 2, oppScore: 1 }); // older clean wins
    const data = buildInput({ recentResultsNewestFirst: recent });

    const result = generateConsistencyScore(data);

    // Windowing means the 5 chaotic newest dominate; expect a lower score.
    expect(result.score).toBeLessThan(60);
  });

  it('rewards a monotonic ranking climb (low residual stddev) with high pvScore', () => {
    // 5 played games (needed for score >= 50 path)
    const games = [
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
    ];
    // Monotonic climb in power score: 0.40 → 0.42 → 0.44 → 0.46 → 0.48 (newest)
    // Reversed input (newest first): [0.48, 0.46, 0.44, 0.42, 0.40]
    const history = [0.48, 0.46, 0.44, 0.42, 0.4];
    const data = buildInput({ recentResultsNewestFirst: games, rankingHistoryScoresNewestFirst: history });

    const result = generateConsistencyScore(data);

    // Residual stddev around a perfect line ≈ 0 → pvScore close to 100.
    // Combined with very clean game results, total score should be high.
    expect(result.score).toBeGreaterThan(75);
  });

  it('penalizes thrashing ranking history (high residual stddev) with low pvScore', () => {
    const games = [
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
    ];
    // Sawtooth: 0.40, 0.60, 0.40, 0.60, 0.40 — slope is zero, residuals are huge.
    const history = [0.4, 0.6, 0.4, 0.6, 0.4];
    const data = buildInput({ recentResultsNewestFirst: games, rankingHistoryScoresNewestFirst: history });

    const result = generateConsistencyScore(data);

    // Clean games (high gdScore + sfScore) but pvScore should be dragged way down.
    // Expect score lower than the monotonic-climb case above.
    expect(result.details.powerScoreVolatility).toBeGreaterThan(0.15);
  });

  it('returns neutral fallback when fewer than 3 scored games exist', () => {
    const data = buildInput({
      recentResultsNewestFirst: [
        { teamScore: 2, oppScore: 1 },
        { teamScore: 1, oppScore: 0 },
      ],
    });

    const result = generateConsistencyScore(data);

    expect(result.score).toBe(50);
    expect(result.label).toBe('unpredictable');
  });
});
