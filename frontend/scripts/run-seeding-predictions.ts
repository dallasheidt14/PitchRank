import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createClient } from '@supabase/supabase-js';
import { buildSeedingPredictions, type SeedingCohorts } from '../lib/seedingPredictions';

async function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) throw new Error('Seeding prediction input and output paths are required');
  const payload = JSON.parse(await readFile(resolve(inputPath), 'utf8')) as {
    schema_version: number;
    cohorts: SeedingCohorts;
  };
  if (payload.schema_version !== 1 || !payload.cohorts || typeof payload.cohorts !== 'object') {
    throw new Error('Invalid seeding prediction input');
  }
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_KEY;
  if (!url || !key) throw new Error('Supabase credentials are required in the environment');
  const supabase = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
  const result = await buildSeedingPredictions(supabase, payload.cohorts);
  await writeFile(resolve(outputPath), JSON.stringify(result), 'utf8');
}

main().catch(() => {
  // Database/HTTP errors can contain request details. Never emit credentials.
  process.stderr.write('Seeding Compare prediction failed. Verify database access and current ranking inputs.\n');
  process.exitCode = 1;
});
