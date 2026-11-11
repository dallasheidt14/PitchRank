import fs from 'node:fs';
import path from 'node:path';
import { createClient } from '@supabase/supabase-js';
import { captureForecasts, type CaptureOptions } from '../lib/prospectiveCapture';

// Never override the runner's environment or print credentials.
for (const name of ['.env.local', '../.env.local', '../.env']) {
  if (!fs.existsSync(name)) continue;
  for (const raw of fs.readFileSync(name, 'utf8').split(/\r?\n/)) {
    const match = raw.trim().match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
    if (match && process.env[match[1]] == null) process.env[match[1]] = match[2].replace(/^(['"])(.*)\1$/, '$2');
  }
}
async function main() {
  const args = process.argv.slice(2);
  const options: CaptureOptions = {
    status: 'pending',
    limit: 500,
    execute: false,
    concurrency: 4,
    budgetMinutes: 45,
    source: 'all',
  };
  let summaryPath: string | undefined;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--execute') options.execute = true;
    else if (arg === '--dry-run') options.execute = false;
    else if (['--status', '--source', '--limit', '--concurrency', '--budget-minutes', '--summary-path'].includes(arg)) {
      const value = args[++i];
      if (!value) throw new Error('Missing value for ' + arg);
      if (arg === '--status') {
        if (value !== 'pending' && value !== 'error') throw new Error('Status must be pending or error');
        options.status = value;
      } else if (arg === '--source') {
        if (value !== 'all' && value !== 'database') throw new Error('Source must be all or database');
        options.source = value;
      } else if (arg === '--summary-path') summaryPath = value;
      else {
        const number = Number(value);
        if (!Number.isSafeInteger(number) || number < 1) throw new Error('Invalid ' + arg);
        if (arg === '--limit') options.limit = number;
        else if (arg === '--concurrency') options.concurrency = Math.min(number, 4);
        else options.budgetMinutes = Math.min(number, 45);
      }
    } else throw new Error('Unknown option ' + arg + '; model version labels cannot be overridden');
  }
  if (args.includes('--execute') && args.includes('--dry-run')) throw new Error('Choose execute or dry-run');
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) throw new Error('Missing Supabase URL or service role key');
  const client = createClient(url, key, { auth: { autoRefreshToken: false, persistSession: false } });
  const summary = await captureForecasts(client, options);
  if (options.execute && summaryPath) {
    fs.mkdirSync(path.dirname(path.resolve(summaryPath)), { recursive: true });
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
  }
  process.stdout.write(JSON.stringify(summary, null, 2) + '\n');
  if (summary.errored > 0 || summary.deadlineReached) process.exitCode = 1;
}
main().catch((error) => {
  process.stderr.write((error instanceof Error ? error.message : String(error)) + '\n');
  process.exitCode = 1;
});
