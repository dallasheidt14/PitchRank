/** Offline only: compare the unchanged extra ML share term with that term disabled. */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createSosRuntime } from '../lib/sosResearch';
import { MATCH_PREDICTION_VERSION, type MatchPredictionShadowContext } from '../lib/matchPredictionService';
import type { MatchPrediction } from '../lib/matchPredictor';

async function main() {
  const payload = JSON.parse(readFileSync(0, 'utf8')) as {
    verifiedProductionRuntime?: boolean;
    cases: Array<{ context: MatchPredictionShadowContext; prediction?: MatchPrediction; reference_time: string }>;
  };
  if (!Array.isArray(payload.cases) || !payload.cases.length) throw new Error('Frozen cases required');
  const runtime = await createSosRuntime(
    payload.cases[0].context.calibration!,
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'),
    { verifiedProductionRuntime: payload.verifiedProductionRuntime === true }
  );
  try {
    const results = payload.cases.map((c) => ({
      ...runtime.compareMlShare(c.context, c.reference_time, c.prediction),
      input_predictor_version: c.context.predictorVersion,
      research_predictor_version: MATCH_PREDICTION_VERSION,
      baseline_origin: c.prediction ? 'verified_frozen_prediction' : 'reconstructed_from_frozen_inputs',
      production_promotion: false,
    }));
    console.log(JSON.stringify(results));
  } finally {
    await runtime.close();
  }
}
main().catch(() => {
  console.error('ML share research failed');
  process.exitCode = 1;
});
