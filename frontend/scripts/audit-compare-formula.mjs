// tsx initializes its disk cache before TypeScript entrypoints run.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const result = spawnSync(
  process.execPath,
  ['--import', 'tsx', fileURLToPath(new URL('./audit-compare-formula.ts', import.meta.url)), ...process.argv.slice(2)],
  { env: { ...process.env, TSX_DISABLE_CACHE: '1' }, stdio: 'inherit', windowsHide: true }
);
if (result.error) console.error('Formula runner could not start.');
process.exitCode = result.status ?? 1;
