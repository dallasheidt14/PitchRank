import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { EnhancedPredictionCard } from './EnhancedPredictionCard';
import baseline from '@/test/fixtures/compare-baseline.json';
import { summarizeMatchEvidence } from '@/lib/matchEvidence';
import type { Game, TeamWithRanking } from '@/lib/types';
import type { MatchPrediction } from '@/lib/matchPredictor';
import type { MatchExplanation } from '@/lib/matchExplainer';

const sample = baseline.cases[0];
const explanation: MatchExplanation = {
  summary: 'Alpha has the edge',
  factors: [],
  keyInsights: [],
  predictionQuality: { confidence: 'high', reliability: 'UNSUPPORTED RELIABILITY' },
  counterFactors: [
    {
      factor: 'schedule_strength',
      advantage: 'team_b',
      magnitude: 'moderate',
      description: 'Beta faced stronger opposition',
      icon: 'vs',
      score: 1,
    },
  ],
};
const prediction = { ...sample.prediction, drawProbability: 0.02 } as MatchPrediction;
const props = { teamAName: 'Alpha', teamBName: 'Beta', prediction, explanation };
it('shows small draw probabilities, opposing evidence and legacy missing-evidence state', () => {
  const html = renderToStaticMarkup(<EnhancedPredictionCard {...props} />);
  expect(html).toContain('Draw');
  expect(html).toContain('2%');
  expect(html).toContain('Projected scoreline');
  expect(html).toContain('Evidence details unavailable');
  expect(html).not.toContain('CONFIDENCE');
  expect(html).not.toContain('UNSUPPORTED RELIABILITY');
  expect(html).toContain('Reasons for caution');
  expect(html).toContain('Beta faced stronger opposition');
});
it('renders factual sparse-history counts and unavailable dates', () => {
  const evidence = summarizeMatchEvidence(
    { as_of: '2026-11-11', window_start: '2025-11-11', games: sample.games as Game[] },
    sample.teamA as TeamWithRanking,
    sample.teamB as TeamWithRanking
  );
  const html = renderToStaticMarkup(<EnhancedPredictionCard {...props} evidence={evidence} />);
  expect(html).toContain('Usable results');
  expect(html).toContain('6 of 8 recent results available');
  expect(html).toContain('Unavailable');
  expect(html).toContain('6 shared opponents');
  expect(html).not.toContain('Evidence details unavailable');
});
it('does not invent a missing draw percentage in legacy responses', () => {
  const html = renderToStaticMarkup(
    <EnhancedPredictionCard
      {...props}
      prediction={{ ...prediction, drawProbability: undefined }}
      explanation={{ ...explanation, counterFactors: undefined }}
    />
  );
  expect(html).toContain('Unavailable');
  expect(html).not.toContain('Reasons for caution');
});
