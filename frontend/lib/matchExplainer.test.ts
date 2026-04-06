import { describe, expect, it } from 'vitest';
import { explainMatch } from './matchExplainer';
import type { MatchPrediction } from './matchPredictor';
import type { TeamWithRanking } from './types';

function makeTeam(overrides: Partial<TeamWithRanking> = {}): TeamWithRanking {
  return {
    team_id_master: 'team-default',
    team_name: 'Default FC 14B',
    club_name: 'Default FC',
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

function makePrediction(overrides: Partial<MatchPrediction> = {}): MatchPrediction {
  return {
    predictedWinner: 'team_a',
    winProbabilityA: 0.73,
    winProbabilityB: 0.27,
    expectedScore: { teamA: 3, teamB: 1 },
    expectedMargin: 2,
    confidence: 'high',
    confidence_score: 0.82,
    components: {
      powerDiff: 0.18,
      strengthSignal: 0.2,
      sosDiff: 0.14,
      formDiffRaw: 2.8,
      formDiffNorm: 0.11,
      matchupAdvantage: 0.19,
      compositeDiff: 0.24,
      mismatchScore: 0.31,
    },
    formA: 2.8,
    formB: -0.5,
    h2h: {
      gamesPlayed: 3,
      avgMargin: 1.8,
    },
    ...overrides,
  };
}

describe('explainMatch', () => {
  it('includes head-to-head context when prior meetings exist', () => {
    const teamA = makeTeam({
      team_id_master: 'team-a',
      team_name: 'Alpha FC 14B',
      power_score_final: 0.81,
      sos_norm: 0.71,
      offense_norm: 0.8,
      defense_norm: 0.76,
    });
    const teamB = makeTeam({
      team_id_master: 'team-b',
      team_name: 'Beta FC 14B',
      power_score_final: 0.63,
      sos_norm: 0.49,
      offense_norm: 0.54,
      defense_norm: 0.51,
    });

    const explanation = explainMatch(teamA, teamB, makePrediction());

    expect(explanation.summary).toContain('Alpha FC');
    expect(explanation.factors.some((factor) => factor.factor === 'head_to_head')).toBe(true);
    expect(explanation.predictionQuality.confidence).toBe('high');
  });

  it('describes toss-up matches as genuinely close', () => {
    const teamA = makeTeam({ team_id_master: 'team-a', team_name: 'Even FC 14B' });
    const teamB = makeTeam({ team_id_master: 'team-b', team_name: 'Mirror FC 14B' });

    const explanation = explainMatch(
      teamA,
      teamB,
      makePrediction({
        predictedWinner: 'draw',
        winProbabilityA: 0.5,
        winProbabilityB: 0.5,
        expectedScore: { teamA: 2, teamB: 2 },
        expectedMargin: 0,
        confidence: 'low',
        confidence_score: 0.41,
        components: {
          powerDiff: 0,
          strengthSignal: 0,
          sosDiff: 0,
          formDiffRaw: 0,
          formDiffNorm: 0,
          matchupAdvantage: 0,
          compositeDiff: 0,
          mismatchScore: 0,
        },
        formA: 0,
        formB: 0,
        h2h: undefined,
      })
    );

    expect(explanation.summary).toContain('Genuine toss-up');
    expect(explanation.factors.some((factor) => factor.factor === 'close_match')).toBe(true);
    expect(explanation.keyInsights.join(' ')).toContain('Coin-flip');
  });
});
