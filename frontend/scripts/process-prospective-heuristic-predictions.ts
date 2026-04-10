import fs from 'node:fs';
import path from 'node:path';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { MATCH_PREDICTION_VERSION, buildMatchPredictionWithShadowContext } from '../lib/matchPredictionService';

type ProspectiveFixtureRow = {
  id: string;
  fixture_key: string;
  home_team_master_id: string | null;
  away_team_master_id: string | null;
};

type ScriptOptions = {
  status: string;
  limit: number;
  heuristicModelVersion?: string;
  summaryPath?: string;
};

function loadEnvFile(filePath: string): void {
  if (!fs.existsSync(filePath)) return;
  const content = fs.readFileSync(filePath, 'utf8');
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const separatorIndex = line.indexOf('=');
    if (separatorIndex <= 0) continue;
    const key = line.slice(0, separatorIndex).trim();
    if (!key || process.env[key] != null) continue;
    let value = line.slice(separatorIndex + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
}

function bootstrapEnv(): void {
  loadEnvFile(path.resolve(process.cwd(), '.env.local'));
  loadEnvFile(path.resolve(process.cwd(), '..', '.env.local'));
}

function getSupabase(): SupabaseClient {
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_KEY;
  if (!url || !key) {
    throw new Error('Missing SUPABASE_URL/NEXT_PUBLIC_SUPABASE_URL or service key');
  }
  return createClient(url, key, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
    },
  });
}

function parseArgs(argv: string[]): ScriptOptions {
  const options: ScriptOptions = {
    status: 'pending',
    limit: 100,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];
    if (arg === '--status' && next) {
      options.status = next;
      index += 1;
    } else if (arg === '--limit' && next) {
      options.limit = Number.parseInt(next, 10);
      index += 1;
    } else if (arg === '--heuristic-model-version' && next) {
      options.heuristicModelVersion = next;
      index += 1;
    } else if (arg === '--summary-path' && next) {
      options.summaryPath = next;
      index += 1;
    }
  }

  if (!Number.isFinite(options.limit) || options.limit <= 0) {
    throw new Error(`Invalid --limit value: ${options.limit}`);
  }
  return options;
}

function errorPayload(error: unknown, modelVersion: string) {
  const message = error instanceof Error ? error.message : String(error);
  const type = error instanceof Error ? error.name : 'Error';
  return {
    modelVersion,
    error: {
      type,
      message,
    },
  };
}

function isMissingTableError(error: unknown, tableName: string): boolean {
  const message = String((error as { message?: string } | null)?.message ?? error ?? '').toLowerCase();
  return (
    (message.includes('could not find the table') || message.includes('schema cache')) &&
    message.includes(tableName.toLowerCase())
  );
}

async function fetchPendingRows(
  supabase: SupabaseClient,
  status: string,
  limit: number
): Promise<ProspectiveFixtureRow[]> {
  const { data, error } = await supabase
    .from('prospective_match_predictions')
    .select('id, fixture_key, home_team_master_id, away_team_master_id')
    .eq('resolution_status', 'resolved')
    .eq('heuristic_prediction_status', status)
    .order('game_date', { ascending: true })
    .limit(limit);

  if (error) {
    if (isMissingTableError(error, 'prospective_match_predictions')) {
      throw new Error(
        'prospective_match_predictions table is missing. Apply the new Supabase migration before running heuristic freezing.'
      );
    }
    throw error;
  }
  return (data ?? []) as ProspectiveFixtureRow[];
}

async function updateRow(supabase: SupabaseClient, rowId: string, payload: Record<string, unknown>): Promise<void> {
  const { error } = await supabase.from('prospective_match_predictions').update(payload).eq('id', rowId);
  if (error) {
    throw error;
  }
}

async function processRows(options: ScriptOptions) {
  bootstrapEnv();
  if (!process.env.SUPABASE_URL && !process.env.NEXT_PUBLIC_SUPABASE_URL) {
    throw new Error('Missing SUPABASE_URL or NEXT_PUBLIC_SUPABASE_URL');
  }
  if (!process.env.SUPABASE_SERVICE_ROLE_KEY && !process.env.SUPABASE_SERVICE_KEY && !process.env.SUPABASE_KEY) {
    throw new Error('Missing SUPABASE_SERVICE_ROLE_KEY, SUPABASE_SERVICE_KEY, or SUPABASE_KEY');
  }
  const supabase = getSupabase();
  const modelVersion = options.heuristicModelVersion || MATCH_PREDICTION_VERSION;
  const rows = await fetchPendingRows(supabase, options.status, options.limit);
  const summary = {
    requestedStatus: options.status,
    requestedLimit: options.limit,
    heuristicModelVersion: modelVersion,
    fetchedRows: rows.length,
    processed: 0,
    completed: 0,
    errored: 0,
    rowIds: [] as string[],
  };

  for (const row of rows) {
    summary.processed += 1;
    summary.rowIds.push(row.id);

    try {
      if (!row.home_team_master_id || !row.away_team_master_id) {
        throw new Error(`Row ${row.fixture_key} is missing resolved team IDs`);
      }

      const result = await buildMatchPredictionWithShadowContext(
        supabase,
        row.home_team_master_id,
        row.away_team_master_id
      );

      await updateRow(supabase, row.id, {
        heuristic_prediction_status: 'completed',
        heuristic_model_version: modelVersion,
        heuristic_prediction: {
          modelVersion,
          response: result.response,
          shadowContext: result.shadowContext,
        },
        heuristic_predicted_at: new Date().toISOString(),
      });

      summary.completed += 1;
    } catch (error) {
      await updateRow(supabase, row.id, {
        heuristic_prediction_status: 'error',
        heuristic_model_version: modelVersion,
        heuristic_prediction: errorPayload(error, modelVersion),
        heuristic_predicted_at: new Date().toISOString(),
      });
      summary.errored += 1;
    }
  }

  if (options.summaryPath) {
    const resolvedPath = path.resolve(process.cwd(), options.summaryPath);
    fs.mkdirSync(path.dirname(resolvedPath), { recursive: true });
    fs.writeFileSync(resolvedPath, JSON.stringify(summary, null, 2), 'utf8');
  }

  process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
}

processRows(parseArgs(process.argv.slice(2))).catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exit(1);
});
