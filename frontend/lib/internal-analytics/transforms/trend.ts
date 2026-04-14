const FLAT_THRESHOLD = 0.05; // |normalized_slope| below this = flat

export function computeTrend(series: number[]): {
  trend_direction: 'up' | 'down' | 'flat';
  trend_strength: number;
} {
  if (series.length < 2) return { trend_direction: 'flat', trend_strength: 0 };

  const n = series.length;
  const xs = Array.from({ length: n }, (_, i) => i);
  const meanX = xs.reduce((a, b) => a + b, 0) / n;
  const meanY = series.reduce((a, b) => a + b, 0) / n;

  let num = 0,
    den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i] - meanX) * (series[i] - meanY);
    den += (xs[i] - meanX) ** 2;
  }
  const slope = den === 0 ? 0 : num / den;
  const normalized = meanY === 0 ? 0 : slope / Math.abs(meanY);
  const strength = Math.min(1, Math.abs(normalized));

  if (Math.abs(normalized) < FLAT_THRESHOLD) return { trend_direction: 'flat', trend_strength: 0 };
  return { trend_direction: normalized > 0 ? 'up' : 'down', trend_strength: strength };
}

export function pctDelta(current: number, previous: number): number {
  if (previous === 0) return current === 0 ? 0 : 1;
  return (current - previous) / previous;
}
