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
    gf: 3,
    ga: 1,
    team_mu: 1500,
    team_sigma: 82,
    opp_mu: 1670,
    opp_sigma: 79,
    expected_outcome: 0.42,
    actual_outcome: 0.86,
    outcome_surprise: 0.44,
    g_factor: 0.94,
    recency_weight: 1.19,
    rating_contribution: 0.14,
    off_residual: 1.3,
    def_residual: 0.8,
    last_calculated: '2026-04-11T00:00:00Z',
    created_at: '2026-04-11T00:00:00Z',
    ...overrides,
  };
}

describe('explainGameBreakdown', () => {
  it('describes positive, above-expectation results without raw Glicko jargon', () => {
    const explanation = explainGameBreakdown(makeBreakdown());
    const combinedCopy = [explanation.headline, explanation.summary]
      .concat(explanation.factors.map((factor) => `${factor.label} ${factor.detail}`))
      .join(' ');

    expect(explanation.headline).toContain('helped the rating');
    expect(explanation.impactTone).toBe('positive');
    expect(explanation.factors.some((factor) => factor.label.toLowerCase().includes('expectation'))).toBe(true);
    expect(
      explanation.factors.some(
        (factor) => factor.label.includes('Faced a stronger opponent') || factor.label.includes('Stepped up in class')
      )
    ).toBe(true);
    expect(combinedCopy).not.toContain('Glicko');
    expect(combinedCopy).not.toContain('RD');
  });

  it('flags negative results when the team comes in below expectation', () => {
    const explanation = explainGameBreakdown(
      makeBreakdown({
        expected_outcome: 0.68,
        actual_outcome: 0.24,
        outcome_surprise: -0.44,
        rating_contribution: -0.17,
        off_residual: -1.1,
        def_residual: -1.5,
        opp_mu: 1430,
      })
    );

    expect(explanation.headline).toContain('pulled the rating down');
    expect(explanation.impactTone).toBe('negative');
    expect(explanation.factors.some((factor) => factor.label.toLowerCase().includes('expectation'))).toBe(true);
    expect(explanation.factors.some((factor) => factor.label.includes('Defense leaked chances'))).toBe(true);
  });

  it('returns a neutral summary for low-impact games', () => {
    const explanation = explainGameBreakdown(
      makeBreakdown({
        expected_outcome: 0.51,
        actual_outcome: 0.5,
        outcome_surprise: -0.01,
        recency_weight: 0.91,
        rating_contribution: 0.008,
        off_residual: 0.2,
        def_residual: -0.1,
        opp_mu: 1510,
      })
    );

    expect(explanation.impactTone).toBe('neutral');
    expect(explanation.headline).toContain('close to neutral');
    expect(explanation.impactLabel).toBe('Light rating touch');
    expect(explanation.factors.length).toBeLessThanOrEqual(1);
  });
});
