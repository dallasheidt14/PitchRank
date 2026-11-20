/** Operational launcher. Keep the registered collector and its formula checkout unchanged. */
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const RUNTIME_URL = 'https://www.pitchrank.io/api/match-prediction';

export function deploymentAwareFetch(fetchRequest, git, onFetched = () => {}) {
  const available = new Set();
  return async (input, options) => {
    const response = await fetchRequest(input, options);
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (url !== RUNTIME_URL || !response.ok) return response;
    if (Number(response.headers.get('content-length') ?? 0) > 1000000) return response;
    const body = await response.clone().text();
    if (body.length > 1000000) return response;
    const profile = JSON.parse(body);
    const revision = profile?.deployment_revision;
    // The pinned runtime still validates freshness, predictor version, inputs,
    // calibration and source hashes. This supplies only a missing Git object.
    if (typeof revision !== 'string' || !/^[a-f0-9]{40}$/.test(revision) || available.has(revision)) return response;
    try {
      git(['cat-file', '-e', `${revision}^{commit}`]);
    } catch {
      git(['fetch', '--no-tags', 'origin', revision]);
      git(['cat-file', '-e', `${revision}^{commit}`]);
      onFetched();
    }
    available.add(revision);
    return response;
  };
}

export function captureOptions(args) {
  const limitIndex = args.indexOf('--limit');
  const limit = limitIndex < 0 ? 500 : Number(args[limitIndex + 1]);
  if (
    !Number.isInteger(limit) ||
    limit < 1 ||
    limit > 500 ||
    args.some(
      (arg, index) => arg !== '--execute' && arg !== '--limit' && !(limitIndex >= 0 && index === limitIndex + 1)
    )
  )
    throw new Error('Use [--execute] [--limit 1..500]');
  return { limit, execute: args.includes('--execute') };
}

export async function main(args = process.argv.slice(2)) {
  const options = captureOptions(args);
  const root = process.cwd();
  if (path.basename(root) !== 'frontend') throw new Error('Run from the registered frontend checkout');
  const requireSource = createRequire(path.join(root, 'package.json'));
  const { createClient } = requireSource('@supabase/supabase-js');
  const { captureMonitoring } = requireSource(path.join(root, 'scripts/capture-compare-monitoring.ts'));
  const url = process.env.SUPABASE_URL,
    key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) throw new Error('Configure server credentials');
  const originalFetch = globalThis.fetch;
  let fetched = 0;
  globalThis.fetch = deploymentAwareFetch(
    originalFetch,
    (gitArgs) =>
      execFileSync('git', gitArgs, {
        cwd: root,
        windowsHide: true,
        timeout: 30000,
        stdio: ['ignore', 'pipe', 'pipe'],
      }),
    () => {
      fetched++;
    }
  );
  try {
    const client = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
    const summary = await captureMonitoring(client, options);
    console.log(JSON.stringify({ ...summary, deploymentRevisionsFetched: fetched }));
    if (summary.errors) process.exitCode = 1;
  } finally {
    globalThis.fetch = originalFetch;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href)
  main().catch(() => {
    console.error('Compare monitoring failed; existing captures remain saved.');
    process.exitCode = 1;
  });
