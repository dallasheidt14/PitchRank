/** Read frozen inputs from stdin; emit no credentials, fitted data, or target results. */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createWinnerRuntime } from '../lib/winnerResearch';
import type { MatchPredictionShadowContext } from '../lib/matchPredictionService';
import type { MatchPrediction } from '../lib/matchPredictor';

async function main() {
  const { cases, weights } = JSON.parse(readFileSync(0, 'utf8')) as {
    weights: Record<string, number>;
    cases: Array<{ context: MatchPredictionShadowContext; prediction: MatchPrediction; reference_time: string }>;
  };
  if (!cases.length) throw new Error('Empty capture batch');
  const runtime = await createWinnerRuntime(
    cases[0].context,
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  );
  try {
    console.log(JSON.stringify(cases.map((c) => runtime.run(c.context, c.prediction, c.reference_time, weights))));
  } finally {
    await runtime.close();
  }
}
main().catch(() => {
  console.error('Winner study replay failed');
  process.exitCode = 1;
});
