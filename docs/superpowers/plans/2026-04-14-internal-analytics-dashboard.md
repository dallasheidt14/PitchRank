# Internal Analytics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an admin-only analytics dashboard at `/analytics` (route group `(internal)`) inside the PitchRank Next.js frontend that shows GA4 + GSC tiles and offers a Claude-powered chat sidebar that queries the same canonical report handlers.

**Architecture:** Next.js App Router with Server Component shell + Client Component tiles/chat. Shared report registry in `lib/internal-analytics/` is the single source of truth — both tile API routes and chat tools call it. Caching via `unstable_cache` with tag-based invalidation. Chat uses Vercel AI SDK with Claude Sonnet 4.6, streaming, with three constrained tools (`run_named_report`, `query_ga4`, `query_gsc`).

**Tech Stack:** Next.js 16, React 19, TypeScript 5.9, Tailwind v4, shadcn/ui, Recharts 3.4, TanStack React Query 5.90, googleapis 171.4 (existing `lib/google-auth.ts`), Supabase SSR, Vitest 4, Playwright 1.58, Vercel AI SDK (to be installed: `ai` + `@ai-sdk/anthropic`).

**Spec:** `docs/superpowers/2026-04-14-pitchrank-analytics-dashboard-design.md`

---

## Divergences from the spec (resolved during pre-plan exploration)

The spec was written before exploring the existing PitchRank codebase. The following divergences are intentional and locked in by this plan:

1. **Library directory:** `lib/internal-analytics/` (not `lib/analytics/`) — avoids collision with existing `lib/analytics.ts` (client-side gtag helpers).
2. **Admin gating:** Reuse existing `requireAdmin()` in `lib/supabase/admin.ts` (DB-backed via `user_profiles.plan = 'admin'`) instead of new `ADMIN_EMAILS` env var. Existing pattern is already battle-tested and matches `/mission-control`. Non-admin behavior follows existing pattern: redirect to `/` (not 404).
3. **Google clients:** Reuse existing `lib/google-auth.ts` exports (`getAnalyticsDataClient()`, `getSearchConsoleClient()`) — already memoized with JWT auth from `GOOGLE_SERVICE_ACCOUNT_JSON`. No new `google-clients.ts`.
4. **Middleware:** Extend existing `frontend/middleware.ts` `ADMIN_ROUTES` array to include `/analytics` rather than writing a new middleware.
5. **GA4 SDK:** Use `googleapis` (already installed) via `getAnalyticsDataClient()`, NOT `@google-analytics/data`. Saves a dependency and matches the existing pattern.
6. **Constants:** GA4 property ID `514724174` and GSC site `sc-domain:pitchrank.io` go in `lib/internal-analytics/constants.ts` — do NOT confuse with the existing client-side `NEXT_PUBLIC_GA_MEASUREMENT_ID=G-7G1698GM92` (gtag tag, different thing).
7. **Route group:** `(internal)` resolves to `/`, so the page lives at `/analytics`. Middleware must gate `/analytics` (not `/(internal)/analytics`).

---

## File structure (final, after reconciling with existing code)

```
frontend/
├── middleware.ts                                       # MODIFY (extend ADMIN_ROUTES)
├── package.json                                        # MODIFY (add ai, @ai-sdk/anthropic)
├── lib/
│   └── internal-analytics/
│       ├── types.ts                                    # NEW
│       ├── constants.ts                                # NEW
│       ├── dates.ts                                    # NEW
│       ├── logging.ts                                  # NEW
│       ├── report-registry.ts                          # NEW
│       ├── transforms/
│       │   ├── ga4.ts                                  # NEW
│       │   ├── gsc.ts                                  # NEW
│       │   └── trend.ts                                # NEW
│       ├── queries/
│       │   ├── _coalesce.ts                            # NEW
│       │   ├── _error.ts                               # NEW
│       │   ├── ga4-overview.ts                         # NEW
│       │   ├── ga4-top-pages.ts                        # NEW
│       │   ├── ga4-upgrade-views.ts                    # NEW
│       │   ├── gsc-performance.ts                      # NEW
│       │   ├── gsc-top-queries.ts                      # NEW
│       │   └── gsc-landing-pages.ts                    # NEW
│       └── chat/
│           ├── tools.ts                                # NEW
│           └── system-prompt.ts                        # NEW
├── app/
│   ├── (internal)/
│   │   └── analytics/
│   │       ├── layout.tsx                              # NEW (server, requireAdmin gate)
│   │       ├── page.tsx                                # NEW (renders DashboardGrid + ChatSidebar)
│   │       └── components/
│   │           ├── DateRangePicker.tsx                 # NEW
│   │           ├── DashboardGrid.tsx                   # NEW
│   │           ├── tiles/
│   │           │   ├── TileShell.tsx                   # NEW (loading/empty/error states)
│   │           │   ├── TrafficOverviewTile.tsx         # NEW
│   │           │   ├── TopPagesTile.tsx                # NEW
│   │           │   ├── UpgradeViewsTile.tsx            # NEW
│   │           │   ├── SearchPerformanceTile.tsx       # NEW
│   │           │   ├── TopQueriesTile.tsx              # NEW
│   │           │   └── LandingPagesTile.tsx            # NEW
│   │           └── chat/
│   │               ├── ChatSidebar.tsx                 # NEW
│   │               └── DateContextChip.tsx             # NEW
│   └── api/
│       └── internal/
│           └── analytics/
│               ├── meta/route.ts                       # NEW
│               ├── refresh/route.ts                    # NEW
│               ├── ga4/
│               │   ├── overview/route.ts               # NEW
│               │   ├── top-pages/route.ts              # NEW
│               │   └── upgrade-views/route.ts          # NEW
│               ├── gsc/
│               │   ├── performance/route.ts            # NEW
│               │   ├── top-queries/route.ts            # NEW
│               │   └── landing-pages/route.ts          # NEW
│               └── chat/route.ts                       # NEW
└── supabase/
    └── migrations/
        └── 004_analytics_chat_logs.sql                 # NEW
```

---

# Phase 1 — Scaffolding

Goal: deployable empty page behind admin gate, with foundational utilities and the chat-logs table in place.

## Task 1.1 — Install dependencies and confirm baseline

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install Vercel AI SDK packages**

```bash
cd C:/PitchRank/frontend && npm install ai @ai-sdk/anthropic
```

Expected: both packages added to `dependencies`, no peer-dep warnings for React 19 / Next 16.

- [ ] **Step 2: Verify Vitest and Playwright still work**

```bash
cd C:/PitchRank/frontend && npx vitest --version && npx playwright --version
```

Expected: vitest reports 4.x, playwright reports 1.58.x.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank/frontend && git add package.json package-lock.json && git commit -m "chore: add Vercel AI SDK for analytics chat"
```

---

## Task 1.2 — Add types, constants, dates utility (TDD)

**Files:**
- Create: `frontend/lib/internal-analytics/types.ts`
- Create: `frontend/lib/internal-analytics/constants.ts`
- Create: `frontend/lib/internal-analytics/dates.ts`
- Test: `frontend/lib/internal-analytics/__tests__/dates.test.ts`

- [ ] **Step 1: Create `types.ts`**

```ts
// frontend/lib/internal-analytics/types.ts

export type DateRangePreset = "today" | "last_7_days" | "last_28_days" | "mtd";

export type DateRange = {
  start: string;        // ISO date YYYY-MM-DD, inclusive
  end: string;          // ISO date YYYY-MM-DD, inclusive
  preset?: DateRangePreset;
};

export type DataFreshness = "complete" | "partial";

export type TileResponse<Row> = {
  report?: string;
  source: "ga4" | "gsc";
  date_range: DateRange;
  timezone: string;
  rows: Row[];
  row_count: number;
  totals: Record<string, number>;
  derived: Record<string, number | string>;
  previous_period?: {
    rows: Row[];
    totals: Record<string, number>;
    derived: Record<string, number | string>;
  };
  truncated: boolean;
  truncation_reason?: "limit_reached" | "api_max" | "post_filter";
  available_rows_hint?: number;
  data_freshness: DataFreshness;
  warnings: string[];
  generated_at: string;     // ISO 8601
  debug?: {
    cost: {
      estimated_units: number;
      range_days: number;
      metric_count: number;
      dimension_count: number;
      limit: number;
    };
  };
};

export type TaxonomyError = {
  type: "VALIDATION" | "RATE_LIMIT" | "API_ERROR" | "NO_DATA" | "AUTH" | "QUOTA";
  message: string;
  retryable: boolean;
  retry_after_ms?: number;
};
```

- [ ] **Step 2: Create `constants.ts`**

```ts
// frontend/lib/internal-analytics/constants.ts

export const GA4_PROPERTY_ID = "514724174";
export const GSC_SITE_URL = "sc-domain:pitchrank.io";

export const DEFAULT_ROW_LIMIT = 10;
export const MAX_ROW_LIMIT = 100;

export const DATE_RANGE_PRESETS = ["today", "last_7_days", "last_28_days", "mtd"] as const;
export const DEFAULT_PRESET: (typeof DATE_RANGE_PRESETS)[number] = "last_7_days";

export const ALLOWED_GA4_METRICS = [
  "activeUsers",
  "sessions",
  "screenPageViews",
  "engagementRate",
  "averageSessionDuration",
  "bounceRate",
  "eventCount",
] as const;

export const ALLOWED_GA4_DIMENSIONS = [
  "date",
  "pagePath",
  "pageTitle",
  "country",
  "deviceCategory",
  "sessionSource",
  "sessionMedium",
  "eventName",
] as const;

export const ALLOWED_GSC_METRICS = ["clicks", "impressions", "ctr", "position"] as const;
export const ALLOWED_GSC_DIMENSIONS = ["date", "query", "page", "country", "device"] as const;

export const CACHE_TTL_SECONDS = 600;     // 10 min
export const REACT_QUERY_STALE_MS = 5 * 60 * 1000;
export const REACT_QUERY_GC_MS = 15 * 60 * 1000;
```

- [ ] **Step 3: Write failing test for `dates.ts`**

```ts
// frontend/lib/internal-analytics/__tests__/dates.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  resolveDateRange,
  previousPeriod,
  detectFreshness,
  rangeDays,
  todayInPropertyTz,
} from "../dates";

describe("resolveDateRange", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Phoenix is UTC-7, so 2026-04-14 12:00 UTC = 2026-04-14 05:00 Phoenix
    vi.setSystemTime(new Date("2026-04-14T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("resolves 'today' to a single-day range in property timezone", () => {
    const r = resolveDateRange("today", "America/Phoenix");
    expect(r).toEqual({ start: "2026-04-14", end: "2026-04-14", preset: "today" });
  });

  it("resolves 'last_7_days' as the prior 7 days ending yesterday", () => {
    const r = resolveDateRange("last_7_days", "America/Phoenix");
    expect(r).toEqual({ start: "2026-04-07", end: "2026-04-13", preset: "last_7_days" });
  });

  it("resolves 'last_28_days' as the prior 28 days ending yesterday", () => {
    const r = resolveDateRange("last_28_days", "America/Phoenix");
    expect(r).toEqual({ start: "2026-03-17", end: "2026-04-13", preset: "last_28_days" });
  });

  it("resolves 'mtd' from the 1st through today", () => {
    const r = resolveDateRange("mtd", "America/Phoenix");
    expect(r).toEqual({ start: "2026-04-01", end: "2026-04-14", preset: "mtd" });
  });

  it("passes through explicit ranges unchanged", () => {
    const r = resolveDateRange({ start: "2026-01-01", end: "2026-01-31" }, "America/Phoenix");
    expect(r).toEqual({ start: "2026-01-01", end: "2026-01-31" });
  });
});

describe("previousPeriod", () => {
  it("returns the prior window of equal length immediately preceding", () => {
    expect(previousPeriod({ start: "2026-04-07", end: "2026-04-13" })).toEqual({
      start: "2026-03-31",
      end: "2026-04-06",
    });
  });
});

describe("rangeDays", () => {
  it("counts days inclusively", () => {
    expect(rangeDays({ start: "2026-04-07", end: "2026-04-13" })).toBe(7);
    expect(rangeDays({ start: "2026-04-14", end: "2026-04-14" })).toBe(1);
  });
});

describe("detectFreshness", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-14T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("flags GSC ranges within 2 days of today as partial", () => {
    const f = detectFreshness("gsc", { start: "2026-04-07", end: "2026-04-13" }, "America/Phoenix");
    expect(f.freshness).toBe("partial");
    expect(f.warnings[0]).toContain("GSC data has a 2-3 day lag");
  });

  it("marks GA4 ranges ending today as partial", () => {
    const f = detectFreshness("ga4", { start: "2026-04-14", end: "2026-04-14" }, "America/Phoenix");
    expect(f.freshness).toBe("partial");
  });

  it("marks complete when end date is well-aged", () => {
    const f = detectFreshness("gsc", { start: "2026-03-01", end: "2026-04-10" }, "America/Phoenix");
    expect(f.freshness).toBe("complete");
    expect(f.warnings).toEqual([]);
  });
});

describe("todayInPropertyTz", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-14T01:30:00Z"));   // 2026-04-13 18:30 Phoenix
  });
  afterEach(() => vi.useRealTimers());

  it("returns yesterday in UTC when Phoenix is still on the prior date", () => {
    expect(todayInPropertyTz("America/Phoenix")).toBe("2026-04-13");
  });
});
```

- [ ] **Step 4: Run test, expect failures**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/__tests__/dates.test.ts
```

Expected: all tests fail with "module not found" for `../dates`.

- [ ] **Step 5: Implement `dates.ts`**

```ts
// frontend/lib/internal-analytics/dates.ts
import type { DateRange, DateRangePreset, DataFreshness } from "./types";

const ISO = (d: Date): string => d.toISOString().slice(0, 10);

function dateInTz(date: Date, timeZone: string): string {
  // en-CA gives YYYY-MM-DD format
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(date);
}

export function todayInPropertyTz(timeZone: string): string {
  return dateInTz(new Date(), timeZone);
}

function addDaysISO(iso: string, delta: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + delta);
  return ISO(dt);
}

function startOfMonthISO(iso: string): string {
  return iso.slice(0, 8) + "01";
}

export function resolveDateRange(
  input: DateRangePreset | DateRange,
  timeZone: string,
): DateRange {
  if (typeof input === "object") return { start: input.start, end: input.end };

  const today = todayInPropertyTz(timeZone);
  const yesterday = addDaysISO(today, -1);

  switch (input) {
    case "today":
      return { start: today, end: today, preset: "today" };
    case "last_7_days":
      return { start: addDaysISO(yesterday, -6), end: yesterday, preset: "last_7_days" };
    case "last_28_days":
      return { start: addDaysISO(yesterday, -27), end: yesterday, preset: "last_28_days" };
    case "mtd":
      return { start: startOfMonthISO(today), end: today, preset: "mtd" };
  }
}

export function rangeDays(r: DateRange): number {
  const [y1, m1, d1] = r.start.split("-").map(Number);
  const [y2, m2, d2] = r.end.split("-").map(Number);
  const a = Date.UTC(y1, m1 - 1, d1);
  const b = Date.UTC(y2, m2 - 1, d2);
  return Math.round((b - a) / 86_400_000) + 1;
}

export function previousPeriod(r: DateRange): DateRange {
  const days = rangeDays(r);
  return {
    start: addDaysISO(r.start, -days),
    end: addDaysISO(r.start, -1),
  };
}

export function detectFreshness(
  source: "ga4" | "gsc",
  range: DateRange,
  timeZone: string,
): { freshness: DataFreshness; warnings: string[] } {
  const today = todayInPropertyTz(timeZone);
  if (source === "gsc") {
    const cutoff = addDaysISO(today, -2);
    if (range.end >= cutoff) {
      return {
        freshness: "partial",
        warnings: [`GSC data has a 2-3 day lag; results through ${range.end} are incomplete.`],
      };
    }
  }
  if (source === "ga4" && range.end >= today) {
    return {
      freshness: "partial",
      warnings: ["GA4 data for today is still being collected."],
    };
  }
  return { freshness: "complete", warnings: [] };
}
```

- [ ] **Step 6: Run tests, expect all pass**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/__tests__/dates.test.ts
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
cd C:/PitchRank/frontend && git add lib/internal-analytics/ && git commit -m "feat(analytics): add internal-analytics types, constants, and date utilities"
```

---

## Task 1.3 — Add error taxonomy module (TDD)

**Files:**
- Create: `frontend/lib/internal-analytics/queries/_error.ts`
- Test: `frontend/lib/internal-analytics/queries/__tests__/_error.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// frontend/lib/internal-analytics/queries/__tests__/_error.test.ts
import { describe, it, expect } from "vitest";
import { toTaxonomyError } from "../_error";

describe("toTaxonomyError", () => {
  it("maps 429 to RATE_LIMIT (retryable)", () => {
    const err = { code: 429, message: "Too many", response: { headers: { "retry-after": "30" } } };
    const t = toTaxonomyError(err);
    expect(t.type).toBe("RATE_LIMIT");
    expect(t.retryable).toBe(true);
    expect(t.retry_after_ms).toBe(30_000);
  });

  it("maps 403 to AUTH (not retryable)", () => {
    const t = toTaxonomyError({ code: 403, message: "Forbidden" });
    expect(t.type).toBe("AUTH");
    expect(t.retryable).toBe(false);
  });

  it("maps 400 to VALIDATION with the original message", () => {
    const t = toTaxonomyError({ code: 400, message: "Invalid metric" });
    expect(t.type).toBe("VALIDATION");
    expect(t.message).toContain("Invalid metric");
    expect(t.retryable).toBe(false);
  });

  it("maps unknown errors to API_ERROR (retryable)", () => {
    const t = toTaxonomyError({ code: 500, message: "boom" });
    expect(t.type).toBe("API_ERROR");
    expect(t.retryable).toBe(true);
  });

  it("handles non-object errors as API_ERROR (not retryable)", () => {
    const t = toTaxonomyError("string error");
    expect(t.type).toBe("API_ERROR");
    expect(t.retryable).toBe(false);
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/queries/__tests__/_error.test.ts
```

Expected: module-not-found.

- [ ] **Step 3: Implement `_error.ts`**

```ts
// frontend/lib/internal-analytics/queries/_error.ts
import type { TaxonomyError } from "../types";

type GoogleLikeError = {
  code?: number;
  message?: string;
  response?: { headers?: Record<string, string> };
};

function isGoogleLikeError(e: unknown): e is GoogleLikeError {
  return typeof e === "object" && e !== null && "code" in e;
}

export function toTaxonomyError(err: unknown): TaxonomyError {
  if (!isGoogleLikeError(err)) {
    return {
      type: "API_ERROR",
      message: typeof err === "string" ? err : "Unknown error",
      retryable: false,
    };
  }

  const message = err.message ?? "Unknown error";
  switch (err.code) {
    case 429: {
      const retryAfter = err.response?.headers?.["retry-after"];
      const ms = retryAfter ? Number(retryAfter) * 1000 : undefined;
      return { type: "RATE_LIMIT", message, retryable: true, retry_after_ms: ms };
    }
    case 403:
      return { type: "AUTH", message, retryable: false };
    case 400:
      return { type: "VALIDATION", message, retryable: false };
    default:
      return { type: "API_ERROR", message, retryable: true };
  }
}

export class TaxonomyAwareError extends Error {
  constructor(public readonly taxonomy: TaxonomyError) {
    super(taxonomy.message);
    this.name = "TaxonomyAwareError";
  }
}
```

- [ ] **Step 4: Run tests, expect green**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/queries/__tests__/_error.test.ts
```

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank/frontend && git add lib/internal-analytics/queries/ && git commit -m "feat(analytics): add error taxonomy mapper"
```

---

## Task 1.4 — Add Supabase migration and chat-log helper

**Files:**
- Create: `frontend/supabase/migrations/004_analytics_chat_logs.sql`
- Create: `frontend/lib/internal-analytics/logging.ts`

- [ ] **Step 1: Write the migration**

```sql
-- frontend/supabase/migrations/004_analytics_chat_logs.sql
create table if not exists public.analytics_chat_logs (
  id            bigserial primary key,
  created_at    timestamptz not null default now(),
  turn_id       uuid not null,
  user_email    text not null,
  model_name    text not null,
  user_question text not null,
  inherited_date_range jsonb,
  overridden_date_range jsonb,
  tool_name     text not null,
  tool_args     jsonb not null,
  tool_result_summary jsonb,
  tool_call_hash text not null,
  force_fresh   boolean not null default false,
  cost_units    integer,
  execution_ms  integer,
  success       boolean not null,
  error_type    text,
  error_message text,
  final_answer  text
);

create index if not exists analytics_chat_logs_created_at_idx
  on public.analytics_chat_logs (created_at desc);

create index if not exists analytics_chat_logs_user_email_idx
  on public.analytics_chat_logs (user_email);

create index if not exists analytics_chat_logs_turn_id_idx
  on public.analytics_chat_logs (turn_id);

-- No RLS policies: this table is server-write only via service role.
alter table public.analytics_chat_logs enable row level security;
-- Deny all default policies = no client access via anon key.
```

- [ ] **Step 2: Apply the migration**

Apply via the Supabase MCP tool or supabase CLI:

```bash
cd C:/PitchRank/frontend && supabase db push
```

Or, if using the Supabase MCP server, call `apply_migration` with the SQL above and migration name `004_analytics_chat_logs`.

Expected: migration applied; verify by listing tables.

- [ ] **Step 3: Implement logging helper**

```ts
// frontend/lib/internal-analytics/logging.ts
import "server-only";
import { createClient } from "@supabase/supabase-js";
import { createHash, randomUUID } from "node:crypto";
import type { TaxonomyError } from "./types";

let _adminClient: ReturnType<typeof createClient> | null = null;

function adminClient() {
  if (_adminClient) return _adminClient;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) throw new Error("Supabase admin client env vars missing");
  _adminClient = createClient(url, key, { auth: { persistSession: false } });
  return _adminClient;
}

export function newTurnId(): string {
  return randomUUID();
}

export function hashToolCall(toolName: string, args: unknown): string {
  const normalized = JSON.stringify(args, Object.keys(args ?? {}).sort());
  return createHash("sha256").update(`${toolName}:${normalized}`).digest("hex");
}

export type ChatToolLogInput = {
  turn_id: string;
  user_email: string;
  model_name: string;
  user_question: string;
  inherited_date_range: unknown;
  overridden_date_range: unknown;
  tool_name: string;
  tool_args: unknown;
  tool_result_summary: unknown;
  force_fresh: boolean;
  cost_units?: number | null;
  execution_ms: number;
  success: boolean;
  error?: TaxonomyError | null;
  final_answer?: string | null;
};

export async function logChatToolCall(input: ChatToolLogInput): Promise<void> {
  const row = {
    turn_id: input.turn_id,
    user_email: input.user_email,
    model_name: input.model_name,
    user_question: input.user_question,
    inherited_date_range: input.inherited_date_range,
    overridden_date_range: input.overridden_date_range,
    tool_name: input.tool_name,
    tool_args: input.tool_args,
    tool_result_summary: input.tool_result_summary,
    tool_call_hash: hashToolCall(input.tool_name, input.tool_args),
    force_fresh: input.force_fresh,
    cost_units: input.cost_units ?? null,
    execution_ms: input.execution_ms,
    success: input.success,
    error_type: input.error?.type ?? null,
    error_message: input.error?.message ?? null,
    final_answer: input.final_answer ?? null,
  };

  const { error } = await adminClient().from("analytics_chat_logs").insert(row);
  if (error) console.error("[analytics] chat-log insert failed:", error.message);
}
```

- [ ] **Step 4: Verify the file compiles**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json
```

Expected: no new errors related to `lib/internal-analytics/logging.ts`.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank/frontend && git add supabase/migrations/004_analytics_chat_logs.sql lib/internal-analytics/logging.ts && git commit -m "feat(analytics): add chat-logs migration and logging helper"
```

---

## Task 1.5 — Extend middleware, add empty `/analytics` page behind admin gate

**Files:**
- Modify: `frontend/middleware.ts`
- Create: `frontend/app/(internal)/analytics/layout.tsx`
- Create: `frontend/app/(internal)/analytics/page.tsx`

- [ ] **Step 1: Extend middleware `ADMIN_ROUTES`**

In `frontend/middleware.ts`, change:

```ts
const ADMIN_ROUTES = ['/mission-control'];
```

to:

```ts
const ADMIN_ROUTES = ['/mission-control', '/analytics'];
```

No other changes; the existing admin-gating logic already handles this list.

- [ ] **Step 2: Create the layout (server, requireAdmin)**

```tsx
// frontend/app/(internal)/analytics/layout.tsx
import { redirect } from "next/navigation";
import { createServerSupabase } from "@/lib/supabase/server";
import type { ReactNode } from "react";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function AnalyticsLayout({ children }: { children: ReactNode }) {
  const supabase = await createServerSupabase();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/analytics");

  const { data: profile } = await supabase
    .from("user_profiles")
    .select("plan")
    .eq("id", user.id)
    .single();

  if (!profile || profile.plan !== "admin") redirect("/");

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-6">{children}</div>
    </div>
  );
}
```

- [ ] **Step 3: Create empty `page.tsx` placeholder**

```tsx
// frontend/app/(internal)/analytics/page.tsx
export default function AnalyticsPage() {
  return (
    <main>
      <h1 className="text-2xl font-semibold">Internal Analytics</h1>
      <p className="text-muted-foreground mt-2">Dashboard scaffolding in progress.</p>
    </main>
  );
}
```

- [ ] **Step 4: Smoke test locally**

```bash
cd C:/PitchRank/frontend && npm run dev
```

In a browser:
1. Visit `http://localhost:3000/analytics` while logged out → expect redirect to `/login?next=/analytics`.
2. Log in as a non-admin → visit `/analytics` → expect redirect to `/`.
3. Log in as an admin → visit `/analytics` → expect placeholder page to render.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank/frontend && git add middleware.ts app/\(internal\)/analytics/ && git commit -m "feat(analytics): add /analytics route group with admin gate"
```

---

# Phase 2 — Data layer

Goal: every report function callable, returning the uniform `TileResponse` shape, with caching, coalescing, and unit tests on transforms.

## Task 2.1 — Trend computation (TDD)

**Files:**
- Create: `frontend/lib/internal-analytics/transforms/trend.ts`
- Test: `frontend/lib/internal-analytics/transforms/__tests__/trend.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// frontend/lib/internal-analytics/transforms/__tests__/trend.test.ts
import { describe, it, expect } from "vitest";
import { computeTrend, pctDelta } from "../trend";

describe("computeTrend", () => {
  it("reports up for monotonically increasing series", () => {
    const t = computeTrend([1, 2, 3, 4, 5]);
    expect(t.trend_direction).toBe("up");
    expect(t.trend_strength).toBeGreaterThan(0);
  });

  it("reports down for monotonically decreasing series", () => {
    const t = computeTrend([5, 4, 3, 2, 1]);
    expect(t.trend_direction).toBe("down");
  });

  it("reports flat for noise around constant", () => {
    const t = computeTrend([10, 10, 10, 10, 10]);
    expect(t.trend_direction).toBe("flat");
    expect(t.trend_strength).toBe(0);
  });

  it("returns flat for empty or single-point series", () => {
    expect(computeTrend([]).trend_direction).toBe("flat");
    expect(computeTrend([42]).trend_direction).toBe("flat");
  });
});

describe("pctDelta", () => {
  it("returns positive percent for growth", () => {
    expect(pctDelta(120, 100)).toBeCloseTo(0.2);
  });
  it("returns 0 when previous is 0 and current is 0", () => {
    expect(pctDelta(0, 0)).toBe(0);
  });
  it("returns Infinity-safe value when previous is 0 and current is positive", () => {
    expect(pctDelta(5, 0)).toBe(1);   // saturate at +100% to avoid Infinity
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/transforms/__tests__/trend.test.ts
```

- [ ] **Step 3: Implement `trend.ts`**

```ts
// frontend/lib/internal-analytics/transforms/trend.ts
const FLAT_THRESHOLD = 0.05;   // |normalized_slope| below this = flat

export function computeTrend(series: number[]): {
  trend_direction: "up" | "down" | "flat";
  trend_strength: number;
} {
  if (series.length < 2) return { trend_direction: "flat", trend_strength: 0 };

  const n = series.length;
  const xs = Array.from({ length: n }, (_, i) => i);
  const meanX = xs.reduce((a, b) => a + b, 0) / n;
  const meanY = series.reduce((a, b) => a + b, 0) / n;

  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (xs[i] - meanX) * (series[i] - meanY);
    den += (xs[i] - meanX) ** 2;
  }
  const slope = den === 0 ? 0 : num / den;
  const normalized = meanY === 0 ? 0 : slope / Math.abs(meanY);
  const strength = Math.min(1, Math.abs(normalized));

  if (Math.abs(normalized) < FLAT_THRESHOLD) return { trend_direction: "flat", trend_strength: 0 };
  return { trend_direction: normalized > 0 ? "up" : "down", trend_strength: strength };
}

export function pctDelta(current: number, previous: number): number {
  if (previous === 0) return current === 0 ? 0 : 1;
  return (current - previous) / previous;
}
```

- [ ] **Step 4: Run tests, expect green; commit**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/transforms/__tests__/trend.test.ts && git add lib/internal-analytics/transforms/ && git commit -m "feat(analytics): add trend computation"
```

---

## Task 2.2 — GA4 + GSC transform helpers (TDD)

**Files:**
- Create: `frontend/lib/internal-analytics/transforms/ga4.ts`
- Create: `frontend/lib/internal-analytics/transforms/gsc.ts`
- Test: `frontend/lib/internal-analytics/transforms/__tests__/ga4.test.ts`
- Test: `frontend/lib/internal-analytics/transforms/__tests__/gsc.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// frontend/lib/internal-analytics/transforms/__tests__/ga4.test.ts
import { describe, it, expect } from "vitest";
import { ga4RowsToObjects } from "../ga4";

describe("ga4RowsToObjects", () => {
  it("merges metric and dimension headers into row objects with parsed numerics", () => {
    const raw = {
      dimensionHeaders: [{ name: "pagePath" }],
      metricHeaders: [{ name: "screenPageViews" }, { name: "engagementRate" }],
      rows: [
        { dimensionValues: [{ value: "/" }], metricValues: [{ value: "120" }, { value: "0.45" }] },
        { dimensionValues: [{ value: "/upgrade" }], metricValues: [{ value: "30" }, { value: "0.62" }] },
      ],
    };
    expect(ga4RowsToObjects(raw)).toEqual([
      { pagePath: "/", screenPageViews: 120, engagementRate: 0.45 },
      { pagePath: "/upgrade", screenPageViews: 30, engagementRate: 0.62 },
    ]);
  });

  it("returns empty array when raw has no rows", () => {
    expect(ga4RowsToObjects({ rows: [] })).toEqual([]);
    expect(ga4RowsToObjects({})).toEqual([]);
  });
});
```

```ts
// frontend/lib/internal-analytics/transforms/__tests__/gsc.test.ts
import { describe, it, expect } from "vitest";
import { gscRowsToObjects, computeGscDeltas } from "../gsc";

describe("gscRowsToObjects", () => {
  it("maps GSC `keys` array to dimension columns", () => {
    const raw = {
      rows: [
        { keys: ["youth soccer rankings"], clicks: 120, impressions: 5000, ctr: 0.024, position: 6.3 },
        { keys: ["club soccer az"], clicks: 95, impressions: 4200, ctr: 0.022, position: 7.1 },
      ],
    };
    const result = gscRowsToObjects(raw, ["query"]);
    expect(result).toEqual([
      { query: "youth soccer rankings", clicks: 120, impressions: 5000, ctr: 0.024, position: 6.3 },
      { query: "club soccer az", clicks: 95, impressions: 4200, ctr: 0.022, position: 7.1 },
    ]);
  });
});

describe("computeGscDeltas", () => {
  it("returns absolute deltas for ctr and position, percent deltas for clicks and impressions", () => {
    const d = computeGscDeltas(
      { clicks: 110, impressions: 5500, ctr: 0.025, position: 5.8 },
      { clicks: 100, impressions: 5000, ctr: 0.020, position: 6.3 },
    );
    expect(d.clicks_delta).toBeCloseTo(0.1);
    expect(d.impressions_delta).toBeCloseTo(0.1);
    expect(d.ctr_delta).toBeCloseTo(0.005);
    expect(d.position_delta).toBeCloseTo(0.5);    // lower position is better → positive when improved
  });
});
```

- [ ] **Step 2: Run tests, expect failure**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/transforms/__tests__/
```

- [ ] **Step 3: Implement `ga4.ts`**

```ts
// frontend/lib/internal-analytics/transforms/ga4.ts
type RawGa4 = {
  dimensionHeaders?: { name: string }[];
  metricHeaders?: { name: string }[];
  rows?: { dimensionValues?: { value: string }[]; metricValues?: { value: string }[] }[];
};

export function ga4RowsToObjects(raw: RawGa4): Record<string, string | number>[] {
  if (!raw.rows?.length) return [];
  const dimNames = (raw.dimensionHeaders ?? []).map((h) => h.name);
  const metricNames = (raw.metricHeaders ?? []).map((h) => h.name);
  return raw.rows.map((row) => {
    const obj: Record<string, string | number> = {};
    (row.dimensionValues ?? []).forEach((v, i) => { obj[dimNames[i]] = v.value; });
    (row.metricValues ?? []).forEach((v, i) => {
      const num = Number(v.value);
      obj[metricNames[i]] = Number.isNaN(num) ? v.value : num;
    });
    return obj;
  });
}
```

- [ ] **Step 4: Implement `gsc.ts`**

```ts
// frontend/lib/internal-analytics/transforms/gsc.ts
import { pctDelta } from "./trend";

type RawGscRow = {
  keys?: string[];
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
};

export function gscRowsToObjects(
  raw: { rows?: RawGscRow[] },
  dimensions: string[],
): Record<string, string | number>[] {
  if (!raw.rows?.length) return [];
  return raw.rows.map((r) => {
    const obj: Record<string, string | number> = {
      clicks: r.clicks,
      impressions: r.impressions,
      ctr: r.ctr,
      position: r.position,
    };
    (r.keys ?? []).forEach((v, i) => { obj[dimensions[i]] = v; });
    return obj;
  });
}

export function computeGscDeltas(
  current: { clicks: number; impressions: number; ctr: number; position: number },
  previous: { clicks: number; impressions: number; ctr: number; position: number },
) {
  return {
    clicks_delta: pctDelta(current.clicks, previous.clicks),
    impressions_delta: pctDelta(current.impressions, previous.impressions),
    ctr_delta: current.ctr - previous.ctr,
    position_delta: previous.position - current.position,    // lower is better → positive = improvement
  };
}
```

- [ ] **Step 5: Run tests, expect green; commit**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/transforms/__tests__/ && git add lib/internal-analytics/transforms/ && git commit -m "feat(analytics): add GA4 and GSC row transforms with delta computation"
```

---

## Task 2.3 — In-flight request coalescing (TDD)

**Files:**
- Create: `frontend/lib/internal-analytics/queries/_coalesce.ts`
- Test: `frontend/lib/internal-analytics/queries/__tests__/_coalesce.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// frontend/lib/internal-analytics/queries/__tests__/_coalesce.test.ts
import { describe, it, expect, vi } from "vitest";
import { coalesce, sortedKeys } from "../_coalesce";

describe("coalesce", () => {
  it("returns the same promise for concurrent same-key calls", async () => {
    const fn = vi.fn(async () => { await new Promise((r) => setTimeout(r, 10)); return 42; });
    const [a, b] = await Promise.all([coalesce("k", fn), coalesce("k", fn)]);
    expect(a).toBe(42);
    expect(b).toBe(42);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("does not share between different keys", async () => {
    const fn = vi.fn(async () => 1);
    await Promise.all([coalesce("a", fn), coalesce("b", fn)]);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("releases the slot after rejection so retries are possible", async () => {
    let n = 0;
    const fn = async () => { n++; if (n === 1) throw new Error("first"); return "ok"; };
    await expect(coalesce("k", fn)).rejects.toThrow("first");
    await expect(coalesce("k", fn)).resolves.toBe("ok");
  });
});

describe("sortedKeys", () => {
  it("produces stable JSON regardless of property insertion order", () => {
    expect(sortedKeys({ b: 1, a: 2 })).toBe(JSON.stringify({ a: 2, b: 1 }));
  });
});
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/queries/__tests__/_coalesce.test.ts
```

- [ ] **Step 3: Implement `_coalesce.ts`**

```ts
// frontend/lib/internal-analytics/queries/_coalesce.ts
const inFlight = new Map<string, Promise<unknown>>();

export function coalesce<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const existing = inFlight.get(key) as Promise<T> | undefined;
  if (existing) return existing;
  const p = fn().finally(() => { inFlight.delete(key); });
  inFlight.set(key, p);
  return p;
}

export function sortedKeys(obj: unknown): string {
  if (obj === null || typeof obj !== "object") return JSON.stringify(obj);
  if (Array.isArray(obj)) return JSON.stringify(obj.map((v) => JSON.parse(sortedKeys(v))));
  const sorted: Record<string, unknown> = {};
  for (const k of Object.keys(obj as object).sort()) {
    sorted[k] = JSON.parse(sortedKeys((obj as Record<string, unknown>)[k]));
  }
  return JSON.stringify(sorted);
}
```

- [ ] **Step 4: Run tests, expect green; commit**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/queries/__tests__/_coalesce.test.ts && git add lib/internal-analytics/queries/ && git commit -m "feat(analytics): add request coalescing and stable key serialization"
```

---

## Task 2.4 — `getGa4Overview` query

**Files:**
- Create: `frontend/lib/internal-analytics/queries/ga4-overview.ts`

- [ ] **Step 1: Implement the query function**

```ts
// frontend/lib/internal-analytics/queries/ga4-overview.ts
import "server-only";
import { unstable_cache } from "next/cache";
import { getAnalyticsDataClient } from "@/lib/google-auth";
import { GA4_PROPERTY_ID, CACHE_TTL_SECONDS } from "../constants";
import type { DateRange, TileResponse } from "../types";
import { resolveDateRange, detectFreshness, todayInPropertyTz, previousPeriod, rangeDays } from "../dates";
import { ga4RowsToObjects } from "../transforms/ga4";
import { computeTrend, pctDelta } from "../transforms/trend";
import { coalesce, sortedKeys } from "./_coalesce";
import { toTaxonomyError, TaxonomyAwareError } from "./_error";

export type Ga4OverviewParams = {
  dateRange: DateRange;
  compareToPrevious?: boolean;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4OverviewRow = {
  date: string;
  sessions: number;
  activeUsers: number;
  screenPageViews: number;
};

async function fetchOverviewRaw(range: DateRange): Promise<unknown> {
  try {
    const client = getAnalyticsDataClient();
    const res = await client.properties.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      requestBody: {
        dateRanges: [{ startDate: range.start, endDate: range.end }],
        dimensions: [{ name: "date" }],
        metrics: [{ name: "sessions" }, { name: "activeUsers" }, { name: "screenPageViews" }],
        orderBys: [{ dimension: { dimensionName: "date" } }],
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

function normalize(raw: unknown, range: DateRange, timezone: string, previous?: { raw: unknown; range: DateRange }): TileResponse<Ga4OverviewRow> {
  const rows = ga4RowsToObjects(raw as never).map((r) => ({
    date: String(r.date),
    sessions: Number(r.sessions ?? 0),
    activeUsers: Number(r.activeUsers ?? 0),
    screenPageViews: Number(r.screenPageViews ?? 0),
  }));

  const totals = rows.reduce(
    (acc, r) => ({
      sessions: acc.sessions + r.sessions,
      activeUsers: acc.activeUsers + r.activeUsers,
      screenPageViews: acc.screenPageViews + r.screenPageViews,
    }),
    { sessions: 0, activeUsers: 0, screenPageViews: 0 },
  );

  const trend = computeTrend(rows.map((r) => r.sessions));
  const fresh = detectFreshness("ga4", range, timezone);

  let previous_period: TileResponse<Ga4OverviewRow>["previous_period"] | undefined;
  let derived: Record<string, number | string> = {
    trend_direction: trend.trend_direction,
    trend_strength: trend.trend_strength,
  };

  if (previous) {
    const prevRows = ga4RowsToObjects(previous.raw as never).map((r) => ({
      date: String(r.date),
      sessions: Number(r.sessions ?? 0),
      activeUsers: Number(r.activeUsers ?? 0),
      screenPageViews: Number(r.screenPageViews ?? 0),
    }));
    const prevTotals = prevRows.reduce(
      (acc, r) => ({
        sessions: acc.sessions + r.sessions,
        activeUsers: acc.activeUsers + r.activeUsers,
        screenPageViews: acc.screenPageViews + r.screenPageViews,
      }),
      { sessions: 0, activeUsers: 0, screenPageViews: 0 },
    );
    derived = {
      ...derived,
      sessions_delta: pctDelta(totals.sessions, prevTotals.sessions),
      users_delta: pctDelta(totals.activeUsers, prevTotals.activeUsers),
      pageviews_delta: pctDelta(totals.screenPageViews, prevTotals.screenPageViews),
    };
    previous_period = { rows: prevRows, totals: prevTotals, derived: {} };
  }

  return {
    report: "ga4_traffic_overview",
    source: "ga4",
    date_range: range,
    timezone,
    rows,
    row_count: rows.length,
    totals,
    derived,
    previous_period,
    truncated: false,
    data_freshness: fresh.freshness,
    warnings: fresh.warnings,
    generated_at: new Date().toISOString(),
    debug: { cost: { estimated_units: rangeDays(range), range_days: rangeDays(range), metric_count: 3, dimension_count: 1, limit: 0 } },
  };
}

async function runOnce(params: Ga4OverviewParams): Promise<TileResponse<Ga4OverviewRow>> {
  const tz = params.timezone ?? "America/Phoenix";
  const range = resolveDateRange(params.dateRange, tz);

  if (params.compareToPrevious && rangeDays(range) > 90) {
    throw new TaxonomyAwareError({
      type: "VALIDATION", retryable: false,
      message: "Comparison disabled for ranges over 90 days (doubles API calls).",
    });
  }

  const raw = await fetchOverviewRaw(range);
  if (params.compareToPrevious) {
    const prevRange = previousPeriod(range);
    const prevRaw = await fetchOverviewRaw(prevRange);
    return normalize(raw, range, tz, { raw: prevRaw, range: prevRange });
  }
  return normalize(raw, range, tz);
}

export function getGa4Overview(params: Ga4OverviewParams): Promise<TileResponse<Ga4OverviewRow>> {
  const key = `ga4_overview:${sortedKeys({ ...params, forceFresh: undefined })}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ["ga4_overview", sortedKeys({ ...params, forceFresh: undefined })], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ["analytics:ga4", "analytics:ga4_overview"],
  })();
}
```

- [ ] **Step 2: Verify type-checks**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json
```

Expected: zero new errors in `lib/internal-analytics/queries/ga4-overview.ts`.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank/frontend && git add lib/internal-analytics/queries/ga4-overview.ts && git commit -m "feat(analytics): add ga4_traffic_overview query"
```

---

## Task 2.5 — `getGa4TopPages` query

**Files:**
- Create: `frontend/lib/internal-analytics/queries/ga4-top-pages.ts`

- [ ] **Step 1: Implement (mirrors Task 2.4 shape)**

```ts
// frontend/lib/internal-analytics/queries/ga4-top-pages.ts
import "server-only";
import { unstable_cache } from "next/cache";
import { getAnalyticsDataClient } from "@/lib/google-auth";
import { GA4_PROPERTY_ID, CACHE_TTL_SECONDS, DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT } from "../constants";
import type { DateRange, TileResponse } from "../types";
import { resolveDateRange, detectFreshness, rangeDays } from "../dates";
import { ga4RowsToObjects } from "../transforms/ga4";
import { coalesce, sortedKeys } from "./_coalesce";
import { toTaxonomyError, TaxonomyAwareError } from "./_error";

export type Ga4TopPagesParams = {
  dateRange: DateRange;
  limit?: number;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4TopPagesRow = {
  pagePath: string;
  pageTitle: string;
  screenPageViews: number;
  activeUsers: number;
  engagementRate: number;
};

async function fetchRaw(range: DateRange, limit: number) {
  try {
    const client = getAnalyticsDataClient();
    const res = await client.properties.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      requestBody: {
        dateRanges: [{ startDate: range.start, endDate: range.end }],
        dimensions: [{ name: "pagePath" }, { name: "pageTitle" }],
        metrics: [{ name: "screenPageViews" }, { name: "activeUsers" }, { name: "engagementRate" }],
        orderBys: [{ metric: { metricName: "screenPageViews" }, desc: true }],
        limit: String(limit),
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: Ga4TopPagesParams): Promise<TileResponse<Ga4TopPagesRow>> {
  const tz = params.timezone ?? "America/Phoenix";
  const range = resolveDateRange(params.dateRange, tz);
  const limit = Math.min(params.limit ?? DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT);

  const raw = await fetchRaw(range, limit);
  const rows = ga4RowsToObjects(raw as never).map((r) => ({
    pagePath: String(r.pagePath ?? ""),
    pageTitle: String(r.pageTitle ?? ""),
    screenPageViews: Number(r.screenPageViews ?? 0),
    activeUsers: Number(r.activeUsers ?? 0),
    engagementRate: Number(r.engagementRate ?? 0),
  }));
  const totals = rows.reduce(
    (acc, r) => ({
      screenPageViews: acc.screenPageViews + r.screenPageViews,
      activeUsers: acc.activeUsers + r.activeUsers,
    }),
    { screenPageViews: 0, activeUsers: 0 },
  );
  const fresh = detectFreshness("ga4", range, tz);

  return {
    report: "ga4_top_pages",
    source: "ga4",
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals,
    derived: {},
    truncated: rows.length >= limit,
    truncation_reason: rows.length >= limit ? "limit_reached" : undefined,
    data_freshness: fresh.freshness,
    warnings: fresh.warnings,
    generated_at: new Date().toISOString(),
    debug: { cost: { estimated_units: rangeDays(range) * 2, range_days: rangeDays(range), metric_count: 3, dimension_count: 2, limit } },
  };
}

export function getGa4TopPages(params: Ga4TopPagesParams): Promise<TileResponse<Ga4TopPagesRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `ga4_top_pages:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ["ga4_top_pages", sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ["analytics:ga4", "analytics:ga4_top_pages"],
  })();
}
```

- [ ] **Step 2: Verify and commit**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json && git add lib/internal-analytics/queries/ga4-top-pages.ts && git commit -m "feat(analytics): add ga4_top_pages query"
```

---

## Task 2.6 — `getGa4UpgradeViews` query

**Files:**
- Create: `frontend/lib/internal-analytics/queries/ga4-upgrade-views.ts`

- [ ] **Step 1: Implement**

```ts
// frontend/lib/internal-analytics/queries/ga4-upgrade-views.ts
import "server-only";
import { unstable_cache } from "next/cache";
import { getAnalyticsDataClient } from "@/lib/google-auth";
import { GA4_PROPERTY_ID, CACHE_TTL_SECONDS } from "../constants";
import type { DateRange, TileResponse } from "../types";
import { resolveDateRange, detectFreshness, rangeDays, previousPeriod } from "../dates";
import { ga4RowsToObjects } from "../transforms/ga4";
import { pctDelta } from "../transforms/trend";
import { coalesce, sortedKeys } from "./_coalesce";
import { toTaxonomyError, TaxonomyAwareError } from "./_error";

export type Ga4UpgradeViewsParams = {
  dateRange: DateRange;
  compareToPrevious?: boolean;
  forceFresh?: boolean;
  timezone?: string;
};

export type Ga4UpgradeViewsRow = {
  date: string;
  upgradeViews: number;
  totalSessions: number;
};

async function fetchRaw(range: DateRange) {
  const client = getAnalyticsDataClient();
  // Two parallel reports: filtered upgrade views, and total sessions.
  try {
    const [upgrade, total] = await Promise.all([
      client.properties.runReport({
        property: `properties/${GA4_PROPERTY_ID}`,
        requestBody: {
          dateRanges: [{ startDate: range.start, endDate: range.end }],
          dimensions: [{ name: "date" }],
          metrics: [{ name: "screenPageViews" }],
          dimensionFilter: {
            filter: { fieldName: "pagePath", stringFilter: { matchType: "EXACT", value: "/upgrade" } },
          },
          orderBys: [{ dimension: { dimensionName: "date" } }],
        },
      }),
      client.properties.runReport({
        property: `properties/${GA4_PROPERTY_ID}`,
        requestBody: {
          dateRanges: [{ startDate: range.start, endDate: range.end }],
          dimensions: [{ name: "date" }],
          metrics: [{ name: "sessions" }],
          orderBys: [{ dimension: { dimensionName: "date" } }],
        },
      }),
    ]);
    return { upgrade: upgrade.data, total: total.data };
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: Ga4UpgradeViewsParams): Promise<TileResponse<Ga4UpgradeViewsRow>> {
  const tz = params.timezone ?? "America/Phoenix";
  const range = resolveDateRange(params.dateRange, tz);

  if (params.compareToPrevious && rangeDays(range) > 90) {
    throw new TaxonomyAwareError({
      type: "VALIDATION", retryable: false,
      message: "Comparison disabled for ranges over 90 days (doubles API calls).",
    });
  }

  const { upgrade, total } = await fetchRaw(range);
  const upRows = ga4RowsToObjects(upgrade as never);
  const totRows = ga4RowsToObjects(total as never);
  const totByDate = new Map(totRows.map((r) => [String(r.date), Number(r.sessions ?? 0)]));

  const rows: Ga4UpgradeViewsRow[] = [];
  for (const date of new Set([...upRows.map((r) => String(r.date)), ...totRows.map((r) => String(r.date))])) {
    const upRow = upRows.find((r) => r.date === date);
    rows.push({
      date,
      upgradeViews: Number(upRow?.screenPageViews ?? 0),
      totalSessions: totByDate.get(date) ?? 0,
    });
  }
  rows.sort((a, b) => a.date.localeCompare(b.date));

  const totals = rows.reduce(
    (acc, r) => ({ upgradeViews: acc.upgradeViews + r.upgradeViews, totalSessions: acc.totalSessions + r.totalSessions }),
    { upgradeViews: 0, totalSessions: 0 },
  );
  const conversionRate = totals.totalSessions === 0 ? 0 : totals.upgradeViews / totals.totalSessions;

  let derived: Record<string, number | string> = { conversion_rate: conversionRate };
  let previous_period: TileResponse<Ga4UpgradeViewsRow>["previous_period"];

  if (params.compareToPrevious) {
    const prevRange = previousPeriod(range);
    const prev = await fetchRaw(prevRange);
    const prevUp = ga4RowsToObjects(prev.upgrade as never);
    const prevTot = ga4RowsToObjects(prev.total as never);
    const prevTotals = {
      upgradeViews: prevUp.reduce((s, r) => s + Number(r.screenPageViews ?? 0), 0),
      totalSessions: prevTot.reduce((s, r) => s + Number(r.sessions ?? 0), 0),
    };
    derived = {
      ...derived,
      upgrade_views_delta: pctDelta(totals.upgradeViews, prevTotals.upgradeViews),
      conversion_rate_delta:
        (prevTotals.totalSessions === 0 ? 0 : prevTotals.upgradeViews / prevTotals.totalSessions) - conversionRate,
    };
    previous_period = { rows: [], totals: prevTotals, derived: {} };
  }

  const fresh = detectFreshness("ga4", range, tz);

  return {
    report: "ga4_upgrade_views",
    source: "ga4",
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals,
    derived,
    previous_period,
    truncated: false,
    data_freshness: fresh.freshness,
    warnings: fresh.warnings,
    generated_at: new Date().toISOString(),
    debug: { cost: { estimated_units: rangeDays(range) * 2, range_days: rangeDays(range), metric_count: 2, dimension_count: 1, limit: 0 } },
  };
}

export function getGa4UpgradeViews(params: Ga4UpgradeViewsParams): Promise<TileResponse<Ga4UpgradeViewsRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `ga4_upgrade_views:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ["ga4_upgrade_views", sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ["analytics:ga4", "analytics:ga4_upgrade_views"],
  })();
}
```

- [ ] **Step 2: Verify and commit**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json && git add lib/internal-analytics/queries/ga4-upgrade-views.ts && git commit -m "feat(analytics): add ga4_upgrade_views query"
```

---

## Task 2.7 — `getGscPerformance` query

**Files:**
- Create: `frontend/lib/internal-analytics/queries/gsc-performance.ts`

- [ ] **Step 1: Implement**

```ts
// frontend/lib/internal-analytics/queries/gsc-performance.ts
import "server-only";
import { unstable_cache } from "next/cache";
import { getSearchConsoleClient } from "@/lib/google-auth";
import { GSC_SITE_URL, CACHE_TTL_SECONDS } from "../constants";
import type { DateRange, TileResponse } from "../types";
import { resolveDateRange, detectFreshness, rangeDays, previousPeriod, todayInPropertyTz } from "../dates";
import { gscRowsToObjects, computeGscDeltas } from "../transforms/gsc";
import { computeTrend } from "../transforms/trend";
import { coalesce, sortedKeys } from "./_coalesce";
import { toTaxonomyError, TaxonomyAwareError } from "./_error";

export type GscPerformanceParams = {
  dateRange: DateRange;
  compareToPrevious?: boolean;
  forceFresh?: boolean;
  timezone?: string;
};

export type GscPerformanceRow = {
  date: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
};

function snapEndDate(range: DateRange, tz: string): { range: DateRange; snapped: boolean } {
  const today = todayInPropertyTz(tz);
  const cutoff = new Date(Date.parse(today + "T00:00:00Z") - 2 * 86_400_000).toISOString().slice(0, 10);
  if (range.end > cutoff) return { range: { ...range, end: cutoff }, snapped: true };
  return { range, snapped: false };
}

async function fetchRaw(range: DateRange) {
  try {
    const client = getSearchConsoleClient();
    const res = await client.searchanalytics.query({
      siteUrl: GSC_SITE_URL,
      requestBody: {
        startDate: range.start,
        endDate: range.end,
        dimensions: ["date"],
        rowLimit: 25_000,
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: GscPerformanceParams): Promise<TileResponse<GscPerformanceRow>> {
  const tz = params.timezone ?? "America/Phoenix";
  const resolved = resolveDateRange(params.dateRange, tz);
  if (params.compareToPrevious && rangeDays(resolved) > 90) {
    throw new TaxonomyAwareError({
      type: "VALIDATION", retryable: false,
      message: "Comparison disabled for ranges over 90 days (doubles API calls).",
    });
  }

  const { range, snapped } = snapEndDate(resolved, tz);
  const raw = await fetchRaw(range);
  const rows = gscRowsToObjects(raw as never, ["date"]).map((r) => ({
    date: String(r.date),
    clicks: Number(r.clicks ?? 0),
    impressions: Number(r.impressions ?? 0),
    ctr: Number(r.ctr ?? 0),
    position: Number(r.position ?? 0),
  }));
  const totals = rows.reduce(
    (acc, r) => ({
      clicks: acc.clicks + r.clicks,
      impressions: acc.impressions + r.impressions,
      ctr: 0,    // recomputed below
      position: 0,
    }),
    { clicks: 0, impressions: 0, ctr: 0, position: 0 },
  );
  totals.ctr = totals.impressions === 0 ? 0 : totals.clicks / totals.impressions;
  totals.position = rows.length === 0 ? 0 : rows.reduce((s, r) => s + r.position, 0) / rows.length;

  const trend = computeTrend(rows.map((r) => r.clicks));
  let derived: Record<string, number | string> = {
    trend_direction: trend.trend_direction,
    trend_strength: trend.trend_strength,
  };
  let previous_period: TileResponse<GscPerformanceRow>["previous_period"];

  if (params.compareToPrevious) {
    const prevRange = previousPeriod(range);
    const prevRaw = await fetchRaw(prevRange);
    const prevRows = gscRowsToObjects(prevRaw as never, ["date"]).map((r) => ({
      date: String(r.date),
      clicks: Number(r.clicks ?? 0),
      impressions: Number(r.impressions ?? 0),
      ctr: Number(r.ctr ?? 0),
      position: Number(r.position ?? 0),
    }));
    const prevTotals = {
      clicks: prevRows.reduce((s, r) => s + r.clicks, 0),
      impressions: prevRows.reduce((s, r) => s + r.impressions, 0),
      ctr: 0, position: 0,
    };
    prevTotals.ctr = prevTotals.impressions === 0 ? 0 : prevTotals.clicks / prevTotals.impressions;
    prevTotals.position = prevRows.length === 0 ? 0 : prevRows.reduce((s, r) => s + r.position, 0) / prevRows.length;
    derived = { ...derived, ...computeGscDeltas(totals, prevTotals) };
    previous_period = { rows: prevRows, totals: prevTotals, derived: {} };
  }

  const fresh = detectFreshness("gsc", range, tz);
  const warnings = [...fresh.warnings];
  if (snapped) warnings.unshift(`End date snapped to ${range.end} due to GSC reporting lag.`);

  return {
    report: "gsc_performance",
    source: "gsc",
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals,
    derived,
    previous_period,
    truncated: false,
    data_freshness: fresh.freshness,
    warnings,
    generated_at: new Date().toISOString(),
    debug: { cost: { estimated_units: rangeDays(range), range_days: rangeDays(range), metric_count: 4, dimension_count: 1, limit: 25_000 } },
  };
}

export function getGscPerformance(params: GscPerformanceParams): Promise<TileResponse<GscPerformanceRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `gsc_performance:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ["gsc_performance", sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ["analytics:gsc", "analytics:gsc_performance"],
  })();
}
```

- [ ] **Step 2: Verify and commit**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json && git add lib/internal-analytics/queries/gsc-performance.ts && git commit -m "feat(analytics): add gsc_performance query"
```

---

## Task 2.8 — `getGscTopQueries` query

**Files:**
- Create: `frontend/lib/internal-analytics/queries/gsc-top-queries.ts`

- [ ] **Step 1: Implement**

```ts
// frontend/lib/internal-analytics/queries/gsc-top-queries.ts
import "server-only";
import { unstable_cache } from "next/cache";
import { getSearchConsoleClient } from "@/lib/google-auth";
import { GSC_SITE_URL, CACHE_TTL_SECONDS, DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT } from "../constants";
import type { DateRange, TileResponse } from "../types";
import { resolveDateRange, detectFreshness, rangeDays, todayInPropertyTz } from "../dates";
import { gscRowsToObjects } from "../transforms/gsc";
import { coalesce, sortedKeys } from "./_coalesce";
import { toTaxonomyError, TaxonomyAwareError } from "./_error";

export type GscTopQueriesParams = {
  dateRange: DateRange;
  limit?: number;
  forceFresh?: boolean;
  timezone?: string;
};

export type GscTopQueriesRow = {
  query: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
};

function snapEnd(range: DateRange, tz: string): { range: DateRange; snapped: boolean } {
  const today = todayInPropertyTz(tz);
  const cutoff = new Date(Date.parse(today + "T00:00:00Z") - 2 * 86_400_000).toISOString().slice(0, 10);
  return range.end > cutoff ? { range: { ...range, end: cutoff }, snapped: true } : { range, snapped: false };
}

async function fetchRaw(range: DateRange, limit: number) {
  try {
    const client = getSearchConsoleClient();
    const res = await client.searchanalytics.query({
      siteUrl: GSC_SITE_URL,
      requestBody: {
        startDate: range.start,
        endDate: range.end,
        dimensions: ["query"],
        rowLimit: limit,
      },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: GscTopQueriesParams): Promise<TileResponse<GscTopQueriesRow>> {
  const tz = params.timezone ?? "America/Phoenix";
  const resolved = resolveDateRange(params.dateRange, tz);
  const limit = Math.min(params.limit ?? DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT);
  const { range, snapped } = snapEnd(resolved, tz);

  const raw = await fetchRaw(range, limit);
  const rows = gscRowsToObjects(raw as never, ["query"]).map((r) => ({
    query: String(r.query),
    clicks: Number(r.clicks ?? 0),
    impressions: Number(r.impressions ?? 0),
    ctr: Number(r.ctr ?? 0),
    position: Number(r.position ?? 0),
  }));
  const totals = {
    clicks: rows.reduce((s, r) => s + r.clicks, 0),
    impressions: rows.reduce((s, r) => s + r.impressions, 0),
    ctr: 0,
    position: 0,
  };
  totals.ctr = totals.impressions === 0 ? 0 : totals.clicks / totals.impressions;
  totals.position = rows.length === 0 ? 0 : rows.reduce((s, r) => s + r.position, 0) / rows.length;

  const fresh = detectFreshness("gsc", range, tz);
  const warnings = [...fresh.warnings];
  if (snapped) warnings.unshift(`End date snapped to ${range.end} due to GSC reporting lag.`);

  return {
    report: "gsc_top_queries",
    source: "gsc",
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals,
    derived: {},
    truncated: rows.length >= limit,
    truncation_reason: rows.length >= limit ? "limit_reached" : undefined,
    data_freshness: fresh.freshness,
    warnings,
    generated_at: new Date().toISOString(),
    debug: { cost: { estimated_units: 1, range_days: rangeDays(range), metric_count: 4, dimension_count: 1, limit } },
  };
}

export function getGscTopQueries(params: GscTopQueriesParams): Promise<TileResponse<GscTopQueriesRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `gsc_top_queries:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ["gsc_top_queries", sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ["analytics:gsc", "analytics:gsc_top_queries"],
  })();
}
```

- [ ] **Step 2: Verify and commit**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json && git add lib/internal-analytics/queries/gsc-top-queries.ts && git commit -m "feat(analytics): add gsc_top_queries query"
```

---

## Task 2.9 — `getGscLandingPages` query (with feasibility note)

**Files:**
- Create: `frontend/lib/internal-analytics/queries/gsc-landing-pages.ts`

> **Note:** True "index coverage" requires the URL Inspection API which is rate-limited per-URL (2000/day). For v1 we ship the documented fallback: top landing pages from search via the `page` dimension. The registry already uses `gsc_landing_pages` for this reason.

- [ ] **Step 1: Implement (mirrors Task 2.8 with `page` dimension)**

```ts
// frontend/lib/internal-analytics/queries/gsc-landing-pages.ts
import "server-only";
import { unstable_cache } from "next/cache";
import { getSearchConsoleClient } from "@/lib/google-auth";
import { GSC_SITE_URL, CACHE_TTL_SECONDS, DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT } from "../constants";
import type { DateRange, TileResponse } from "../types";
import { resolveDateRange, detectFreshness, rangeDays, todayInPropertyTz } from "../dates";
import { gscRowsToObjects } from "../transforms/gsc";
import { coalesce, sortedKeys } from "./_coalesce";
import { toTaxonomyError, TaxonomyAwareError } from "./_error";

export type GscLandingPagesParams = {
  dateRange: DateRange;
  limit?: number;
  forceFresh?: boolean;
  timezone?: string;
};

export type GscLandingPagesRow = {
  page: string;
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
};

function snapEnd(range: DateRange, tz: string) {
  const today = todayInPropertyTz(tz);
  const cutoff = new Date(Date.parse(today + "T00:00:00Z") - 2 * 86_400_000).toISOString().slice(0, 10);
  return range.end > cutoff ? { range: { ...range, end: cutoff }, snapped: true } : { range, snapped: false };
}

async function fetchRaw(range: DateRange, limit: number) {
  try {
    const client = getSearchConsoleClient();
    const res = await client.searchanalytics.query({
      siteUrl: GSC_SITE_URL,
      requestBody: { startDate: range.start, endDate: range.end, dimensions: ["page"], rowLimit: limit },
    });
    return res.data;
  } catch (e) {
    throw new TaxonomyAwareError(toTaxonomyError(e));
  }
}

async function runOnce(params: GscLandingPagesParams): Promise<TileResponse<GscLandingPagesRow>> {
  const tz = params.timezone ?? "America/Phoenix";
  const resolved = resolveDateRange(params.dateRange, tz);
  const limit = Math.min(params.limit ?? DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT);
  const { range, snapped } = snapEnd(resolved, tz);

  const raw = await fetchRaw(range, limit);
  const rows = gscRowsToObjects(raw as never, ["page"]).map((r) => ({
    page: String(r.page),
    clicks: Number(r.clicks ?? 0),
    impressions: Number(r.impressions ?? 0),
    ctr: Number(r.ctr ?? 0),
    position: Number(r.position ?? 0),
  }));
  const totals = {
    clicks: rows.reduce((s, r) => s + r.clicks, 0),
    impressions: rows.reduce((s, r) => s + r.impressions, 0),
    ctr: 0, position: 0,
  };
  totals.ctr = totals.impressions === 0 ? 0 : totals.clicks / totals.impressions;
  totals.position = rows.length === 0 ? 0 : rows.reduce((s, r) => s + r.position, 0) / rows.length;

  const fresh = detectFreshness("gsc", range, tz);
  const warnings = [...fresh.warnings];
  if (snapped) warnings.unshift(`End date snapped to ${range.end} due to GSC reporting lag.`);

  return {
    report: "gsc_landing_pages",
    source: "gsc",
    date_range: range,
    timezone: tz,
    rows,
    row_count: rows.length,
    totals,
    derived: {},
    truncated: rows.length >= limit,
    truncation_reason: rows.length >= limit ? "limit_reached" : undefined,
    data_freshness: fresh.freshness,
    warnings,
    generated_at: new Date().toISOString(),
    debug: { cost: { estimated_units: 1, range_days: rangeDays(range), metric_count: 4, dimension_count: 1, limit } },
  };
}

export function getGscLandingPages(params: GscLandingPagesParams): Promise<TileResponse<GscLandingPagesRow>> {
  const cacheArgs = { ...params, forceFresh: undefined };
  const key = `gsc_landing_pages:${sortedKeys(cacheArgs)}`;
  const run = () => coalesce(key, () => runOnce(params));
  if (params.forceFresh) return run();
  return unstable_cache(run, ["gsc_landing_pages", sortedKeys(cacheArgs)], {
    revalidate: CACHE_TTL_SECONDS,
    tags: ["analytics:gsc", "analytics:gsc_landing_pages"],
  })();
}
```

- [ ] **Step 2: Verify and commit**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json && git add lib/internal-analytics/queries/gsc-landing-pages.ts && git commit -m "feat(analytics): add gsc_landing_pages query"
```

---

## Task 2.10 — Report registry + `runReport`

**Files:**
- Create: `frontend/lib/internal-analytics/report-registry.ts`

- [ ] **Step 1: Implement registry**

```ts
// frontend/lib/internal-analytics/report-registry.ts
import "server-only";
import { z } from "zod";
import type { DateRangePreset } from "./types";
import { DATE_RANGE_PRESETS, MAX_ROW_LIMIT } from "./constants";
import { getGa4Overview } from "./queries/ga4-overview";
import { getGa4TopPages } from "./queries/ga4-top-pages";
import { getGa4UpgradeViews } from "./queries/ga4-upgrade-views";
import { getGscPerformance } from "./queries/gsc-performance";
import { getGscTopQueries } from "./queries/gsc-top-queries";
import { getGscLandingPages } from "./queries/gsc-landing-pages";

const DateRangeSchema = z.union([
  z.enum(DATE_RANGE_PRESETS as readonly [DateRangePreset, ...DateRangePreset[]]),
  z.object({ start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/), end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/) }),
]);

const Common = {
  date_range: DateRangeSchema,
  compare_to_previous: z.boolean().optional(),
  forceFresh: z.boolean().optional(),
};

export const REPORTS = {
  ga4_traffic_overview: {
    source: "ga4",
    description: "Sessions, active users, and pageviews over time with totals and trend.",
    paramsSchema: z.object({ ...Common }),
    handler: (p: { date_range: DateRangePreset | { start: string; end: string }; compare_to_previous?: boolean; forceFresh?: boolean }) =>
      getGa4Overview({ dateRange: p.date_range as never, compareToPrevious: p.compare_to_previous, forceFresh: p.forceFresh }),
    summaryRequired: ["totals", "trend_direction"],
    derivedMetrics: ["sessions_delta", "trend_direction"],
  },
  ga4_top_pages: {
    source: "ga4",
    description: "Top pages by pageviews with engagement rate.",
    paramsSchema: z.object({ ...Common, limit: z.number().int().min(1).max(MAX_ROW_LIMIT).optional() }),
    handler: (p: any) => getGa4TopPages({ dateRange: p.date_range, limit: p.limit, forceFresh: p.forceFresh }),
    summaryRequired: ["totals"],
  },
  ga4_upgrade_views: {
    source: "ga4",
    description: "Pageviews of /upgrade and conversion rate vs total sessions.",
    paramsSchema: z.object({ ...Common }),
    handler: (p: any) => getGa4UpgradeViews({ dateRange: p.date_range, compareToPrevious: p.compare_to_previous, forceFresh: p.forceFresh }),
    summaryRequired: ["totals", "conversion_rate"],
    derivedMetrics: ["conversion_rate"],
  },
  gsc_performance: {
    source: "gsc",
    description: "Clicks, impressions, CTR, and position over time with period-over-period deltas.",
    paramsSchema: z.object({ ...Common }),
    handler: (p: any) => getGscPerformance({ dateRange: p.date_range, compareToPrevious: p.compare_to_previous, forceFresh: p.forceFresh }),
    summaryRequired: ["totals", "ctr_delta", "impressions_delta", "position_delta"],
  },
  gsc_top_queries: {
    source: "gsc",
    description: "Top search queries by clicks with CTR and average position.",
    paramsSchema: z.object({ ...Common, limit: z.number().int().min(1).max(MAX_ROW_LIMIT).optional() }),
    handler: (p: any) => getGscTopQueries({ dateRange: p.date_range, limit: p.limit, forceFresh: p.forceFresh }),
    summaryRequired: ["totals"],
  },
  gsc_landing_pages: {
    source: "gsc",
    description: "Top landing pages receiving search traffic (may display as Index Coverage in UI).",
    paramsSchema: z.object({ ...Common, limit: z.number().int().min(1).max(MAX_ROW_LIMIT).optional() }),
    handler: (p: any) => getGscLandingPages({ dateRange: p.date_range, limit: p.limit, forceFresh: p.forceFresh }),
    experimental: true,
  },
} as const;

export type ReportKey = keyof typeof REPORTS;

export async function runReport(key: ReportKey, params: unknown) {
  const report = REPORTS[key];
  const validated = report.paramsSchema.parse(params);
  return report.handler(validated as any);
}
```

- [ ] **Step 2: If `zod` isn't installed, install it**

```bash
cd C:/PitchRank/frontend && npm ls zod || npm install zod
```

- [ ] **Step 3: Verify and commit**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json && git add lib/internal-analytics/report-registry.ts package.json package-lock.json && git commit -m "feat(analytics): add report registry with runReport dispatcher"
```

---

## Task 2.11 — `meta` and `refresh` API routes

**Files:**
- Create: `frontend/app/api/internal/analytics/meta/route.ts`
- Create: `frontend/app/api/internal/analytics/refresh/route.ts`

- [ ] **Step 1: Implement `meta`**

```ts
// frontend/app/api/internal/analytics/meta/route.ts
import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/supabase/admin";
import { GA4_PROPERTY_ID, GSC_SITE_URL, DATE_RANGE_PRESETS, DEFAULT_PRESET } from "@/lib/internal-analytics/constants";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  return NextResponse.json({
    presets: DATE_RANGE_PRESETS,
    default_preset: DEFAULT_PRESET,
    ga4_property_id: GA4_PROPERTY_ID,
    gsc_site_url: GSC_SITE_URL,
    admin_email: auth.user.email ?? null,
    timezone: "America/Phoenix",
  });
}
```

- [ ] **Step 2: Implement `refresh`**

```ts
// frontend/app/api/internal/analytics/refresh/route.ts
import { NextResponse } from "next/server";
import { revalidateTag } from "next/cache";
import { requireAdmin } from "@/lib/supabase/admin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  revalidateTag("analytics:ga4");
  revalidateTag("analytics:gsc");
  return NextResponse.json({ ok: true, refreshed_at: new Date().toISOString() });
}
```

- [ ] **Step 3: Smoke test locally**

```bash
cd C:/PitchRank/frontend && npm run dev
```

In a browser/curl as admin (cookies needed):
1. `GET /api/internal/analytics/meta` → 200 with the JSON.
2. `POST /api/internal/analytics/refresh` → 200 with `{ ok: true }`.
3. As non-admin → 403.

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank/frontend && git add app/api/internal/analytics/ && git commit -m "feat(analytics): add meta and refresh routes"
```

---

# Phase 3 — Tiles

Goal: Six rendered tiles wired to API routes, with a working date range picker.

## Task 3.1 — DateRangePicker with URL state

**Files:**
- Create: `frontend/app/(internal)/analytics/components/DateRangePicker.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/app/(internal)/analytics/components/DateRangePicker.tsx
"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { DATE_RANGE_PRESETS, DEFAULT_PRESET } from "@/lib/internal-analytics/constants";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

const LABELS: Record<DateRangePreset, string> = {
  today: "Today",
  last_7_days: "Last 7 days",
  last_28_days: "Last 28 days",
  mtd: "Month to date",
};

export function DateRangePicker() {
  const router = useRouter();
  const params = useSearchParams();
  const current = (params.get("range") as DateRangePreset) ?? DEFAULT_PRESET;

  const setRange = (preset: DateRangePreset) => {
    const next = new URLSearchParams(params.toString());
    next.set("range", preset);
    router.push(`?${next.toString()}`, { scroll: false });
  };

  return (
    <div className="flex gap-2 flex-wrap">
      {DATE_RANGE_PRESETS.map((p) => (
        <Button
          key={p}
          variant={p === current ? "default" : "outline"}
          size="sm"
          onClick={() => setRange(p)}
        >
          {LABELS[p]}
        </Button>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd C:/PitchRank/frontend && git add app/\(internal\)/analytics/components/DateRangePicker.tsx && git commit -m "feat(analytics): add DateRangePicker with URL-synced state"
```

---

## Task 3.2 — TileShell + DashboardGrid scaffold

**Files:**
- Create: `frontend/app/(internal)/analytics/components/tiles/TileShell.tsx`
- Create: `frontend/app/(internal)/analytics/components/DashboardGrid.tsx`

- [ ] **Step 1: Implement TileShell**

```tsx
// frontend/app/(internal)/analytics/components/tiles/TileShell.tsx
"use client";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { AlertCircle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export type TileState =
  | { status: "loading" }
  | { status: "error"; message: string; retry?: () => void }
  | { status: "empty"; suggestion?: string }
  | { status: "success" };

export function TileShell({
  title,
  description,
  state,
  children,
}: {
  title: string;
  description?: string;
  state: TileState;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>
        {state.status === "loading" && (
          <div className="flex items-center gap-2 text-muted-foreground py-8 justify-center">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        )}
        {state.status === "error" && (
          <div className="flex flex-col items-center gap-2 text-destructive py-8">
            <AlertCircle className="h-4 w-4" />
            <span className="text-sm">{state.message}</span>
            {state.retry && <button className="text-xs underline" onClick={state.retry}>Retry</button>}
          </div>
        )}
        {state.status === "empty" && (
          <div className="text-sm text-muted-foreground py-8 text-center">
            No data for this range. {state.suggestion}
          </div>
        )}
        {state.status === "success" && children}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Implement DashboardGrid**

```tsx
// frontend/app/(internal)/analytics/components/DashboardGrid.tsx
"use client";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DEFAULT_PRESET, REACT_QUERY_STALE_MS, REACT_QUERY_GC_MS } from "@/lib/internal-analytics/constants";
import type { DateRangePreset } from "@/lib/internal-analytics/types";
import { DateRangePicker } from "./DateRangePicker";
import { TrafficOverviewTile } from "./tiles/TrafficOverviewTile";
import { TopPagesTile } from "./tiles/TopPagesTile";
import { UpgradeViewsTile } from "./tiles/UpgradeViewsTile";
import { SearchPerformanceTile } from "./tiles/SearchPerformanceTile";
import { TopQueriesTile } from "./tiles/TopQueriesTile";
import { LandingPagesTile } from "./tiles/LandingPagesTile";
import { ChatSidebar } from "./chat/ChatSidebar";

export function DashboardGrid() {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: REACT_QUERY_STALE_MS, gcTime: REACT_QUERY_GC_MS } } }),
  );
  const params = useSearchParams();
  const range = (params.get("range") as DateRangePreset) ?? DEFAULT_PRESET;

  return (
    <QueryClientProvider client={client}>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Internal Analytics</h1>
          <DateRangePicker />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-4">
            <TrafficOverviewTile range={range} />
            <UpgradeViewsTile range={range} />
            <TopPagesTile range={range} />
            <SearchPerformanceTile range={range} />
            <TopQueriesTile range={range} />
            <LandingPagesTile range={range} />
          </div>
          <div className="lg:col-span-1">
            <ChatSidebar range={range} />
          </div>
        </div>
      </div>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 3: Update `page.tsx` to mount the grid**

```tsx
// frontend/app/(internal)/analytics/page.tsx
import { DashboardGrid } from "./components/DashboardGrid";

export default function AnalyticsPage() {
  return <DashboardGrid />;
}
```

> **Note:** Compilation will fail until tile components and ChatSidebar exist (next tasks). That is intentional — fix as we go.

- [ ] **Step 4: Commit (compilation broken until next tasks)**

```bash
cd C:/PitchRank/frontend && git add app/\(internal\)/analytics/ && git commit -m "feat(analytics): scaffold DashboardGrid and TileShell (incomplete tiles WIP)"
```

---

## Task 3.3 — GA4 tile API routes

**Files:**
- Create: `frontend/app/api/internal/analytics/ga4/overview/route.ts`
- Create: `frontend/app/api/internal/analytics/ga4/top-pages/route.ts`
- Create: `frontend/app/api/internal/analytics/ga4/upgrade-views/route.ts`

- [ ] **Step 1: Implement overview route**

```ts
// frontend/app/api/internal/analytics/ga4/overview/route.ts
import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/supabase/admin";
import { runReport } from "@/lib/internal-analytics/report-registry";
import { TaxonomyAwareError } from "@/lib/internal-analytics/queries/_error";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  const url = new URL(req.url);
  const range = url.searchParams.get("range") ?? "last_7_days";
  const compare = url.searchParams.get("compare") === "1";
  try {
    const data = await runReport("ga4_traffic_overview", { date_range: range, compare_to_previous: compare });
    return NextResponse.json(data);
  } catch (e) {
    if (e instanceof TaxonomyAwareError) return NextResponse.json({ error: e.taxonomy }, { status: 500 });
    throw e;
  }
}
```

- [ ] **Step 2: Implement top-pages route (mirror)**

```ts
// frontend/app/api/internal/analytics/ga4/top-pages/route.ts
import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/supabase/admin";
import { runReport } from "@/lib/internal-analytics/report-registry";
import { TaxonomyAwareError } from "@/lib/internal-analytics/queries/_error";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  const url = new URL(req.url);
  const range = url.searchParams.get("range") ?? "last_7_days";
  const limit = Number(url.searchParams.get("limit") ?? 10);
  try {
    const data = await runReport("ga4_top_pages", { date_range: range, limit });
    return NextResponse.json(data);
  } catch (e) {
    if (e instanceof TaxonomyAwareError) return NextResponse.json({ error: e.taxonomy }, { status: 500 });
    throw e;
  }
}
```

- [ ] **Step 3: Implement upgrade-views route (mirror)**

```ts
// frontend/app/api/internal/analytics/ga4/upgrade-views/route.ts
import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/supabase/admin";
import { runReport } from "@/lib/internal-analytics/report-registry";
import { TaxonomyAwareError } from "@/lib/internal-analytics/queries/_error";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  const url = new URL(req.url);
  const range = url.searchParams.get("range") ?? "last_7_days";
  const compare = url.searchParams.get("compare") === "1";
  try {
    const data = await runReport("ga4_upgrade_views", { date_range: range, compare_to_previous: compare });
    return NextResponse.json(data);
  } catch (e) {
    if (e instanceof TaxonomyAwareError) return NextResponse.json({ error: e.taxonomy }, { status: 500 });
    throw e;
  }
}
```

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank/frontend && git add app/api/internal/analytics/ga4/ && git commit -m "feat(analytics): add GA4 tile API routes (overview, top-pages, upgrade-views)"
```

---

## Task 3.4 — GSC tile API routes

**Files:**
- Create: `frontend/app/api/internal/analytics/gsc/performance/route.ts`
- Create: `frontend/app/api/internal/analytics/gsc/top-queries/route.ts`
- Create: `frontend/app/api/internal/analytics/gsc/landing-pages/route.ts`

- [ ] **Step 1: Implement performance route**

```ts
// frontend/app/api/internal/analytics/gsc/performance/route.ts
import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/supabase/admin";
import { runReport } from "@/lib/internal-analytics/report-registry";
import { TaxonomyAwareError } from "@/lib/internal-analytics/queries/_error";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  const url = new URL(req.url);
  const range = url.searchParams.get("range") ?? "last_7_days";
  const compare = url.searchParams.get("compare") === "1";
  try {
    const data = await runReport("gsc_performance", { date_range: range, compare_to_previous: compare });
    return NextResponse.json(data);
  } catch (e) {
    if (e instanceof TaxonomyAwareError) return NextResponse.json({ error: e.taxonomy }, { status: 500 });
    throw e;
  }
}
```

- [ ] **Step 2: Implement top-queries route**

```ts
// frontend/app/api/internal/analytics/gsc/top-queries/route.ts
import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/supabase/admin";
import { runReport } from "@/lib/internal-analytics/report-registry";
import { TaxonomyAwareError } from "@/lib/internal-analytics/queries/_error";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  const url = new URL(req.url);
  const range = url.searchParams.get("range") ?? "last_7_days";
  const limit = Number(url.searchParams.get("limit") ?? 10);
  try {
    const data = await runReport("gsc_top_queries", { date_range: range, limit });
    return NextResponse.json(data);
  } catch (e) {
    if (e instanceof TaxonomyAwareError) return NextResponse.json({ error: e.taxonomy }, { status: 500 });
    throw e;
  }
}
```

- [ ] **Step 3: Implement landing-pages route**

```ts
// frontend/app/api/internal/analytics/gsc/landing-pages/route.ts
import { NextResponse } from "next/server";
import { requireAdmin } from "@/lib/supabase/admin";
import { runReport } from "@/lib/internal-analytics/report-registry";
import { TaxonomyAwareError } from "@/lib/internal-analytics/queries/_error";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  const url = new URL(req.url);
  const range = url.searchParams.get("range") ?? "last_7_days";
  const limit = Number(url.searchParams.get("limit") ?? 10);
  try {
    const data = await runReport("gsc_landing_pages", { date_range: range, limit });
    return NextResponse.json(data);
  } catch (e) {
    if (e instanceof TaxonomyAwareError) return NextResponse.json({ error: e.taxonomy }, { status: 500 });
    throw e;
  }
}
```

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank/frontend && git add app/api/internal/analytics/gsc/ && git commit -m "feat(analytics): add GSC tile API routes (performance, top-queries, landing-pages)"
```

---

## Task 3.5 — Traffic Overview tile

**Files:**
- Create: `frontend/app/(internal)/analytics/components/tiles/TrafficOverviewTile.tsx`

- [ ] **Step 1: Implement**

```tsx
// frontend/app/(internal)/analytics/components/tiles/TrafficOverviewTile.tsx
"use client";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { TileShell, type TileState } from "./TileShell";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

type Row = { date: string; sessions: number; activeUsers: number; screenPageViews: number };
type Resp = { rows: Row[]; totals: { sessions: number; activeUsers: number; screenPageViews: number }; row_count: number; warnings: string[] };

export function TrafficOverviewTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ["ga4_overview", range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/overview?range=${range}`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? "Request failed");
      return r.json();
    },
  });

  let state: TileState = { status: "loading" };
  if (q.isError) state = { status: "error", message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: "empty", suggestion: "Try a wider date range." };
  else if (q.data) state = { status: "success" };

  return (
    <TileShell title="Traffic" description="Sessions, users, pageviews" state={state}>
      {q.data && (
        <div className="space-y-3">
          <div className="flex gap-6 text-sm">
            <div><div className="text-muted-foreground">Sessions</div><div className="text-xl font-semibold">{q.data.totals.sessions.toLocaleString()}</div></div>
            <div><div className="text-muted-foreground">Users</div><div className="text-xl font-semibold">{q.data.totals.activeUsers.toLocaleString()}</div></div>
            <div><div className="text-muted-foreground">Views</div><div className="text-xl font-semibold">{q.data.totals.screenPageViews.toLocaleString()}</div></div>
          </div>
          <div className="h-32">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={q.data.rows}>
                <XAxis dataKey="date" hide />
                <YAxis hide />
                <Tooltip />
                <Line dataKey="sessions" type="monotone" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </TileShell>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd C:/PitchRank/frontend && git add app/\(internal\)/analytics/components/tiles/TrafficOverviewTile.tsx && git commit -m "feat(analytics): add TrafficOverviewTile"
```

---

## Task 3.6 — TopPages, UpgradeViews tiles

**Files:**
- Create: `frontend/app/(internal)/analytics/components/tiles/TopPagesTile.tsx`
- Create: `frontend/app/(internal)/analytics/components/tiles/UpgradeViewsTile.tsx`

- [ ] **Step 1: TopPagesTile**

```tsx
// frontend/app/(internal)/analytics/components/tiles/TopPagesTile.tsx
"use client";
import { useQuery } from "@tanstack/react-query";
import { TileShell, type TileState } from "./TileShell";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

type Row = { pagePath: string; pageTitle: string; screenPageViews: number; activeUsers: number; engagementRate: number };
type Resp = { rows: Row[]; row_count: number };

export function TopPagesTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ["ga4_top_pages", range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/top-pages?range=${range}&limit=10`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? "Request failed");
      return r.json();
    },
  });

  let state: TileState = { status: "loading" };
  if (q.isError) state = { status: "error", message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: "empty" };
  else if (q.data) state = { status: "success" };

  return (
    <TileShell title="Top Pages" description="Most viewed pages" state={state}>
      {q.data && (
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr><th>Page</th><th className="text-right">Views</th><th className="text-right">Eng.</th></tr>
          </thead>
          <tbody>
            {q.data.rows.map((r) => (
              <tr key={r.pagePath} className="border-t">
                <td className="py-1 truncate max-w-[160px]" title={r.pagePath}>{r.pagePath}</td>
                <td className="text-right">{r.screenPageViews.toLocaleString()}</td>
                <td className="text-right">{(r.engagementRate * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </TileShell>
  );
}
```

- [ ] **Step 2: UpgradeViewsTile**

```tsx
// frontend/app/(internal)/analytics/components/tiles/UpgradeViewsTile.tsx
"use client";
import { useQuery } from "@tanstack/react-query";
import { TileShell, type TileState } from "./TileShell";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

type Resp = {
  totals: { upgradeViews: number; totalSessions: number };
  derived: { conversion_rate: number; conversion_rate_delta?: number; upgrade_views_delta?: number };
  row_count: number;
};

export function UpgradeViewsTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ["ga4_upgrade_views", range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/ga4/upgrade-views?range=${range}&compare=1`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? "Request failed");
      return r.json();
    },
  });

  let state: TileState = { status: "loading" };
  if (q.isError) state = { status: "error", message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.totals.upgradeViews === 0) state = { status: "empty" };
  else if (q.data) state = { status: "success" };

  return (
    <TileShell title="/upgrade Views" description="Pageviews + conversion rate" state={state}>
      {q.data && (
        <div className="space-y-2">
          <div className="text-3xl font-semibold">{q.data.totals.upgradeViews.toLocaleString()}</div>
          <div className="text-sm text-muted-foreground">
            {(q.data.derived.conversion_rate * 100).toFixed(2)}% of sessions
            {q.data.derived.upgrade_views_delta !== undefined && (
              <span className={`ml-2 ${q.data.derived.upgrade_views_delta >= 0 ? "text-emerald-600" : "text-destructive"}`}>
                {q.data.derived.upgrade_views_delta >= 0 ? "▲" : "▼"} {Math.abs(q.data.derived.upgrade_views_delta * 100).toFixed(0)}%
              </span>
            )}
          </div>
        </div>
      )}
    </TileShell>
  );
}
```

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank/frontend && git add app/\(internal\)/analytics/components/tiles/ && git commit -m "feat(analytics): add TopPages and UpgradeViews tiles"
```

---

## Task 3.7 — SearchPerformance, TopQueries, LandingPages tiles

**Files:**
- Create: `frontend/app/(internal)/analytics/components/tiles/SearchPerformanceTile.tsx`
- Create: `frontend/app/(internal)/analytics/components/tiles/TopQueriesTile.tsx`
- Create: `frontend/app/(internal)/analytics/components/tiles/LandingPagesTile.tsx`

- [ ] **Step 1: SearchPerformanceTile**

```tsx
// frontend/app/(internal)/analytics/components/tiles/SearchPerformanceTile.tsx
"use client";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { TileShell, type TileState } from "./TileShell";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

type Row = { date: string; clicks: number; impressions: number; ctr: number; position: number };
type Resp = { rows: Row[]; totals: { clicks: number; impressions: number; ctr: number; position: number }; derived: Record<string, number>; row_count: number };

export function SearchPerformanceTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ["gsc_performance", range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/gsc/performance?range=${range}&compare=1`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? "Request failed");
      return r.json();
    },
  });

  let state: TileState = { status: "loading" };
  if (q.isError) state = { status: "error", message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: "empty" };
  else if (q.data) state = { status: "success" };

  return (
    <TileShell title="Search Performance" description="Clicks · impressions · CTR · position" state={state}>
      {q.data && (
        <div className="space-y-3">
          <div className="grid grid-cols-4 gap-2 text-sm">
            <div><div className="text-muted-foreground">Clicks</div><div className="text-lg font-semibold">{q.data.totals.clicks.toLocaleString()}</div></div>
            <div><div className="text-muted-foreground">Impressions</div><div className="text-lg font-semibold">{q.data.totals.impressions.toLocaleString()}</div></div>
            <div><div className="text-muted-foreground">CTR</div><div className="text-lg font-semibold">{(q.data.totals.ctr * 100).toFixed(2)}%</div></div>
            <div><div className="text-muted-foreground">Pos.</div><div className="text-lg font-semibold">{q.data.totals.position.toFixed(1)}</div></div>
          </div>
          <div className="h-32">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={q.data.rows}>
                <XAxis dataKey="date" hide />
                <YAxis hide />
                <Tooltip />
                <Line dataKey="clicks" type="monotone" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </TileShell>
  );
}
```

- [ ] **Step 2: TopQueriesTile**

```tsx
// frontend/app/(internal)/analytics/components/tiles/TopQueriesTile.tsx
"use client";
import { useQuery } from "@tanstack/react-query";
import { TileShell, type TileState } from "./TileShell";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

type Row = { query: string; clicks: number; impressions: number; ctr: number; position: number };
type Resp = { rows: Row[]; row_count: number };

export function TopQueriesTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ["gsc_top_queries", range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/gsc/top-queries?range=${range}&limit=10`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? "Request failed");
      return r.json();
    },
  });

  let state: TileState = { status: "loading" };
  if (q.isError) state = { status: "error", message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: "empty" };
  else if (q.data) state = { status: "success" };

  return (
    <TileShell title="Top Queries" description="Most-clicked search terms" state={state}>
      {q.data && (
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr><th>Query</th><th className="text-right">Clicks</th><th className="text-right">Pos.</th></tr>
          </thead>
          <tbody>
            {q.data.rows.map((r) => (
              <tr key={r.query} className="border-t">
                <td className="py-1 truncate max-w-[180px]" title={r.query}>{r.query}</td>
                <td className="text-right">{r.clicks.toLocaleString()}</td>
                <td className="text-right">{r.position.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </TileShell>
  );
}
```

- [ ] **Step 3: LandingPagesTile**

```tsx
// frontend/app/(internal)/analytics/components/tiles/LandingPagesTile.tsx
"use client";
import { useQuery } from "@tanstack/react-query";
import { TileShell, type TileState } from "./TileShell";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

type Row = { page: string; clicks: number; impressions: number; ctr: number; position: number };
type Resp = { rows: Row[]; row_count: number };

export function LandingPagesTile({ range }: { range: DateRangePreset }) {
  const q = useQuery({
    queryKey: ["gsc_landing_pages", range],
    queryFn: async (): Promise<Resp> => {
      const r = await fetch(`/api/internal/analytics/gsc/landing-pages?range=${range}&limit=10`);
      if (!r.ok) throw new Error((await r.json()).error?.message ?? "Request failed");
      return r.json();
    },
  });

  let state: TileState = { status: "loading" };
  if (q.isError) state = { status: "error", message: (q.error as Error).message, retry: () => q.refetch() };
  else if (q.data && q.data.row_count === 0) state = { status: "empty" };
  else if (q.data) state = { status: "success" };

  return (
    <TileShell title="Landing Pages" description="Top pages from search" state={state}>
      {q.data && (
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr><th>Page</th><th className="text-right">Clicks</th><th className="text-right">CTR</th></tr>
          </thead>
          <tbody>
            {q.data.rows.map((r) => (
              <tr key={r.page} className="border-t">
                <td className="py-1 truncate max-w-[180px]" title={r.page}>{r.page}</td>
                <td className="text-right">{r.clicks.toLocaleString()}</td>
                <td className="text-right">{(r.ctr * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </TileShell>
  );
}
```

- [ ] **Step 4: Smoke test**

```bash
cd C:/PitchRank/frontend && npm run dev
```

Visit `/analytics` as admin. All six tiles should render with real data within ~15s. ChatSidebar will throw — that's Phase 4.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank/frontend && git add app/\(internal\)/analytics/components/tiles/ && git commit -m "feat(analytics): add SearchPerformance, TopQueries, LandingPages tiles"
```

---

# Phase 4 — Chat

Goal: Streaming Claude chat sidebar with three constrained tools, full logging, date-context inheritance.

## Task 4.1 — Chat tools module + system prompt

**Files:**
- Create: `frontend/lib/internal-analytics/chat/tools.ts`
- Create: `frontend/lib/internal-analytics/chat/system-prompt.ts`

- [ ] **Step 1: Implement system prompt**

```ts
// frontend/lib/internal-analytics/chat/system-prompt.ts
import type { DateRange } from "../types";

export function buildSystemPrompt(inheritedRange: DateRange): string {
  return `You are an analytics assistant for PitchRank, a youth soccer ranking platform.

Data sources:
- GA4 (property 514724174) — traffic, pageviews, events, conversions
- Google Search Console (sc-domain:pitchrank.io) — queries, clicks, impressions, CTR, position

Common mappings (prefer these named reports):
- "traffic", "users", "visitors", "sessions" -> ga4_traffic_overview
- "top pages", "most viewed", "popular pages" -> ga4_top_pages
- "conversions", "upgrade", "upgrade page", "pricing views" -> ga4_upgrade_views
- "search performance", "SEO", "search traffic", "Google" -> gsc_performance
- "queries", "keywords", "search terms", "ranking for" -> gsc_top_queries
- "landing pages from search", "which pages get clicks" -> gsc_landing_pages

Only use query_ga4 / query_gsc if you are CERTAIN no named report can answer the question.

Default limits when unspecified: top/ranked lists -> 10; broader exploration -> 30.

No-data handling: if a tool returns no rows, say so clearly and suggest a wider date range or different dimension.

GSC freshness: GSC has a 2-3 day reporting lag. If the user asks about "today" or "yesterday", mention the lag and show the most recent complete data. Honor the data_freshness field in tool results.

Errors: on retryable=false, report to user. On retryable=true, retry once with backoff. NEVER retry VALIDATION errors — fix the args.

The user's current dashboard date range is: ${JSON.stringify(inheritedRange)}. Use this unless the user specifies otherwise in their question.

Numbers are pre-rounded by the tool. Do not reformat them. Show deltas when available. Be concise — answer the question, then offer one follow-up suggestion.`;
}
```

- [ ] **Step 2: Implement tools module**

```ts
// frontend/lib/internal-analytics/chat/tools.ts
import "server-only";
import { z } from "zod";
import { tool } from "ai";
import { runReport, type ReportKey } from "../report-registry";
import { ALLOWED_GA4_METRICS, ALLOWED_GA4_DIMENSIONS, ALLOWED_GSC_METRICS, ALLOWED_GSC_DIMENSIONS, MAX_ROW_LIMIT, DATE_RANGE_PRESETS } from "../constants";
import { getAnalyticsDataClient } from "@/lib/google-auth";
import { GA4_PROPERTY_ID, GSC_SITE_URL } from "../constants";
import { getSearchConsoleClient } from "@/lib/google-auth";
import { resolveDateRange } from "../dates";
import { ga4RowsToObjects } from "../transforms/ga4";
import { gscRowsToObjects } from "../transforms/gsc";
import { TaxonomyAwareError, toTaxonomyError } from "../queries/_error";
import { hashToolCall, logChatToolCall } from "../logging";
import type { DateRange } from "../types";

const DateRangeArg = z.union([
  z.enum(DATE_RANGE_PRESETS as readonly [string, ...string[]]),
  z.object({ start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/), end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/) }),
]);

type ToolContext = {
  turnId: string;
  userEmail: string;
  modelName: string;
  question: string;
  inheritedRange: DateRange;
  forceFresh: boolean;
};

export function buildTools(ctx: ToolContext) {
  return {
    run_named_report: tool({
      description: "Run a pre-defined analytics report. Prefer this over raw queries when the question matches a known report.",
      parameters: z.object({
        report: z.enum(["ga4_traffic_overview", "ga4_top_pages", "ga4_upgrade_views", "gsc_performance", "gsc_top_queries", "gsc_landing_pages"]),
        date_range: DateRangeArg,
        compare_to_previous: z.boolean().optional(),
        limit: z.number().int().min(1).max(MAX_ROW_LIMIT).optional(),
      }),
      execute: async (args) => runWithLog(ctx, "run_named_report", args, async () => {
        const params = { ...args, forceFresh: ctx.forceFresh };
        return await runReport(args.report as ReportKey, params);
      }),
    }),

    query_ga4: tool({
      description: "Run a custom GA4 query. Use only when no named report fits.",
      parameters: z.object({
        metrics: z.array(z.enum(ALLOWED_GA4_METRICS as readonly [string, ...string[]])).min(1).max(5),
        dimensions: z.array(z.enum(ALLOWED_GA4_DIMENSIONS as readonly [string, ...string[]])).max(3).optional(),
        date_range: DateRangeArg,
        filter: z.object({
          dimension: z.enum(ALLOWED_GA4_DIMENSIONS as readonly [string, ...string[]]),
          match_type: z.enum(["EXACT", "CONTAINS", "BEGINS_WITH"]),
          value: z.string(),
        }).optional(),
        order_by: z.object({ metric: z.enum(ALLOWED_GA4_METRICS as readonly [string, ...string[]]), desc: z.boolean() }).optional(),
        limit: z.number().int().min(1).max(MAX_ROW_LIMIT),
      }),
      execute: async (args) => runWithLog(ctx, "query_ga4", args, async () => {
        const range = resolveDateRange(args.date_range as never, "America/Phoenix");
        try {
          const client = getAnalyticsDataClient();
          const res = await client.properties.runReport({
            property: `properties/${GA4_PROPERTY_ID}`,
            requestBody: {
              dateRanges: [{ startDate: range.start, endDate: range.end }],
              metrics: args.metrics.map((name) => ({ name })),
              dimensions: args.dimensions?.map((name) => ({ name })),
              dimensionFilter: args.filter ? { filter: { fieldName: args.filter.dimension, stringFilter: { matchType: args.filter.match_type, value: args.filter.value } } } : undefined,
              orderBys: args.order_by ? [{ metric: { metricName: args.order_by.metric }, desc: args.order_by.desc }] : undefined,
              limit: String(args.limit),
            },
          });
          return { source: "ga4", rows: ga4RowsToObjects(res.data as never), date_range: range };
        } catch (e) { throw new TaxonomyAwareError(toTaxonomyError(e)); }
      }),
    }),

    query_gsc: tool({
      description: "Run a custom Search Console Search Analytics query. Use only when no named report fits.",
      parameters: z.object({
        dimensions: z.array(z.enum(ALLOWED_GSC_DIMENSIONS as readonly [string, ...string[]])).min(1).max(3),
        date_range: DateRangeArg,
        filters: z.array(z.object({
          dimension: z.enum(ALLOWED_GSC_DIMENSIONS as readonly [string, ...string[]]),
          operator: z.enum(["equals", "contains", "notEquals", "notContains"]),
          expression: z.string(),
        })).optional(),
        limit: z.number().int().min(1).max(MAX_ROW_LIMIT),
      }),
      execute: async (args) => runWithLog(ctx, "query_gsc", args, async () => {
        const range = resolveDateRange(args.date_range as never, "America/Phoenix");
        try {
          const client = getSearchConsoleClient();
          const res = await client.searchanalytics.query({
            siteUrl: GSC_SITE_URL,
            requestBody: {
              startDate: range.start,
              endDate: range.end,
              dimensions: args.dimensions,
              dimensionFilterGroups: args.filters ? [{ filters: args.filters }] : undefined,
              rowLimit: args.limit,
            },
          });
          return { source: "gsc", rows: gscRowsToObjects(res.data as never, args.dimensions), date_range: range };
        } catch (e) { throw new TaxonomyAwareError(toTaxonomyError(e)); }
      }),
    }),
  };
}

async function runWithLog<T>(ctx: ToolContext, toolName: string, args: unknown, fn: () => Promise<T>): Promise<T | { error: any }> {
  const start = Date.now();
  try {
    const result = await fn();
    await logChatToolCall({
      turn_id: ctx.turnId, user_email: ctx.userEmail, model_name: ctx.modelName,
      user_question: ctx.question, inherited_date_range: ctx.inheritedRange, overridden_date_range: null,
      tool_name: toolName, tool_args: args,
      tool_result_summary: summarize(result),
      force_fresh: ctx.forceFresh, execution_ms: Date.now() - start, success: true,
    });
    return result;
  } catch (e) {
    const taxonomy = e instanceof TaxonomyAwareError ? e.taxonomy : { type: "API_ERROR" as const, message: String(e), retryable: false };
    await logChatToolCall({
      turn_id: ctx.turnId, user_email: ctx.userEmail, model_name: ctx.modelName,
      user_question: ctx.question, inherited_date_range: ctx.inheritedRange, overridden_date_range: null,
      tool_name: toolName, tool_args: args, tool_result_summary: null,
      force_fresh: ctx.forceFresh, execution_ms: Date.now() - start, success: false, error: taxonomy,
    });
    return { error: taxonomy };
  }
}

function summarize(result: any) {
  if (!result || typeof result !== "object") return null;
  return {
    row_count: Array.isArray(result.rows) ? result.rows.length : undefined,
    has_totals: !!result.totals,
    truncated: !!result.truncated,
  };
}
```

- [ ] **Step 3: Verify and commit**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json && git add lib/internal-analytics/chat/ && git commit -m "feat(analytics): add chat tools with logging and system prompt"
```

---

## Task 4.2 — Chat route handler

**Files:**
- Create: `frontend/app/api/internal/analytics/chat/route.ts`

- [ ] **Step 1: Implement**

```ts
// frontend/app/api/internal/analytics/chat/route.ts
import { streamText } from "ai";
import { anthropic } from "@ai-sdk/anthropic";
import { requireAdmin } from "@/lib/supabase/admin";
import { resolveDateRange } from "@/lib/internal-analytics/dates";
import { buildTools } from "@/lib/internal-analytics/chat/tools";
import { buildSystemPrompt } from "@/lib/internal-analytics/chat/system-prompt";
import { newTurnId } from "@/lib/internal-analytics/logging";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

export const runtime = "nodejs";
export const maxDuration = 60;
export const dynamic = "force-dynamic";

const FRESH_INTENT = /\b(today|right now|just now|this minute|this hour)\b/i;

export async function POST(req: Request) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;

  const body = await req.json();
  const { messages, range = "last_7_days" } = body as { messages: any[]; range?: DateRangePreset };
  const userMessage = messages[messages.length - 1]?.content ?? "";
  const forceFresh = typeof userMessage === "string" && FRESH_INTENT.test(userMessage);

  const inheritedRange = resolveDateRange(range, "America/Phoenix");
  const turnId = newTurnId();
  const userEmail = auth.user.email ?? "unknown@pitchrank.io";
  const modelName = "claude-sonnet-4-6";

  const tools = buildTools({ turnId, userEmail, modelName, question: typeof userMessage === "string" ? userMessage : "", inheritedRange, forceFresh });

  const result = await streamText({
    model: anthropic(modelName),
    system: buildSystemPrompt(inheritedRange),
    messages,
    tools,
    maxSteps: 5,
  });

  return result.toDataStreamResponse();
}
```

- [ ] **Step 2: Confirm `ANTHROPIC_API_KEY` env var is documented**

Add to local `.env.local` (manually, do not commit):
```
ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank/frontend && git add app/api/internal/analytics/chat/ && git commit -m "feat(analytics): add streaming chat route handler"
```

---

## Task 4.3 — ChatSidebar + DateContextChip

**Files:**
- Create: `frontend/app/(internal)/analytics/components/chat/DateContextChip.tsx`
- Create: `frontend/app/(internal)/analytics/components/chat/ChatSidebar.tsx`

- [ ] **Step 1: DateContextChip**

```tsx
// frontend/app/(internal)/analytics/components/chat/DateContextChip.tsx
"use client";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

const LABELS: Record<DateRangePreset, string> = {
  today: "Today",
  last_7_days: "Last 7 days",
  last_28_days: "Last 28 days",
  mtd: "Month to date",
};

export function DateContextChip({ range }: { range: DateRangePreset }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
      Using: {LABELS[range]}
    </span>
  );
}
```

- [ ] **Step 2: ChatSidebar**

```tsx
// frontend/app/(internal)/analytics/components/chat/ChatSidebar.tsx
"use client";
import { useChat } from "ai/react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { DateContextChip } from "./DateContextChip";
import type { DateRangePreset } from "@/lib/internal-analytics/types";

export function ChatSidebar({ range }: { range: DateRangePreset }) {
  const { messages, input, handleInputChange, handleSubmit, isLoading } = useChat({
    api: "/api/internal/analytics/chat",
    body: { range },
  });

  return (
    <Card className="h-[calc(100vh-8rem)] flex flex-col">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Ask your data</CardTitle>
        <DateContextChip range={range} />
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto space-y-3 text-sm">
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "text-foreground" : "text-muted-foreground"}>
            <div className="font-medium text-xs uppercase opacity-60">{m.role}</div>
            <div className="whitespace-pre-wrap">{m.content}</div>
            {m.toolInvocations?.map((t) => (
              <details key={t.toolCallId} className="mt-1 text-xs">
                <summary className="cursor-pointer">🔍 {t.toolName}</summary>
                <pre className="text-xs overflow-x-auto">{JSON.stringify(t.args, null, 2)}</pre>
              </details>
            ))}
          </div>
        ))}
      </CardContent>
      <form onSubmit={handleSubmit} className="p-3 border-t flex gap-2">
        <Input value={input} onChange={handleInputChange} placeholder="Ask about traffic, queries, conversions…" disabled={isLoading} />
        <Button type="submit" disabled={isLoading || !input.trim()}>Send</Button>
      </form>
    </Card>
  );
}
```

- [ ] **Step 3: Smoke test the 5 baseline questions**

```bash
cd C:/PitchRank/frontend && npm run dev
```

In the browser:
1. "What was my traffic last week?"
2. "What are my top 5 pages this month?"
3. "How did search performance change vs the previous period?"
4. "What keywords drove the most clicks in the last 28 days?"
5. "How many people viewed the /upgrade page today?"

Each should produce a streamed answer. Check `analytics_chat_logs` in Supabase to confirm rows are written.

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank/frontend && git add app/\(internal\)/analytics/components/chat/ && git commit -m "feat(analytics): add ChatSidebar with streaming useChat and DateContextChip"
```

---

# Phase 5 — Polish & ship

## Task 5.1 — Tile state polish + manual refresh button

**Files:**
- Modify: `frontend/app/(internal)/analytics/components/DashboardGrid.tsx`

- [ ] **Step 1: Add a "Refresh" button to the DashboardGrid header**

In `DashboardGrid.tsx`, replace the header line:

```tsx
<div className="flex items-center justify-between">
  <h1 className="text-2xl font-semibold">Internal Analytics</h1>
  <DateRangePicker />
</div>
```

with:

```tsx
<div className="flex items-center justify-between">
  <h1 className="text-2xl font-semibold">Internal Analytics</h1>
  <div className="flex items-center gap-2">
    <DateRangePicker />
    <Button
      variant="outline"
      size="sm"
      onClick={async () => {
        await fetch("/api/internal/analytics/refresh", { method: "POST" });
        client.invalidateQueries();
      }}
    >
      Refresh
    </Button>
  </div>
</div>
```

Add the `Button` import at the top:
```tsx
import { Button } from "@/components/ui/button";
```

- [ ] **Step 2: Smoke test refresh flow**

In dev: change a tile's URL range, click Refresh, observe network requests fire fresh and React Query caches invalidate.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank/frontend && git add app/\(internal\)/analytics/components/DashboardGrid.tsx && git commit -m "feat(analytics): add Refresh button that busts server + client caches"
```

---

## Task 5.2 — Run the full manual verification checklist

- [ ] **Step 1: Run the verification checklist**

In `frontend/`:

```bash
npm run dev
```

Tick each item off the spec's manual-verification list:

- [ ] Logged out → `/analytics` redirects to `/login?next=/analytics`
- [ ] Logged in as a non-admin → `/analytics` redirects to `/`
- [ ] Logged in as admin → page renders, all 6 tiles reach success state within 15s
- [ ] All four date range presets work (Today, 7 days, 28 days, MTD)
- [ ] Refresh button clears caches and refetches
- [ ] All 5 baseline chat questions return correct answers
- [ ] Tool call rows appear in `analytics_chat_logs` (check via Supabase dashboard)

- [ ] **Step 2: Run the unit test suite**

```bash
cd C:/PitchRank/frontend && npx vitest run lib/internal-analytics/
```

Expected: all green.

- [ ] **Step 3: Run typecheck**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit -p tsconfig.json
```

Expected: zero new errors in `lib/internal-analytics/`, `app/(internal)/analytics/`, `app/api/internal/analytics/`.

- [ ] **Step 4: Run linter**

```bash
cd C:/PitchRank/frontend && npm run lint
```

Fix any new warnings/errors. Commit any lint-fix changes.

```bash
cd C:/PitchRank/frontend && git add -u && git commit -m "chore(analytics): lint cleanup" || true
```

---

## Task 5.3 — Deploy to Vercel and verify

**Files:**
- (Vercel dashboard env vars; no file changes)

- [ ] **Step 1: Add required env vars to Vercel project (Production + Preview)**

Required:
- `GOOGLE_SERVICE_ACCOUNT_JSON` — base64-encoded service account JSON (already used for SEO scripts; verify presence)
- `ANTHROPIC_API_KEY` — for Claude
- `SUPABASE_SERVICE_KEY` — already present (used for chat-log inserts)
- `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` — already present

Verify via Vercel CLI:
```bash
cd C:/PitchRank/frontend && vercel env ls
```

Add any missing keys with `vercel env add <name> production preview`.

- [ ] **Step 2: Push branch and merge**

```bash
cd C:/PitchRank && git push -u origin feat/internal-analytics-dashboard
```

Open PR to `main`, request review, merge.

- [ ] **Step 3: Verify production deploy**

After Vercel deploy, log in to production as admin → visit `https://www.pitchrank.io/analytics` → run through the same manual verification list as Task 5.2 against production data.

- [ ] **Step 4: Shadow-use period**

Use the dashboard daily for 1 week. Note any rough edges, missing reports, or chat misfires in `docs/superpowers/2026-04-14-pitchrank-analytics-dashboard-design.md` under a new "Post-launch notes" section. Use that to drive v2 priorities.

---

# Self-review

**Spec coverage check:**
- ✅ Architecture (Section: Architecture in spec) → Tasks 1.5, 3.2 (route group + grid + chat layout)
- ✅ Three-layer admin gating → Task 1.5 (middleware + layout) + every API route includes `requireAdmin()` (Tasks 2.11, 3.3, 3.4, 4.2)
- ✅ Lazy memoized Google clients → Reused `lib/google-auth.ts` (already memoized)
- ✅ Six tiles → Tasks 3.5, 3.6, 3.7
- ✅ Shared report registry → Task 2.10
- ✅ `unstable_cache` with stable keys + tag-based invalidation → All query tasks (2.4–2.9)
- ✅ React Query staleTime 5 min, gcTime 15 min → Task 3.2 (DashboardGrid)
- ✅ Manual refresh button → Task 5.1
- ✅ In-flight coalescing → Task 2.3
- ✅ Cache bypass for chat (`forceFresh`) → Task 4.2 (chat route detects freshness intent) + every query function honors it
- ✅ Centralized derived metrics + trend → Task 2.1 (trend), 2.2 (deltas), used in Tasks 2.4, 2.7
- ✅ Standardized error taxonomy → Task 1.3
- ✅ Previous-period guardrail (>90 days) → Tasks 2.4, 2.6, 2.7 (each query)
- ✅ GSC end-date snap-to-`today-2` + warning → Tasks 2.7, 2.8, 2.9
- ✅ `data_freshness` field on every TileResponse → Tasks 2.4–2.9
- ✅ `generated_at`, `timezone`, `debug.cost` on every response → Tasks 2.4–2.9
- ✅ Truncation reason → Tasks 2.5, 2.8, 2.9
- ✅ Empty-dataset normalization (zero rows still returns `totals: {}`, `derived: {}`, etc.) → All query tasks
- ✅ Chat tools (3): `run_named_report`, `query_ga4`, `query_gsc` → Task 4.1
- ✅ Constrained metric/dimension allowlists → Task 1.2 (constants), enforced in Task 4.1
- ✅ Hard limit cap of 100 → Task 1.2 + every query
- ✅ Hard-coded `pagePath == "/upgrade"` for upgrade-views → Task 2.6
- ✅ System prompt with semantic intent mapping → Task 4.1 (system-prompt.ts)
- ✅ `analytics_chat_logs` table + `tool_call_hash` column → Task 1.4
- ✅ `forceFresh` gated to chat route only (tile routes do not pass it) → Tasks 3.3, 3.4 (no forceFresh) vs Task 4.2 (sets it)
- ✅ Streaming chat with tool-call inline cards → Task 4.3
- ✅ DateContextChip → Task 4.3
- ✅ Meta endpoint → Task 2.11
- ✅ Migration uses next sequential number → Task 1.4 (`004_…`)
- ✅ Testing: unit tests on dates, error taxonomy, transforms, trend, coalesce → Tasks 1.2, 1.3, 2.1, 2.2, 2.3
- ✅ Manual verification checklist → Task 5.2
- ✅ Rollout phases match spec phases → Phases 1-5

**Placeholder scan:** No `TBD`, `TODO`, "fill in later", or unspecified error handling. Every step has executable code or commands.

**Type consistency:** `TileResponse<Row>` shape, `DateRange`, `DateRangePreset` used identically across query files, registry, route handlers, and tile components. `Ga4OverviewRow`, `GscPerformanceRow`, etc. defined in their own query files and re-imported by tiles. `runReport` signature consistent.

**Open questions resolved during exploration (per spec):**
- React Query installed: ✅ `@tanstack/react-query 5.90.7`
- Existing admin gating: ✅ `requireAdmin()` at `lib/supabase/admin.ts` (DB-based)
- GA4 service account access: assumed yes per memory; verified at first integration test in Task 5.2
- Index-coverage feasibility: deferred to URL Inspection API; Task 2.9 ships top landing pages instead, registry uses `gsc_landing_pages` from day one

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-14-internal-analytics-dashboard.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
