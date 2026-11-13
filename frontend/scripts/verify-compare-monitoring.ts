import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PREDICTOR_SOURCE_FILES, PREDICTOR_CALIBRATION_FILES } from '../lib/predictionSourceInventory';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
for (const file of [
  ...PREDICTOR_SOURCE_FILES.map((f) => `frontend/lib/${f}`),
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
