/** Offline source checks only. Authority and pre-match availability require the private archive index. */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { stableJson } from '../lib/canonicalJson';

export const PINNED_REVISION = '866f30c73a84524028b9fe8e55b3108ec8d544fc';
export const PINNED_SIGNATURE = '1718e7be40328a18901f93df30ed31f99581b7b481af71de9277f700462dde05';
type RecordValue = Record<string, unknown>;
type ReadSource = (revision: string, name: string) => string;
const digest = (value: unknown) => createHash('sha256').update(stableJson(value)).digest('hex');
const object = (value: unknown): RecordValue => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('missing_object');
  return value as RecordValue;
};
const requiredString = (value: unknown) => {
  if (typeof value !== 'string' || !value) throw new Error('missing_identity');
  return value;
};

export function sourceVerifier(readSource: ReadSource) {
  const pinnedCapture = readSource(PINNED_REVISION, 'prospectiveCapture.ts');
  const declaration = pinnedCapture.match(/const files = \[([\s\S]*?)\];/);
  const names = [...(declaration?.[1].matchAll(/'([A-Za-z0-9]+\.ts)'/g) ?? [])].map((match) => match[1]);
  if (!names.length || names.length !== new Set(names).size) throw new Error('invalid_pinned_module_list');
  if (readSource(PINNED_REVISION, 'canonicalJson.ts') !== readSource('workspace', 'canonicalJson.ts'))
    throw new Error('canonical_serialization_changed');
  const sources = names.map((name) => [name, readSource(PINNED_REVISION, name)]);
  const algorithm = digest(sources);
  const modelVersion = readSource(PINNED_REVISION, 'matchPredictionService.ts').match(
    /export const MATCH_PREDICTION_VERSION = '([^']+)'/
  )?.[1];
  if (!modelVersion) throw new Error('missing_pinned_model_version');
  const revisions = new Map<string, string[]>();

  function fieldsAt(revision: string) {
    const known = revisions.get(revision);
    if (known) return known;
    if (sources.some(([name, content]) => readSource(revision, name) !== content))
      throw new Error('collecting_predictor_changed');
    const capture = readSource(revision, 'prospectiveCapture.ts');
    const fetch = capture.split('export async function fetchCaptureRows(')[1]?.split('async function checkSource(')[0];
    const projection = fetch
      ?.match(/\.select\(\s*'([^']+)'\s*\)/)?.[1]
      .split(',')
      .map((name) => name.trim());
    if (!projection?.length || projection.some((name) => !/^[a-z_]+$/.test(name)))
      throw new Error('unknown_capture_projection');
    revisions.set(revision, projection);
    return projection;
  }

  return (value: unknown) => {
    const row = object(value);
    const payload = object(row.heuristic_prediction);
    const context = object(payload.shadowContext);
    const revision = requiredString(payload.codeRevision);
    if (!/^[a-f0-9]{40}$/.test(revision)) throw new Error('invalid_code_revision');
    if (
      row.heuristic_prediction_status !== 'completed' ||
      row.source_system !== 'database_games' ||
      !row.source_game_id ||
      row.fixture_key !== `database:${row.source_game_id}` ||
      row.home_team_master_id === row.away_team_master_id ||
      row.heuristic_model_version !== modelVersion ||
      payload.modelVersion !== modelVersion ||
      context.predictorVersion !== modelVersion
    )
      throw new Error('invalid_frozen_fixture');
    const id = requiredString(row.id);
    const day = requiredString(row.game_date);
    const cutoff = Date.parse(day + 'T00:00:00Z');
    const capturedAt = requiredString(row.heuristic_predicted_at);
    const captured = Date.parse(capturedAt.replace(/([+-]\d{2})$/, '$1:00'));
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(day) ||
      !Number.isFinite(cutoff) ||
      new Date(cutoff).toISOString().slice(0, 10) !== day ||
      !Number.isFinite(captured) ||
      captured >= cutoff ||
      !/(Z|[+-]\d{2}(?::\d{2})?)$/.test(capturedAt)
    )
      throw new Error('invalid_pre_match_timestamp');
    const fixture = Object.fromEntries(
      fieldsAt(revision).map((name) => {
        if (!(name in row)) throw new Error('missing_fixture_member');
        return [name, row[name]];
      })
    );
    if (payload.inputHash !== digest({ fixture, context })) throw new Error('frozen_input_hash_mismatch');
    const calibration = object(context.calibration);
    if (['ageGroups', 'probability', 'margin', 'outcome', 'confidence'].some((name) => calibration[name] == null))
      throw new Error('missing_frozen_calibration');
    const signature = digest({ algorithm, calibration });
    if (payload.modelSignature !== signature || signature !== PINNED_SIGNATURE)
      throw new Error('baseline_model_signature_changed');
    const teamA = object(context.teamAInput);
    const teamB = object(context.teamBInput);
    const knownTeamIds = (team: RecordValue, aliases: unknown) => {
      if (aliases !== undefined && (!Array.isArray(aliases) || aliases.some((id) => typeof id !== 'string' || !id)))
        throw new Error('frozen_team_orientation_mismatch');
      return new Set([requiredString(team.team_id_master), ...((aliases ?? []) as string[])]);
    };
    const knownA = knownTeamIds(teamA, context.resolvedTeamAIds);
    const knownB = knownTeamIds(teamB, context.resolvedTeamBIds);
    if (
      !knownA.has(requiredString(row.home_team_master_id)) ||
      !knownB.has(requiredString(row.away_team_master_id)) ||
      [...knownA].some((id) => knownB.has(id))
    )
      throw new Error('frozen_team_orientation_mismatch');
    const source = object(object(row.fixture_payload).source_snapshot);
    if (source.game_date !== day) throw new Error('frozen_source_snapshot_mismatch');
    if (
      !knownA.has(requiredString(source.home_team_master_id)) ||
      !knownB.has(requiredString(source.away_team_master_id))
    )
      throw new Error('frozen_source_team_mapping_mismatch');
    const evidence = object(context.frozenEvidence);
    if (!Array.isArray(evidence.games) || !context.preOutcomeCalibration) throw new Error('incomplete_frozen_inputs');
    const prediction = object(object(payload.response).prediction);
    if (typeof prediction.expectedMargin !== 'number' || !Number.isFinite(prediction.expectedMargin))
      throw new Error('missing_frozen_prediction');
    return {
      id,
      source_game_id: row.source_game_id,
      row_sha256: digest(row),
      input_hash: payload.inputHash,
      predictor_revision: PINNED_REVISION,
      collecting_code_revision: revision,
      model_signature: signature,
      reference_time: new Date(captured).toISOString(),
      authority_verified: false,
    };
  };
}

async function main() {
  const [input, output] = process.argv.slice(2);
  if (!input || !output || process.argv.length !== 4)
    throw new Error('Usage: verify-compare-source.ts INPUT.json NEW_OUTPUT.json (use - for stdin/stdout)');
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const canonicalSource = await readFile(path.join(root, 'frontend/lib/canonicalJson.ts'), 'utf8');
  const cache = new Map<string, string>();
  const verify = sourceVerifier((revision, name) => {
    const key = revision + ':' + name;
    if (!cache.has(key))
      cache.set(
        key,
        (revision === 'workspace'
          ? canonicalSource
          : execFileSync('git', ['show', `${revision}:frontend/lib/${name}`], {
              cwd: root,
              encoding: 'utf8',
              windowsHide: true,
              timeout: 15000,
            })
        ).replace(/\r\n/g, '\n')
      );
    return cache.get(key)!;
  });
  let inputText: string;
  if (input === '-') {
    process.stdin.setEncoding('utf8');
    inputText = '';
    for await (const chunk of process.stdin) inputText += chunk;
  } else inputText = await readFile(input, 'utf8');
  const rows: unknown = JSON.parse(inputText);
  if (!Array.isArray(rows)) throw new Error('Expected an array of frozen ledger rows');
  const receipts = rows.map((row) => {
    try {
      return { verified: true, ...verify(row) };
    } catch (error) {
      return {
        verified: false,
        id: row && typeof row === 'object' ? ((row as RecordValue).id ?? null) : null,
        reason: error instanceof Error ? error.message : 'invalid_row',
      };
    }
  });
  const result = JSON.stringify({ schema_version: 1, receipts });
  if (output === '-') process.stdout.write(result);
  else await writeFile(output, result, { flag: 'wx' });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url))
  main().catch((error) => {
    process.stderr.write(String(error) + '\n');
    process.exitCode = 1;
  });
