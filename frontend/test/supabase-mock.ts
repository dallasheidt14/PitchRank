import { vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';

export type QueryResult = { data?: unknown; error?: unknown };

/**
 * A chainable Supabase query-builder mock.
 *
 * Filter/mutation methods (select, insert, eq, …) all return the same builder,
 * so a route can chain them in any order. The builder is awaitable (thenable)
 * and also exposes .single()/.maybeSingle(); all three resolve to the supplied
 * result. This mirrors how a real PostgREST builder is consumed — either by
 * awaiting the chain directly or by calling a row terminator.
 */
export function queryBuilder(result: QueryResult = { data: null, error: null }) {
  const builder: Record<string, unknown> = {};
  const resolved = Promise.resolve(result);
  const chainable = ['select', 'insert', 'upsert', 'update', 'delete', 'eq', 'in', 'is', 'neq', 'order', 'limit'];
  for (const method of chainable) {
    builder[method] = vi.fn(() => builder);
  }
  builder.single = vi.fn(() => resolved);
  builder.maybeSingle = vi.fn(() => resolved);
  builder.then = (onFulfilled: (v: unknown) => unknown, onRejected?: (e: unknown) => unknown) =>
    resolved.then(onFulfilled, onRejected);
  return builder;
}

/**
 * A service-role Supabase client mock for admin route handlers.
 *
 * `.from(table)` returns the next queued result for that table (FIFO), and
 * `.rpc(name)` returns the next queued RPC result. Both default to an empty
 * success when nothing is queued. Queue results per test with
 * queueFrom()/queueRpc(); assert interactions on the exposed `from`/`rpc` spies.
 */
export function serviceClientMock() {
  const fromQueues: Record<string, QueryResult[]> = {};
  const rpcQueue: QueryResult[] = [];

  const from = vi.fn((table: string) =>
    queryBuilder((fromQueues[table] ??= []).shift() ?? { data: null, error: null })
  );
  const rpc = vi.fn(() => Promise.resolve(rpcQueue.shift() ?? { data: null, error: null }));

  return {
    client: { from, rpc } as unknown as SupabaseClient,
    from,
    rpc,
    queueFrom(table: string, ...results: QueryResult[]) {
      (fromQueues[table] ??= []).push(...results);
    },
    queueRpc(...results: QueryResult[]) {
      rpcQueue.push(...results);
    },
  };
}
