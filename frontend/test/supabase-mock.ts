import { vi } from 'vitest';
import type { SupabaseClient } from '@supabase/supabase-js';

export type QueryResult = { data?: unknown; error?: unknown; count?: number | null };

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
  const chainable = [
    'select',
    'insert',
    'upsert',
    'update',
    'delete',
    'eq',
    'in',
    'is',
    'not',
    'or',
    'neq',
    'gte',
    'order',
    'limit',
  ];
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

export type MockRow = Record<string, unknown>;

const OR_TERM = /^([A-Za-z_][A-Za-z0-9_]*)\.eq\.([0-9a-fA-F-]+)$/;
const PLAIN_COLUMN = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** The columns a select names, or null when it asks for `*`, an embed or an alias. */
function plainColumns(selected: string | undefined): string[] | null {
  if (!selected) return null;
  const names = selected.split(',').map((name) => name.trim());
  return names.every((name) => PLAIN_COLUMN.test(name)) ? names : null;
}

/**
 * A Supabase client mock whose builder APPLIES the filters it is given.
 *
 * `queryBuilder` above replays a canned result, which suits a route that only
 * needs rows back. It is the wrong tool for a test guarding a filter: the guard
 * passes just as well once the filter is deleted. This builder models PostgREST
 * closely enough to refuse what PostgREST refuses — `.eq` and `.gte` drop NULL, `.is(col,
 * null)` keeps NULL and missing values, `.not(col, 'is', null)` drops them, `.or` honours the column each term names
 * rather than accepting a match on either side, `.single()` errors with PGRST116
 * unless exactly one row survives, and `.maybeSingle()` errors once more than one
 * does. That last one matters as much as the rest: a filter guard whose query ends
 * in `.maybeSingle()` would otherwise still pass with the filter deleted, because
 * the extra rows it lets through arrive as a silent `rows[0]`. A `.not()` operator,
 * `.or()` term or non-null `.is()` value this builder cannot model throws rather than passing silently.
 *
 * Rows are recorded per query, not per table, so a second query against the same
 * table is a visible change rather than one that silently retargets an assertion.
 *
 * `select(_, { count })` resolves a `count` of the surviving rows and `head: true` drops
 * `data`, as supabase-js does. PostgREST's exact count ignores `limit`/`range`, but this
 * one counts after them, so don't combine the two in a test.
 *
 * `.select('a, b')` answers only the columns a plain list names, a column a row lacks as
 * null, as PostgREST does; `*`, an embed or an alias passes whole rows.
 *
 * `.update(values)` changes the stored rows its filters leave, at the terminal call where
 * the real builder sends the request, so an update whose chain is never awaited changes
 * nothing. It answers the changed rows only when `.select()` follows, as supabase-js
 * does.
 *
 * `.insert(rows)` adds them at the terminal call too. Set `unique[table]` to a row's key under a
 * unique index (null for a row the index leaves out) and an insert whose key a stored row already
 * holds is refused with Postgres' 23505 and stores nothing, as the database refuses it.
 *
 * Set `failing[table]` to an error and every query against that table answers it, as PostgREST
 * answers PGRST205 for a table a migration has not created yet.
 */
export function filteringClientMock(initialRows: Record<string, MockRow[]> = {}) {
  const tableRows: Record<string, MockRow[]> = { ...initialRows };
  const queries: Array<{ table: string; rows: MockRow[] }> = [];
  const unique: Record<string, (row: MockRow) => string | null> = {};
  const failing: Record<string, { code: string; message: string }> = {};

  function createBuilder(table: string) {
    let rows: MockRow[] = [...(tableRows[table] ?? [])];
    let countRequested = false;
    let headOnly = false;
    let columns: string[] | null = null;
    let patch: MockRow | null = null;
    let inserting: MockRow[] | null = null;
    let returning = false;

    const insert = () => {
      const key = unique[table];
      const held = new Set((tableRows[table] ?? []).map((row) => key?.(row) ?? null).filter((k) => k !== null));
      if (
        key &&
        inserting!.some((row) => {
          const k = key(row);
          return k !== null && held.has(k);
        })
      ) {
        return { data: null, error: { code: '23505', message: 'duplicate key value violates unique constraint' } };
      }
      const added = inserting!.map((row) => ({ ...row }));
      tableRows[table] = [...(tableRows[table] ?? []), ...added];
      queries.push({ table, rows: added });
      return { data: returning ? added : null, error: null };
    };

    const record = () => {
      if (patch) for (const row of rows) Object.assign(row, patch);
      queries.push({ table, rows });
      if (patch && !returning) return null;
      return columns ? rows.map((row) => Object.fromEntries(columns!.map((c) => [c, c in row ? row[c] : null]))) : rows;
    };

    const builder = {
      select: (selected?: string, options?: { count?: string; head?: boolean }) => {
        countRequested = options?.count !== undefined;
        headOnly = options?.head === true;
        columns = plainColumns(selected);
        returning = patch !== null || inserting !== null;
        return builder;
      },
      update: (values: MockRow) => {
        patch = values;
        return builder;
      },
      insert: (values: MockRow | MockRow[]) => {
        inserting = Array.isArray(values) ? values : [values];
        return builder;
      },
      is: (field: string, value: null) => {
        if (value !== null) {
          throw new Error(`filteringClientMock does not model .is(${field}, ${String(value)})`);
        }
        rows = rows.filter((row) => row[field] === null || row[field] === undefined);
        return builder;
      },
      eq: (field: string, value: unknown) => {
        rows = rows.filter((row) => row[field] === value);
        return builder;
      },
      in: (field: string, values: readonly unknown[]) => {
        rows = rows.filter((row) => values.includes(row[field]));
        return builder;
      },
      gte: (field: string, value: string | number) => {
        rows = rows.filter(
          (row) => row[field] !== null && row[field] !== undefined && (row[field] as typeof value) >= value
        );
        return builder;
      },
      not: (field: string, operator: string, value: unknown) => {
        if (operator !== 'is' || value !== null) {
          throw new Error(`filteringClientMock does not model .not(${field}, ${operator}, ${String(value)})`);
        }
        rows = rows.filter((row) => row[field] !== null && row[field] !== undefined);
        return builder;
      },
      or: (conditions: string) => {
        const terms = conditions.split(',').map((term) => {
          const parsed = OR_TERM.exec(term);
          if (!parsed) {
            throw new Error(`filteringClientMock does not model .or() term ${JSON.stringify(term)}`);
          }
          return { column: parsed[1], value: parsed[2] };
        });
        rows = rows.filter((row) => terms.some((term) => row[term.column] === term.value));
        return builder;
      },
      order: (field: string, options?: { ascending?: boolean }) => {
        const direction = options?.ascending === false ? -1 : 1;
        rows = [...rows].sort((a, b) => String(a[field]).localeCompare(String(b[field])) * direction);
        return builder;
      },
      limit: (count: number) => {
        rows = rows.slice(0, count);
        return builder;
      },
      range: (from: number, to: number) => {
        rows = rows.slice(from, to + 1);
        return builder;
      },
      single: async () => {
        const found = record() ?? [];
        if (found.length !== 1) {
          return {
            data: null,
            error: { code: 'PGRST116', message: 'JSON object requested, multiple (or no) rows returned' },
            status: 406,
          };
        }
        return { data: found[0], error: null, status: 200 };
      },
      maybeSingle: async () => {
        const found = record() ?? [];
        if (found.length > 1) {
          return {
            data: null,
            error: { code: 'PGRST116', message: 'JSON object requested, multiple (or no) rows returned' },
            status: 406,
          };
        }
        return { data: found[0] ?? null, error: null, status: 200 };
      },
      then: (onFulfilled: (value: unknown) => unknown, onRejected?: (reason: unknown) => unknown) =>
        Promise.resolve(
          (() => {
            if (failing[table]) return { data: null, error: failing[table], count: null };
            if (inserting) return insert();
            const found = record();
            return { data: headOnly ? null : found, error: null, count: countRequested ? (found?.length ?? 0) : null };
          })()
        ).then(onFulfilled, onRejected),
    };

    return builder;
  }

  return {
    client: { from: (table: string) => createBuilder(table) } as unknown as SupabaseClient,
    tableRows,
    queries,
    unique,
    failing,
    /**
     * Every query run against `table`, in order, as the stored rows its filters matched: whole rows rather than
     * the selected columns, and shared with the table, so a later update shows in them.
     */
    queriesFor(table: string) {
      return queries.filter((query) => query.table === table).map((query) => query.rows);
    },
    reset() {
      queries.length = 0;
      for (const key of Object.keys(tableRows)) delete tableRows[key];
      for (const key of Object.keys(unique)) delete unique[key];
      for (const key of Object.keys(failing)) delete failing[key];
    },
  };
}
