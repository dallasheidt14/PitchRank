/** Offline only. Default mode writes nothing, including temporary files. */
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { buildFormulaReport } from '../lib/compareFormulaReport';

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('--help')) {
    console.log('audit-compare-formula --input PRIVATE_EXPORT [--synthetic] [--execute --output IGNORED_REPORT]');
    return;
  }
  const options: Record<string, string> = {};
  const flags = new Set<string>();
  for (let i = 0; i < args.length; i++) {
    const key = args[i];
    if (['--synthetic', '--execute'].includes(key) && !flags.has(key)) flags.add(key);
    else if (['--input', '--output'].includes(key) && !options[key] && args[i + 1] && !args[i + 1].startsWith('--'))
      options[key] = args[++i];
    else throw new Error('Invalid or repeated argument');
  }
  if (!options['--input'] || flags.has('--execute') !== Boolean(options['--output']))
    throw new Error('Input required; execute and output must be supplied together');
  const input = JSON.parse(readFileSync(options['--input'], 'utf8'));
  const report = await buildFormulaReport(
    input,
    path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'),
    flags.has('--synthetic')
  );
  if (flags.has('--execute')) {
    const output = path.resolve(options['--output']);
    // The caller creates a private ignored directory; refuse tracked/public output and overwrites.
    execFileSync('git', ['check-ignore', '-q', '--', output], { cwd: path.dirname(output), windowsHide: true });
    writeFileSync(output, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
  }
  console.log(
    JSON.stringify({
      ...report.summary,
      output_written: flags.has('--execute'),
      frozen_sensitivity: report.frozen_sensitivity.stats,
      synthetic_sensitivity: report.synthetic_sensitivity?.stats,
      boundary_sensitivity: report.boundary_sensitivity?.stats,
    })
  );
}
main().catch((error) => {
  console.error(error instanceof Error ? error.message : 'Formula audit failed');
  process.exitCode = 1;
});
