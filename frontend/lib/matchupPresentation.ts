import type { MatchPrediction } from './matchPredictor';

/** Presentation only: the saved predictor decision and probabilities stay intact. */
export function presentMatchup(
  prediction: Pick<MatchPrediction, 'winProbabilityA' | 'winProbabilityB' | 'drawProbability' | 'predictedWinner'>,
  teamAName: string,
  teamBName: string
) {
  const a = prediction.winProbabilityA;
  const b = prediction.winProbabilityB;
  const draw = prediction.drawProbability;
  const valid = (value: unknown): value is number =>
    typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
  if (!valid(a) || !valid(b))
    return {
      favorite: null,
      closelyMatched: false,
      winGap: null,
      showScore: false,
      summary: 'Prediction unavailable',
    };
  const drawLeading = valid(draw) && draw > Math.max(a, b);
  const tied = Math.abs(a - b) < 1e-9;
  const favorite: 'team_a' | 'team_b' | null = drawLeading || tied ? null : a > b ? 'team_a' : 'team_b';
  const closelyMatched = Math.abs(a - b) <= 0.1 + 1e-12;
  let summary: string;
  if (drawLeading) summary = `A draw is the most likely outcome (${Math.round(draw * 100)}% draw probability)`;
  else if (tied)
    summary = `No clear favorite (${Math.round(a * 100)}% / ${valid(draw) ? `${Math.round(draw * 100)}% draw` : 'draw unavailable'} / ${Math.round(b * 100)}%)`;
  else {
    const name = favorite === 'team_a' ? teamAName : teamBName;
    const probability = Math.round(Math.max(a, b) * 100);
    summary = closelyMatched
      ? `${name} has a slight edge at ${probability}% win probability`
      : probability >= 75
        ? `${name} is the clear favorite at ${probability}% win probability`
        : `${name} has the edge with ${probability}% win probability`;
  }
  const showScore =
    prediction.predictedWinner === 'draw'
      ? drawLeading
      : !drawLeading && (favorite === null || prediction.predictedWinner === favorite);
  return { favorite, closelyMatched, drawMostLikely: drawLeading, winGap: Math.abs(a - b), showScore, summary };
}
