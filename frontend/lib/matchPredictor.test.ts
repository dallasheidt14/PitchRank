import { beforeAll, describe, expect, it } from 'vitest';
import { calculateCommonOpponentSignal, predictMatch, warmMatchPredictorCalibration } from './matchPredictor';
import type { Game, TeamWithRanking } from './types';

beforeAll(async () => {
  // Calibration JSON loads fire-and-forget at module init; awaiting here makes
  // every test deterministic regardless of how fast the load resolves.
  await warmMatchPredictorCalibration();
});

function makeTeam(overrides: Partial<TeamWithRanking> = {}): TeamWithRanking {
  return {
    team_id_master: 'team-default',
    team_name: 'Default FC 14B',
    club_name: 'Default FC',
    league: null,
    distinction: null,
    state: 'TX',
    age: 12,
    gender: 'M',
    rank_in_cohort_final: 50,
    rank_in_state_final: 10,
    power_score_final: 0.5,
    glicko_rating: 1500,
    glicko_rd: 80,
    glicko_volatility: 0.05,
    sos_norm: 0.5,
    sos_norm_state: 0.5,
    sos_rank_national: 50,
    sos_rank_state: 10,
    offense_norm: 0.5,
    defense_norm: 0.5,
    wins: 10,
    losses: 5,
    draws: 2,
    games_played: 17,
    last_scraped_at: null,
    total_games_played: 17,
    total_wins: 10,
    total_losses: 5,
    total_draws: 2,
    win_percentage: 64.7,
    ...overrides,
  };
}

function makeGame(overrides: Partial<Game>): Game {
  return {
    id: crypto.randomUUID(),
    home_team_master_id: 'team-a',
    away_team_master_id: 'team-b',
    home_provider_id: 'home-provider',
    away_provider_id: 'away-provider',
    home_score: 2,
    away_score: 1,
    result: null,
    game_date: '2026-03-01',
    competition: null,
    division_name: null,
    event_name: null,
    venue: null,
    provider_id: null,
    source_url: null,
    scraped_at: null,
    created_at: '2026-03-01T00:00:00.000Z',
    ml_overperformance: null,
    is_excluded: false,
    ...overrides,
  };
}

describe('predictMatch', () => {
  it('favors the stronger team in a clear mismatch', () => {
    const teamA = makeTeam({
      team_id_master: 'team-a',
      team_name: 'Alpha FC 14B',
      power_score_final: 0.84,
      glicko_rating: 1710,
      glicko_rd: 42,
      sos_norm: 0.75,
      offense_norm: 0.82,
      defense_norm: 0.79,
      games_played: 24,
    });
    const teamB = makeTeam({
      team_id_master: 'team-b',
      team_name: 'Beta FC 14B',
      power_score_final: 0.58,
      glicko_rating: 1510,
      glicko_rd: 88,
      sos_norm: 0.46,
      offense_norm: 0.56,
      defense_norm: 0.51,
      wins: 8,
      losses: 12,
      draws: 1,
      games_played: 21,
    });

    const games: Game[] = [
      makeGame({ home_team_master_id: 'team-a', away_team_master_id: 'opp-1', home_score: 4, away_score: 0 }),
      makeGame({ home_team_master_id: 'opp-2', away_team_master_id: 'team-a', home_score: 1, away_score: 3 }),
      makeGame({ home_team_master_id: 'team-a', away_team_master_id: 'opp-3', home_score: 5, away_score: 1 }),
      makeGame({ home_team_master_id: 'opp-4', away_team_master_id: 'team-a', home_score: 0, away_score: 2 }),
      makeGame({ home_team_master_id: 'team-a', away_team_master_id: 'opp-5', home_score: 3, away_score: 1 }),
      makeGame({ home_team_master_id: 'team-b', away_team_master_id: 'opp-6', home_score: 1, away_score: 2 }),
      makeGame({ home_team_master_id: 'opp-7', away_team_master_id: 'team-b', home_score: 3, away_score: 0 }),
      makeGame({ home_team_master_id: 'team-b', away_team_master_id: 'opp-8', home_score: 1, away_score: 1 }),
      makeGame({ home_team_master_id: 'opp-9', away_team_master_id: 'team-b', home_score: 2, away_score: 1 }),
      makeGame({ home_team_master_id: 'team-b', away_team_master_id: 'opp-10', home_score: 0, away_score: 4 }),
    ];

    const prediction = predictMatch(teamA, teamB, games);

    expect(prediction.predictedWinner).toBe('team_a');
    expect(prediction.winProbabilityA).toBeGreaterThan(0.6);
    expect(prediction.drawProbability ?? 0).toBeLessThan(0.2);
    expect(
      (prediction.winProbabilityA + prediction.winProbabilityB + (prediction.drawProbability ?? 0)).toFixed(6)
    ).toBe('1.000000');
    expect(prediction.expectedMargin).toBeGreaterThan(0);
    expect(prediction.expectedScore.teamA).toBeGreaterThanOrEqual(prediction.expectedScore.teamB);
  });

  it('returns a draw-leaning, low-confidence prediction for sparse evenly matched data', () => {
    const teamA = makeTeam({
      team_id_master: 'team-a',
      team_name: 'Even FC 14B',
      games_played: 1,
      wins: 0,
      losses: 0,
      draws: 1,
      power_score_final: 0.5,
      glicko_rating: 1500,
      glicko_rd: 180,
      sos_norm: 0.5,
      offense_norm: 0.5,
      defense_norm: 0.5,
    });
    const teamB = makeTeam({
      team_id_master: 'team-b',
      team_name: 'Mirror FC 14B',
      games_played: 1,
      wins: 0,
      losses: 0,
      draws: 1,
      power_score_final: 0.5,
      glicko_rating: 1500,
      glicko_rd: 180,
      sos_norm: 0.5,
      offense_norm: 0.5,
      defense_norm: 0.5,
    });

    const prediction = predictMatch(teamA, teamB, []);

    expect(prediction.predictedWinner).toBe('draw');
    expect(prediction.confidence).toBe('low');
    expect(prediction.drawProbability ?? 0).toBeGreaterThan(0.2);
    expect(prediction.winProbabilityA).toBeGreaterThan(0);
    expect(prediction.winProbabilityA).toBeLessThan(1);
    expect(prediction.expectedScore.teamA).toBeGreaterThanOrEqual(0);
    expect(prediction.expectedScore.teamB).toBeGreaterThanOrEqual(0);
  });

  it('predicts draw for symmetric inputs even with non-sparse history', () => {
    // Non-sparse symmetric inputs: heuristic-draw conditions DO NOT trigger
    // (sparseMatchup=false because games_played=22), so the symmetric-inputs
    // short-circuit is the only path that returns 'draw'. Without it, the
    // asymmetric outcome-calibration prior would tip the predicted winner to
    // whichever side has the slightly higher prior.
    const teamA = makeTeam({
      team_id_master: 'team-a',
      team_name: 'Twin A 14B',
      games_played: 22,
      wins: 11,
      losses: 7,
      draws: 4,
      win_percentage: 50,
      power_score_final: 0.6,
      glicko_rating: 1600,
      glicko_rd: 60,
      sos_norm: 0.55,
      offense_norm: 0.6,
      defense_norm: 0.55,
    });
    const teamB = makeTeam({
      ...teamA,
      team_id_master: 'team-b',
      team_name: 'Twin B 14B',
    });

    const prediction = predictMatch(teamA, teamB, []);

    expect(prediction.predictedWinner).toBe('draw');
    expect(prediction.winProbabilityA).toBeCloseTo(prediction.winProbabilityB, 9);
    expect(
      (prediction.winProbabilityA + prediction.winProbabilityB + (prediction.drawProbability ?? 0)).toFixed(6)
    ).toBe('1.000000');
  });

  it('shrinks overconfident edges when same-age evidence is weak', () => {
    const baselineA = makeTeam({
      team_id_master: 'team-a',
      team_name: 'Evidence A 14B',
      power_score_final: 0.63,
      exp_win_rate: 0.57,
      exp_margin: 0.35,
    });
    const baselineB = makeTeam({
      team_id_master: 'team-b',
      team_name: 'Evidence B 14B',
      power_score_final: 0.61,
      exp_win_rate: 0.54,
      exp_margin: 0.2,
    });

    const baselinePrediction = predictMatch(baselineA, baselineB, []);

    const weakEvidenceA = makeTeam({
      ...baselineA,
      same_age_games: 2,
      same_age_game_share: 0.12,
      same_age_unique_opponents: 2,
      same_age_top100_opp_count: 0,
      same_age_top500_opp_count: 1,
      same_age_avg_opp_power_adj: 0.42,
      repeat_opponent_share: 0.62,
      positive_ml_evidence_scale: 0,
      publication_cap_rank: 100,
      publication_cap_score: 0.58,
    });
    const strongEvidenceB = makeTeam({
      ...baselineB,
      same_age_games: 14,
      same_age_game_share: 0.82,
      same_age_unique_opponents: 9,
      same_age_top100_opp_count: 3,
      same_age_top500_opp_count: 7,
      same_age_avg_opp_power_adj: 0.72,
      repeat_opponent_share: 0.08,
      positive_ml_evidence_scale: 1,
    });

    const evidencePrediction = predictMatch(weakEvidenceA, strongEvidenceB, []);

    expect(evidencePrediction.winProbabilityA).toBeLessThan(baselinePrediction.winProbabilityA);
    expect(evidencePrediction.components.evidenceSignal).toBeLessThan(0);
    expect(evidencePrediction.components.evidenceReliabilityA ?? 1).toBeLessThan(
      evidencePrediction.components.evidenceReliabilityB ?? 1
    );
  });

  it('uses common-opponent performance as a matchup signal', () => {
    const commonOpponentGames: Game[] = [
      makeGame({
        game_date: '2026-03-20',
        home_team_master_id: 'team-a',
        away_team_master_id: 'opp-1',
        home_score: 3,
        away_score: 0,
      }),
      makeGame({
        game_date: '2026-03-13',
        home_team_master_id: 'team-a',
        away_team_master_id: 'opp-2',
        home_score: 2,
        away_score: 0,
      }),
      makeGame({
        game_date: '2026-03-06',
        home_team_master_id: 'opp-1',
        away_team_master_id: 'team-b',
        home_score: 2,
        away_score: 1,
      }),
      makeGame({
        game_date: '2026-02-27',
        home_team_master_id: 'opp-2',
        away_team_master_id: 'team-b',
        home_score: 1,
        away_score: 1,
      }),
    ];

    const summary = calculateCommonOpponentSignal('team-a', 'team-b', commonOpponentGames);
    expect(summary.sharedOpponents).toBe(2);
    expect(summary.advantage).toBeGreaterThan(0);

    const balancedTeamA = makeTeam({
      team_id_master: 'team-a',
      team_name: 'Alpha FC 14B',
      power_score_final: 0.6,
      glicko_rating: 1535,
      glicko_rd: 90,
      sos_norm: 0.56,
      offense_norm: 0.58,
      defense_norm: 0.56,
      wins: 10,
      losses: 5,
      draws: 2,
      games_played: 17,
    });
    const balancedTeamB = makeTeam({
      team_id_master: 'team-b',
      team_name: 'Beta FC 14B',
      power_score_final: 0.6,
      glicko_rating: 1535,
      glicko_rd: 90,
      sos_norm: 0.56,
      offense_norm: 0.58,
      defense_norm: 0.56,
      wins: 10,
      losses: 5,
      draws: 2,
      games_played: 17,
    });

    const prediction = predictMatch(balancedTeamA, balancedTeamB, commonOpponentGames);

    expect(prediction.predictedWinner).toBe('team_a');
    expect(prediction.components.commonOpponentSignal ?? 0).toBeGreaterThan(0);
    expect(prediction.components.commonOpponentCount).toBe(2);
    expect(prediction.commonOpponents?.sharedOpponents).toBe(2);
  });
});
