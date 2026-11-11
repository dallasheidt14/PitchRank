import { describe, expect, it } from 'vitest';
import baseline from '@/test/fixtures/compare-baseline.json';
import { summarizeMatchEvidence } from './matchEvidence';
import type { Game, TeamWithRanking } from './types';

const sample = baseline.cases[0];
const a = sample.teamA as TeamWithRanking;
const b = sample.teamB as TeamWithRanking;
describe('match evidence', () => {
  it('counts the usable input window and keeps latest opponent results', () => {
    const games = sample.games as Game[];
    const extra = {
      ...games[0],
      id: 'new',
      home_team_master_id: 'a',
      away_team_master_id: 'opp0',
      home_score: 4,
      away_score: 0,
      game_date: '2026-11-01',
    };
    const evidence = summarizeMatchEvidence(
      { as_of: '2026-11-11', window_start: '2025-11-11', games: [...games, extra] },
      { ...a, games_played: 999, ratings_as_of: '2026-11-09T12:00:00Z' },
      b
    );
    expect(evidence.teamA.usableResults).toBe(7);
    expect(evidence.teamB.usableResults).toBe(6);
    expect(evidence.teamA.uniqueOpponents).toBe(6);
    expect(evidence.teamA.latestResultDate).toBe('2026-11-01');
    expect(evidence.sharedOpponents).toBe(6);
    expect(evidence.commonOpponents.find((row) => row.opponent_id === 'opp0')).toMatchObject({
      team1_result: 'W',
      team1_score: 4,
      opponent_score_team1: 0,
      team1_date: '2026-11-01',
    });
  });
  it('caps only the form sample and preserves unavailable dates', () => {
    const games = Array.from({ length: 12 }, (_, i) => ({
      ...sample.games[0],
      id: String(i),
      home_team_master_id: 'a',
      away_team_master_id: 'b',
    })) as Game[];
    const evidence = summarizeMatchEvidence({ as_of: '2026-11-11', window_start: '2025-11-11', games }, a, b);
    expect(evidence.teamA.usableResults).toBe(12);
    expect(evidence.teamA.formSampleSize).toBe(8);
    expect(evidence.headToHeadMeetings).toBe(12);
    expect(evidence.teamA.ratingSnapshotDate).toBeNull();
    const empty = summarizeMatchEvidence({ as_of: '2026-11-11', window_start: '2025-11-11', games: [] }, a, b);
    expect(empty.teamA.latestResultDate).toBeNull();
    expect(empty.teamA.usableResults).toBe(0);
  });
});
