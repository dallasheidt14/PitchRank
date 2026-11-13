import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  PREDICTOR_SOURCE_FILES,
  PREDICTOR_CALIBRATION_FILES,
  PREDICTOR_INPUT_SOURCE_FILES,
} from '../lib/predictionSourceInventory';
import { captureCodeIdentity } from '../lib/prospectiveCapture';
import { loadMonitoringRuntime } from '../lib/monitoringRuntime';

async function main() {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  for (const file of [
    ...PREDICTOR_SOURCE_FILES.map((f) => `frontend/lib/${f}`),
    ...PREDICTOR_INPUT_SOURCE_FILES.map((f) => `frontend/lib/${f}`),
    ...Object.values(PREDICTOR_CALIBRATION_FILES).map((f) => `frontend/public/data/calibration/${f}`),
  ]) {
    const current = execFileSync('git', ['show', `FETCH_HEAD:${file}`], {
      cwd: root,
      encoding: 'utf8',
      windowsHide: true,
    });
    if (current.replace(/\r\n/g, '\n') !== readFileSync(path.join(root, file), 'utf8').replace(/\r\n/g, '\n'))
      throw new Error('Monitored formula or calibration differs from main; register the live revision separately.');
  }
  console.log('Monitored formula and calibration match main.');
  await loadMonitoringRuntime(root, captureCodeIdentity().algorithmHash, { fetchMissingRevision: true });
  console.log('Deployed predictor source matches monitoring; effective runtime available.');
}
main().catch(() => {
  console.error('Monitoring source/runtime preflight failed.');
  process.exitCode = 1;
});
