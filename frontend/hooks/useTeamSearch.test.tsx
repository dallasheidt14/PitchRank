import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { useTeamSearch } from './useTeamSearch';

type HookResult = ReturnType<typeof useTeamSearch>;

const team = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  team_id_master: id,
  team_name: name,
  club_name: 'Rebels SC',
  age_group: 'u13',
  gender: 'Female',
  state_code: 'CA',
  state: 'California',
  league: null,
  distinction: null,
  is_ranked: true,
  ...extra,
});

interface Deferred {
  url: string;
  signal: AbortSignal | undefined;
  resolve: (body: unknown) => void;
  fail: (status: number) => void;
}

let pending: Deferred[] = [];
let latest: HookResult | null = null;
let root: Root | null = null;
let container: HTMLDivElement | null = null;
// Real fetch rejects once its signal aborts; switch off to model a response that resolved first.
let honourAbort = true;

function Probe({ query, limit, excludeId }: { query: string; limit: number; excludeId?: string | null }) {
  const result = useTeamSearch(query, { limit, excludeId });
  useEffect(() => {
    latest = result;
  });
  return null;
}

async function render(query: string, limit = 2, excludeId?: string | null) {
  await act(async () => {
    root!.render(React.createElement(Probe, { query, limit, excludeId }));
  });
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
}

async function settleDebounce() {
  await advance(250);
}

async function flush(step: () => void) {
  await act(async () => {
    step();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function respond(index: number, teams: unknown[], match = 'exact') {
  await flush(() => pending[index].resolve({ teams, match }));
}

async function fail(index: number, status: number) {
  await flush(() => pending[index].fail(status));
}

// Responses are cached for the page lifetime, so each test searches words no other test uses.
describe('useTeamSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    pending = [];
    latest = null;
    honourAbort = true;
    // Each call parks until the test resolves it, so responses can arrive in any order.
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (url: string, init?: { signal?: AbortSignal }) =>
          new Promise((resolve, reject) => {
            if (honourAbort) {
              init?.signal?.addEventListener('abort', () =>
                reject(new DOMException('The operation was aborted.', 'AbortError'))
              );
            }
            pending.push({
              url,
              signal: init?.signal,
              resolve: (body) => resolve({ ok: true, status: 200, json: async () => body }),
              fail: (status) => resolve({ ok: false, status, json: async () => ({ error: 'nope' }) }),
            });
          })
      )
    );
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      root?.unmount();
    });
    container?.remove();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('fetches the route once typing pauses and maps rows to RankingRow', async () => {
    await render('rebels u13 g');
    expect(fetch).not.toHaveBeenCalled();

    await settleDebounce();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(pending[0].url).toBe('/api/teams/search?q=rebels+u13+g&limit=3');
    expect(latest!.isLoading).toBe(true);

    await respond(0, [team('t1', 'Rebels SC 2014 Premier', { gender: 'Male', age_group: 'u18' })]);

    expect(latest!.isLoading).toBe(false);
    expect(latest!.results).toHaveLength(1);
    expect(latest!.results[0]).toMatchObject({
      team_id_master: 't1',
      team_name: 'Rebels SC 2014 Premier',
      club_name: 'Rebels SC',
      state: 'CA',
      age: 19,
      gender: 'M',
      rank_in_cohort_final: 0,
    });
  });

  it('maps a girls team to F', async () => {
    await render('rebels girls');
    await settleDebounce();
    await respond(0, [team('t1', 'Rebels SC 2014 Girls')]);

    expect(latest!.results[0].gender).toBe('F');
  });

  it('waits for typing to pause before fetching', async () => {
    await render('solar');
    await advance(150);
    expect(fetch).not.toHaveBeenCalled();

    await advance(100);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('drops the excluded team and still shows the full limit', async () => {
    await render('rebels', 2, 't2');
    await settleDebounce();
    await respond(0, [team('t1', 'A'), team('t2', 'B'), team('t3', 'C')]);

    expect(latest!.results.map((r) => r.team_id_master)).toEqual(['t1', 't3']);
  });

  it('trims the extra row the route sends when nothing is excluded', async () => {
    await render('rangers', 2);
    await settleDebounce();
    await respond(0, [team('t1', 'A'), team('t2', 'B'), team('t3', 'C')]);

    expect(latest!.results.map((r) => r.team_id_master)).toEqual(['t1', 't2']);
  });

  it("shows nothing from the last query while the next one loads, so Enter can't pick it", async () => {
    await render('dynamo');
    await settleDebounce();
    await respond(0, [team('t1', 'Dynamo')]);
    expect(latest!.results).toHaveLength(1);

    await render('dynamo u13');
    expect(latest!.results).toEqual([]);
    expect(latest!.isLoading).toBe(true);

    await settleDebounce();
    expect(latest!.results).toEqual([]);
    expect(latest!.isLoading).toBe(true);
  });

  it('clears the results when the query drops under two characters', async () => {
    await render('strikers');
    await settleDebounce();
    await respond(0, [team('t1', 'Strikers')]);

    await render('s');
    await settleDebounce();

    expect(latest!.results).toEqual([]);
    expect(latest!.isLoading).toBe(false);
  });

  it('aborts the request a newer query replaces', async () => {
    await render('rov');
    await settleDebounce();
    await render('rovers');
    await settleDebounce();

    expect(pending[0].signal!.aborted).toBe(true);
    expect(pending[1].signal!.aborted).toBe(false);
  });

  it('keeps the newest query when an older response arrives last', async () => {
    honourAbort = false;
    await render('rowdies');
    await settleDebounce();
    await render('rowdies fc');
    await settleDebounce();
    expect(pending).toHaveLength(2);

    await respond(1, [team('new', 'Rowdies FC')]);
    await respond(0, [team('old', 'Rowdies')]);

    expect(latest!.results.map((r) => r.team_id_master)).toEqual(['new']);
  });

  it('ignores an older request that fails after a newer one succeeded', async () => {
    honourAbort = false;
    await render('galaxy');
    await settleDebounce();
    await render('galaxy fc');
    await settleDebounce();

    await respond(1, [team('new', 'Galaxy FC')]);
    await fail(0, 429);

    expect(latest!.isError).toBe(false);
    expect(latest!.isLoading).toBe(false);
    expect(latest!.results.map((r) => r.team_id_master)).toEqual(['new']);
  });

  it('reports a failed search as an error, then fetches again on refetch', async () => {
    await render('surf sc');
    await settleDebounce();
    await fail(0, 429);

    expect(latest!.isError).toBe(true);
    expect(latest!.error!.message).toBe('Search failed (429)');
    expect(latest!.isLoading).toBe(false);
    expect(latest!.results).toEqual([]);

    await act(async () => {
      latest!.refetch();
    });
    expect(latest!.isLoading).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(2);

    await respond(1, [team('t1', 'Surf SC')]);

    expect(latest!.isError).toBe(false);
    expect(latest!.results.map((r) => r.team_id_master)).toEqual(['t1']);
  });

  it('reuses the response for a query typed again', async () => {
    await render('sporting');
    await settleDebounce();
    await respond(0, [team('t1', 'Sporting')]);
    await render('sporting kc');
    await settleDebounce();
    await respond(1, [team('t2', 'Sporting KC')]);

    await render('sporting');
    await settleDebounce();
    await flush(() => {});

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(latest!.results.map((r) => r.team_id_master)).toEqual(['t1']);
  });

  it('does not fetch under two characters', async () => {
    await render('r');
    await settleDebounce();

    expect(fetch).not.toHaveBeenCalled();
    expect(latest!.results).toEqual([]);
    expect(latest!.isLoading).toBe(false);
  });

  it('reports the match pass from the route', async () => {
    await render('rebles');
    await settleDebounce();
    await respond(0, [team('t1', 'Rebels')], 'similar');

    expect(latest!.match).toBe('similar');
  });
});
