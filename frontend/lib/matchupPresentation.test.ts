import { describe, expect, it } from 'vitest';
import { presentMatchup } from './matchupPresentation';

describe('matchup presentation independent of the model decision', () => {
  it('does not label tied win chances as a likely draw', () => {
    const result = presentMatchup(
      { winProbabilityA: 0.45, winProbabilityB: 0.45, drawProbability: 0.1, predictedWinner: 'draw' },
      'Alpha',
      'Beta'
    );
    expect(result.summary).toContain('No clear favorite');
    expect(result.closelyMatched).toBe(true);
    expect(result.showScore).toBe(false);
    expect(result.favorite).toBeNull();
  });
  it('only calls a draw most likely when it leads both win probabilities', () => {
    const result = presentMatchup(
      { winProbabilityA: 0.3, winProbabilityB: 0.3, drawProbability: 0.4, predictedWinner: 'draw' },
      'Alpha',
      'Beta'
    );
    expect(result.summary).toContain('A draw is the most likely outcome');
    expect(result.showScore).toBe(true);
  });
  it('shows a slight edge independently of matchup closeness and model draw override', () => {
    const result = presentMatchup(
      { winProbabilityA: 0.423, winProbabilityB: 0.401, drawProbability: 0.176, predictedWinner: 'draw' },
      'Alpha',
      'Beta'
    );
    expect(result.summary).toContain('Alpha has a slight edge');
    expect(result.closelyMatched).toBe(true);
    expect(result.showScore).toBe(false);
  });
  it('swaps the displayed favorite and preserves closeness', () => {
    const result = presentMatchup(
      { winProbabilityA: 0.401, winProbabilityB: 0.423, drawProbability: 0.176, predictedWinner: 'team_b' },
      'Beta',
      'Alpha'
    );
    expect(result.summary).toContain('Alpha has a slight edge');
    expect(result.favorite).toBe('team_b');
    expect(result.showScore).toBe(true);
  });
  it('does not invent a missing draw probability', () => {
    const result = presentMatchup(
      { winProbabilityA: 0.5, winProbabilityB: 0.5, predictedWinner: 'draw' },
      'Alpha',
      'Beta'
    );
    expect(result.summary).toContain('draw unavailable');
    expect(result.showScore).toBe(false);
  });
  it('does not present invalid probabilities as a favorite', () => {
    expect(
      presentMatchup({ winProbabilityA: NaN, winProbabilityB: 0.5, predictedWinner: 'team_a' }, 'A', 'B').showScore
    ).toBe(false);
  });
});
