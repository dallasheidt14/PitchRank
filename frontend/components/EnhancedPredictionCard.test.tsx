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
it('shows small draw probabilities and opposing factors without an evidence panel', () => {
  const html = renderToStaticMarkup(<EnhancedPredictionCard {...props} />);
  expect(html).toContain('Draw');
  expect(html).toContain('2%');
  expect(html).toContain('Projected scoreline');
  expect(html).not.toContain('Evidence details unavailable');
  expect(html).not.toContain('CONFIDENCE');
  expect(html).not.toContain('UNSUPPORTED RELIABILITY');
  expect(html).toContain('Reasons for caution');
  expect(html).toContain('Beta faced stronger opposition');
});
it('keeps a concise limited-history caution without displaying evidence diagnostics', () => {
  const evidence = summarizeMatchEvidence(
    { as_of: '2026-11-11', window_start: '2025-11-11', games: sample.games as Game[] },
    sample.teamA as TeamWithRanking,
    sample.teamB as TeamWithRanking
  );
  const html = renderToStaticMarkup(<EnhancedPredictionCard {...props} evidence={evidence} />);
  expect(html).not.toContain('Usable results');
  expect(html).toContain('limited recent results available');
  expect(html).not.toContain('Rating snapshot');
  expect(html).not.toContain('Evidence behind this prediction');
  expect(html).not.toContain('6 shared opponents');
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

it('hides a forced draw score and keeps the balanced probabilities and cautions', () => {
  const html = renderToStaticMarkup(
    <EnhancedPredictionCard
      {...props}
      prediction={{
        ...prediction,
        predictedWinner: 'draw',
        winProbabilityA: 0.45,
        drawProbability: 0.1,
        winProbabilityB: 0.45,
        expectedScore: { teamA: 1, teamB: 1 },
      }}
    />
  );
  expect(html).toContain('No clear favorite');
  expect(html).toContain('Closely matched');
  expect(html).toContain('10%');
  expect(html).not.toContain('Projected scoreline');
  expect(html).toContain('Reasons for caution');
  expect(html).not.toContain('Usable results');
});

it('keeps the score when a draw is strictly the most likely outcome', () => {
  const html = renderToStaticMarkup(
    <EnhancedPredictionCard
      {...props}
      prediction={{
        ...prediction,
        predictedWinner: 'draw',
        winProbabilityA: 0.3,
        drawProbability: 0.4,
        winProbabilityB: 0.3,
        expectedScore: { teamA: 1, teamB: 1 },
      }}
    />
  );
  expect(html).toContain('A draw is the most likely outcome');
  expect(html).toContain('Projected scoreline');
});
