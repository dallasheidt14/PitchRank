import { describe, expect, it } from 'vitest';
import { generateSeasonTruth } from '../seasonTruth';
import type { InsightInputData } from '../types';

const TEAM_ID = 'team-a';

/** Home games, newest first, as [team goals, opponent goals]. */
function inputWith(scoresNewestFirst: Array<[number, number]>): InsightInputData {
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
    games: scoresNewestFirst.map(([team, opp], i) => ({
      game_date: new Date(Date.UTC(2026, 8, 30 - i)).toISOString().slice(0, 10),
      home_team_master_id: TEAM_ID,
      away_team_master_id: 'opp',
      home_score: team,
      away_score: opp,
      opponent_rank: null,
      opponent_power_score: null,
    })),
    rankingHistory: [],
    cohortStats: { totalTeams: 100, medianPowerScore: 50, percentile: 50 },
    stateCohort: null,
  };
}

const noteFor = (scores: Array<[number, number]>) => generateSeasonTruth(inputWith(scores)).details.consistencyNote;

describe('generateSeasonTruth consistency note', () => {
  it('reads only the 15 newest played games', () => {
    const steady = Array.from({ length: 15 }, (): [number, number] => [2, 1]);
    const chaotic = Array.from({ length: 15 }, (_, i): [number, number] => (i % 2 === 0 ? [6, 0] : [0, 6]));

    expect(noteFor([...steady, ...chaotic])).toBe('consistent performer with minimal variance');
  });

  it("reads each game from the team's side", () => {
    expect(noteFor(Array.from({ length: 6 }, (): [number, number] => [3, 0]))).toBe(
      'consistent performer with minimal variance'
    );
  });

  it('caps a blowout at six goals', () => {
    // Capped diffs [6, 0, 0] -> stddev 2.83; uncapped [7, 0, 0] -> 3.30, past the inconsistency line at 3.
    expect(
      noteFor([
        [7, 0],
        [0, 0],
        [0, 0],
      ])
    ).toBe('balanced performance with typical variance');
  });
});

describe('generateSeasonTruth current streak', () => {
  const streakOf = (data: InsightInputData) => generateSeasonTruth(data).details.currentStreak;

  it('counts the newest run of played results, past an unscored fixture', () => {
    const data = inputWith([
      [2, 0],
      [3, 1],
      [1, 0],
      [0, 2],
    ]);
    data.games.unshift({ ...data.games[0], home_score: null, away_score: null });

    expect(streakOf(data)).toBe('W3');
  });

  // An away win then a home win: read from one fixed side, one of them would be a loss and break the run.
  it("reads an away win from the team's side", () => {
    const data = inputWith([
      [2, 0],
      [3, 1],
    ]);
    const [newest] = data.games;
    data.games[0] = {
      ...newest,
      home_team_master_id: 'opp',
      away_team_master_id: TEAM_ID,
      home_score: newest.away_score,
      away_score: newest.home_score,
    };

    expect(streakOf(data)).toBe('W2');
  });
});
