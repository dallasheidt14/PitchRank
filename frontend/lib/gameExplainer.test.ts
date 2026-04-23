import { describe, expect, it } from 'vitest';
import { explainGameBreakdown } from './gameExplainer';
import type { GameExplainability } from './types';

function makeBreakdown(overrides: Partial<GameExplainability> = {}): GameExplainability {
  return {
    team_id: '11111111-1111-1111-1111-111111111111',
    game_uuid: '22222222-2222-2222-2222-222222222222',
    game_id: 'provider-game-1',
    opp_id: '33333333-3333-3333-3333-333333333333',
    game_date: '2026-04-01',
    gf: 4,
    ga: 0,
    team_mu: 1500,
    team_sigma: 82,
    opp_mu: 1670,
    opp_sigma: 79,
    expected_outcome: 0.42,
    actual_outcome: 0.86,
    outcome_surprise: 0.44,
    g_factor: 0.94,
    recency_weight: 0.12,
    rating_contribution: 0.14,
    off_residual: 2.1,
    def_residual: 0.4,
    last_calculated: '2026-04-11T00:00:00Z',
    created_at: '2026-04-11T00:00:00Z',
    ...overrides,
  };
}

describe('explainGameBreakdown', () => {
  it('summarizes a standout result around the highlight rule, expectation, and actual result', () => {
    const explanation = explainGameBreakdown(makeBreakdown(), 2.4);
    const combinedCopy = [
      explanation.headline,
      explanation.highlightReason,
      explanation.expectationLine,
      explanation.actualLine,
    ]
      .concat(explanation.details)
      .join(' ');

    expect(explanation.headline).toBe('Outperformed expectation');
    expect(explanation.tone).toBe('positive');
    expect(explanation.highlightReason).toBe('Result came in 2.4 goals better than model expectation.');
    expect(explanation.expectationLine).toBe('Model expected this team to have a 1.6-goal win.');
    expect(explanation.actualLine).toBe('This team won 4-0. Margin was 4.0 goals.');
    expect(explanation.details).toContain('They scored more than PitchRank expected.');
    expect(explanation.details).toContain('It stood out more because it came against a stronger opponent.');
    expect(combinedCopy.toLowerCase()).not.toContain('recency');
    expect(combinedCopy.toLowerCase()).not.toContain('bump');
  });

  it('flags negative results when the team comes in below expectation', () => {
    const explanation = explainGameBreakdown(
      makeBreakdown({
        gf: 0,
        ga: 4,
        expected_outcome: 0.68,
        actual_outcome: 0.24,
        outcome_surprise: -0.44,
        rating_contribution: -0.17,
        off_residual: -1.2,
        def_residual: -2.0,
        opp_mu: 1410,
      }),
      -2.3
    );

    expect(explanation.headline).toBe('Came in below expectation');
    expect(explanation.tone).toBe('negative');
    expect(explanation.highlightReason).toBe('Result came in 2.3 goals worse than model expectation.');
    expect(explanation.expectationLine).toBe('Model expected this team to have a 1.7-goal loss.');
    expect(explanation.actualLine).toBe('This team lost 0-4. Margin was 4.0 goals.');
    expect(explanation.details).toContain('They allowed more goals than PitchRank expected.');
    expect(explanation.details).toContain('It hurt more because PitchRank saw this as the easier matchup.');
  });

  it('returns a neutral summary for low-impact games', () => {
    const explanation = explainGameBreakdown(
      makeBreakdown({
        gf: 2,
        ga: 1,
        expected_outcome: 0.51,
        actual_outcome: 0.5,
        outcome_surprise: -0.01,
        recency_weight: 0.02,
        rating_contribution: 0.008,
        off_residual: 0.1,
        def_residual: -0.1,
        opp_mu: 1510,
      }),
      0.2
    );

    expect(explanation.tone).toBe('neutral');
    expect(explanation.headline).toBe('Landed close to expectation');
    expect(explanation.highlightReason).toBeNull();
    expect(explanation.expectationLine).toBe('Model expected this team to have a 0.8-goal win.');
    expect(explanation.actualLine).toBe('This team won 2-1. Margin was 1.0 goals.');
    expect(explanation.details).toEqual(['Nothing major stood out beyond the result itself.']);
  });
});
