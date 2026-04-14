import { describe, expect, it } from 'vitest';
import { buildMissionControlSnapshot, type ProspectiveSnapshotRow } from './modelSnapshot';

describe('buildMissionControlSnapshot', () => {
  it('builds current model summaries from settled prospective rows', () => {
    const rows: ProspectiveSnapshotRow[] = [
      {
        fixture_key: 'fixture-1',
        game_date: '2026-04-10',
        resolution_status: 'resolved',
        heuristic_prediction_status: 'completed',
        heuristic_model_version: 'heuristic_v3',
        heuristic_prediction: {
          response: {
            prediction: {
              predictedWinner: 'team_a',
              winProbabilityA: 0.6,
              drawProbability: 0.2,
              winProbabilityB: 0.2,
              expectedScore: { teamA: 2, teamB: 1 },
              expectedMargin: 1,
            },
          },
          modelVersion: 'heuristic_v3',
        },
        heuristic_predicted_at: '2026-04-09T10:00:00Z',
        offline_prediction_status: 'completed',
        offline_model_version: 'pitm_hybrid',
        offline_prediction: {
          prediction: {
            predictedWinner: 'draw',
            winProbabilityA: 0.3,
            drawProbability: 0.4,
            winProbabilityB: 0.3,
            expectedScore: { teamA: 1, teamB: 1 },
            expectedMargin: 0,
          },
          modelVersion: 'pitm_hybrid',
        },
        offline_predicted_at: '2026-04-09T11:00:00Z',
        actual_home_score: 1,
        actual_away_score: 1,
        actual_outcome: 'draw',
        evaluation_status: 'settled',
      },
      {
        fixture_key: 'fixture-2',
        game_date: '2026-04-11',
        resolution_status: 'resolved',
        heuristic_prediction_status: 'completed',
        heuristic_model_version: 'heuristic_v3',
        heuristic_prediction: {
          response: {
            prediction: {
              predictedWinner: 'team_b',
              winProbabilityA: 0.1,
              drawProbability: 0.2,
              winProbabilityB: 0.7,
              expectedScore: { teamA: 0, teamB: 2 },
              expectedMargin: -2,
            },
          },
          modelVersion: 'heuristic_v3',
        },
        heuristic_predicted_at: '2026-04-10T10:00:00Z',
        offline_prediction_status: 'completed',
        offline_model_version: 'pitm_hybrid',
        offline_prediction: {
          prediction: {
            predictedWinner: 'team_b',
            winProbabilityA: 0.15,
            drawProbability: 0.25,
            winProbabilityB: 0.6,
            expectedScore: { teamA: 1, teamB: 2 },
            expectedMargin: -1,
          },
          modelVersion: 'pitm_hybrid',
        },
        offline_predicted_at: '2026-04-10T11:00:00Z',
        actual_home_score: 0,
        actual_away_score: 2,
        actual_outcome: 'team_b',
        evaluation_status: 'settled',
      },
      {
        fixture_key: 'fixture-3',
        game_date: '2026-04-12',
        resolution_status: 'unresolved',
        heuristic_prediction_status: 'pending',
        heuristic_model_version: null,
        heuristic_prediction: null,
        heuristic_predicted_at: null,
        offline_prediction_status: 'error',
        offline_model_version: 'pitm_hybrid',
        offline_prediction: null,
        offline_predicted_at: null,
        actual_home_score: null,
        actual_away_score: null,
        actual_outcome: null,
        evaluation_status: 'pending_result',
      },
    ];

    const snapshot = buildMissionControlSnapshot(rows, {
      snapshotRows: 100,
      windowStart: '2025-08-01',
      windowEnd: '2026-04-14',
      totalScoredGames: 1000,
      trainableScoredGames: 600,
      last365ScoredGames: 800,
      last365TrainableGames: 600,
    });

    expect(snapshot.currentHeuristicVersion).toBe('heuristic_v3');
    expect(snapshot.currentOfflineVersion).toBe('pitm_hybrid');
    expect(snapshot.sharedSettledGames).toBe(2);
    expect(snapshot.pipeline.totalFixtures).toBe(3);
    expect(snapshot.pipeline.pendingResult).toBe(1);
    expect(snapshot.pipeline.pendingResolution).toBe(1);
    expect(snapshot.pipeline.offlineError).toBe(1);
    expect(snapshot.heuristic.games).toBe(2);
    expect(snapshot.offline.games).toBe(2);
    expect(snapshot.heuristic.winnerAccuracy).toBe(0.5);
    expect(snapshot.offline.winnerAccuracy).toBe(1);
    expect(snapshot.offline.drawRecall).toBe(1);
    expect(snapshot.headToHead.fixturesWithBothPredictions).toBe(2);
    expect(snapshot.headToHead.winnerDisagreementRate).toBe(0.5);
  });
});
