/** Offline replay entry point, also exercised through the real Node/tsx runtime. */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createSosRuntime } from '../lib/sosResearch';
import type { MatchPredictionShadowContext } from '../lib/matchPredictionService';
import type { MatchPrediction } from '../lib/matchPredictor';

async function main() {
  const payload = JSON.parse(readFileSync(0, 'utf8')) as {
    cases: Array<{
      context: MatchPredictionShadowContext;
      prediction: MatchPrediction;
      reference_time: string;
    }>;
  };
  const runtime = await createSosRuntime(
    payload.cases[0].context.calibration!,
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  );
  try {
    // Each case supplies its complete frozen context, saved prediction and original UTC clock.
    const results = payload.cases.map((c) => runtime.run(c.context, c.prediction, c.reference_time));
    console.log(JSON.stringify(results));
  } finally {
    await runtime.close();
  }
}
main().catch(() => {
  console.error('SOS replay failed');
  process.exitCode = 1;
});
