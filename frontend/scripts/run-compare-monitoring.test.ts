// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { captureOptions, deploymentAwareFetch } from './run-compare-monitoring.mjs';

const endpoint = 'https://www.pitchrank.io/api/match-prediction';
const first = 'a'.repeat(40),
  second = 'b'.repeat(40);

describe('deployment-aware monitoring transport', () => {
  it('previews by default and validates limits and unknown flags before creating a client', () => {
    expect(captureOptions([])).toEqual({ limit: 500, execute: false });
    expect(captureOptions(['--limit', '1', '--execute'])).toEqual({ limit: 1, execute: true });
    for (const args of [['unexpected'], ['--limit'], ['--limit', '0'], ['--limit', '501'], ['--limit', '1.5']])
      expect(() => captureOptions(args)).toThrow('Use [--execute] [--limit 1..500]');
  });
  it('fetches a new deployment during a batch before the pinned verifier consumes its unchanged profile', async () => {
    const present = new Set([first]);
    const git = vi.fn((args: string[]) => {
      if (args[0] === 'fetch') present.add(args[3]);
      else if (!present.has(args[2].split('^')[0])) throw new Error('Missing revision');
    });
    const profiles = [first, second, second].map((deployment_revision) => ({
      deployment_revision,
      calibration: { ageGroups: {} },
      probes: [{ prediction: { winProbabilityA: 0.41 } }],
    }));
    const fetchRequest = vi.fn(async () => Response.json(profiles.shift()));
    const fetched = vi.fn();
    const run = deploymentAwareFetch(fetchRequest, git, fetched);
    for (const revision of [first, second, second]) {
      const response = await run(endpoint, { cache: 'no-store' });
      expect(present.has(revision)).toBe(true);
      expect(await response.json()).toEqual({
        deployment_revision: revision,
        calibration: { ageGroups: {} },
        probes: [{ prediction: { winProbabilityA: 0.41 } }],
      });
    }
    expect(git.mock.calls.filter(([args]) => args[0] === 'fetch')).toEqual([
      [['fetch', '--no-tags', 'origin', second]],
    ]);
    expect(fetched).toHaveBeenCalledTimes(1);
  });

  it('passes database traffic through without fetching code or altering request options', async () => {
    const response = Response.json({ data: true });
    const fetchRequest = vi.fn(async () => response),
      git = vi.fn();
    const run = deploymentAwareFetch(fetchRequest, git);
    const options = { method: 'POST', body: '{"p_baseline":"fixture"}' };
    expect(await run('https://example.supabase.co/rest/v1/rpc/freeze_compare_monitor', options)).toBe(response);
    expect(fetchRequest).toHaveBeenCalledWith(
      'https://example.supabase.co/rest/v1/rpc/freeze_compare_monitor',
      options
    );
    expect(git).not.toHaveBeenCalled();
  });

  it.each(['--upload-pack=bad', '../other', 'c'.repeat(39), 'C'.repeat(40)])(
    'leaves invalid revision %s to the pinned validator without passing it to git',
    async (deployment_revision) => {
      const git = vi.fn();
      const run = deploymentAwareFetch(async () => Response.json({ deployment_revision }), git);
      expect(await (await run(endpoint)).json()).toEqual({ deployment_revision });
      expect(git).not.toHaveBeenCalled();
    }
  );

  it('refuses to continue when fetching the required revision fails', async () => {
    const git = vi.fn(() => {
      throw new Error('Unavailable');
    });
    const run = deploymentAwareFetch(async () => Response.json({ deployment_revision: second }), git);
    await expect(run(endpoint)).rejects.toThrow('Unavailable');
    expect(git).toHaveBeenCalledTimes(2);
  });

  it('does not treat an unsuccessful metadata response as available source', async () => {
    const response = new Response('Unavailable', { status: 503 }),
      git = vi.fn();
    const run = deploymentAwareFetch(async () => response, git);
    expect(await run(endpoint)).toBe(response);
    expect(git).not.toHaveBeenCalled();
  });

  it('leaves oversized declared metadata to the pinned size guard before reading it', async () => {
    const response = new Response('not JSON', { headers: { 'content-length': '1000001' } });
    const clone = vi.spyOn(response, 'clone'),
      git = vi.fn();
    const run = deploymentAwareFetch(async () => response, git);
    expect(await run(endpoint)).toBe(response);
    expect(clone).not.toHaveBeenCalled();
    expect(git).not.toHaveBeenCalled();
  });

  it('does not parse or fetch code for oversized metadata without a length header', async () => {
    const response = new Response('x'.repeat(1000001)),
      git = vi.fn();
    const run = deploymentAwareFetch(async () => response, git);
    expect(await run(endpoint)).toBe(response);
    expect(git).not.toHaveBeenCalled();
  });
});
