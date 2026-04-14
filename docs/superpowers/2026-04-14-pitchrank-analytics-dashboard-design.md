# PitchRank Analytics Dashboard — Design

**Date:** 2026-04-14
**Owner:** Dallas Heidt
**Status:** Approved design, ready for implementation planning

## Summary

An admin-only analytics dashboard inside the PitchRank Next.js frontend that surfaces GA4 and Google Search Console data, paired with a chat sidebar backed by a tool-calling LLM (Claude Sonnet 4.6 via the Vercel AI SDK). The dashboard is the primary surface; the chat lets Dallas ask natural-language questions that route through the same canonical report functions used by the tiles.

Lives at `(internal)/analytics` in the existing Next.js app, gated by an `ADMIN_EMAILS` env var allowlist enforced at three layers (middleware, layout, every API route).

## Goals

- See traffic, search performance, and conversion health in one place without opening GA4 and GSC separately.
- Ask plain-English questions ("how did my top pages do this week?") and get grounded, data-backed answers.
- Stay inside the existing PitchRank app (single auth, single deploy, no separate service).
- Low-friction tile set that can evolve over time.

## Non-goals (v1)

- Hot-report precompute cron
- Precomputed daily aggregates in Supabase for > 90-day comparisons
- `explain_data` reasoning tool
- Chat history persistence across sessions (in-memory only for v1)
- Additional tiles beyond the six agreed (country/device breakdown, conversions beyond `/upgrade`, etc.)
- Mobile-optimized layout polish
- Multi-user chat with per-user state
- Exporting reports (CSV/PDF)
- Alerts / anomaly detection
- A/B model swapping via AI Gateway

## Architecture

**Location:** New route group at `frontend/app/(internal)/analytics/`. Not linked from public nav.

**Runtime:** Node runtime for all route handlers (Google SDKs are not Edge-compatible). Page is a Server Component rendering the dashboard shell; tiles and chat are Client Components fetching from internal API routes.

**External services:**
- Google Analytics Data API (GA4) via `@google-analytics/data` — property `514724174`
- Google Search Console API via `googleapis` — site `sc-domain:pitchrank.io`
- Anthropic Claude via Vercel AI SDK (`ai` + `@ai-sdk/anthropic`), model `claude-sonnet-4-6`

**Auth:** Single service account JSON stored base64-encoded in env var `GOOGLE_SERVICE_ACCOUNT_JSON`, decoded lazily inside memoized client factories in `lib/analytics/google-clients.ts`. Same account has both GA4 and GSC access.

**Admin gating — three layers, non-negotiable:**
1. `middleware.ts` — returns 404 for non-admins on `(internal)/*` and `/api/internal/analytics/*`
2. `layout.tsx` — server-side `requireAdmin()` before rendering the page
3. Every `/api/internal/analytics/*` route — `requireAdmin()` at the top of the handler

**Data flow:**
1. Dashboard loads → six tiles fire parallel requests to their API routes → routes call shared report handlers → handlers call GA4/GSC → return normalized JSON → tile renders.
2. Chat: user types → `/api/internal/analytics/chat` streams from Claude with tools `run_named_report`, `query_ga4`, `query_gsc` → Claude calls tools as needed → final answer streams back to the sidebar.

## File structure

```
frontend/
├── middleware.ts                              # extended; gate (internal)/*
├── lib/
│   └── analytics/
│       ├── google-clients.ts                  # lazy memoized GA4 + GSC clients
│       ├── dates.ts                           # resolveDateRange, previousPeriod, detectFreshness, todayInPropertyTz
│       ├── admin.ts                           # requireAdmin() helper
│       ├── logging.ts                         # logChatToolCall()
│       ├── types.ts                           # DateRange, TileResponse<T>, Ga4Row, GscRow, ChatToolArgs, ChatToolResult
│       ├── constants.ts                       # GA4_PROPERTY_ID, GSC_SITE_URL, ALLOWED_*, DEFAULT_ROW_LIMIT, DATE_RANGE_PRESETS
│       ├── report-registry.ts                 # canonical reports, runReport(key, params)
│       ├── transforms/
│       │   ├── ga4.ts                         # raw → normalized row shape
│       │   ├── gsc.ts                         # raw → normalized; computeGscDeltas
│       │   └── trend.ts                       # computeTrend(series) → direction + strength
│       ├── queries/
│       │   ├── _coalesce.ts                   # in-flight request deduping
│       │   ├── _error.ts                      # toTaxonomyError()
│       │   ├── ga4-overview.ts
│       │   ├── ga4-top-pages.ts
│       │   ├── ga4-upgrade-views.ts
│       │   ├── gsc-performance.ts
│       │   ├── gsc-top-queries.ts
│       │   └── gsc-landing-pages.ts           # formerly gsc_index_coverage; see Open Questions
│       └── chat/
│           ├── tools.ts                       # query_ga4, query_gsc, run_named_report
│           └── system-prompt.ts
├── app/(internal)/
│   └── analytics/
│       ├── layout.tsx                         # server, calls requireAdmin()
│       ├── page.tsx                           # server, renders shell
│       └── components/
│           ├── DateRangePicker.tsx            # Today / 7d / 28d / MTD
│           ├── DashboardGrid.tsx              # owns date range, URL-synced
│           ├── tiles/
│           │   ├── TrafficOverviewTile.tsx
│           │   ├── TopPagesTile.tsx
│           │   ├── UpgradeViewsTile.tsx
│           │   ├── SearchPerformanceTile.tsx
│           │   ├── TopQueriesTile.tsx
│           │   └── LandingPagesTile.tsx
│           └── chat/
│               ├── ChatSidebar.tsx            # Vercel AI SDK useChat
│               └── DateContextChip.tsx
└── app/api/internal/analytics/
    ├── meta/route.ts                          # available ranges, default, refresh timestamps, identity labels
    ├── refresh/route.ts                       # revalidateTag for analytics:ga4 and analytics:gsc
    ├── ga4/overview/route.ts
    ├── ga4/top-pages/route.ts
    ├── ga4/upgrade-views/route.ts
    ├── gsc/performance/route.ts
    ├── gsc/top-queries/route.ts
    ├── gsc/landing-pages/route.ts
    └── chat/route.ts                          # streaming, tool-calling
```

## Shared data layer

### Query function pattern

Every file in `lib/analytics/queries/` exports the same shape:

```ts
export type Ga4TopPagesParams = {
  dateRange: DateRange;
  limit?: number;               // default 10
  compareToPrevious?: boolean;  // default false
  forceFresh?: boolean;         // gated: chat route only, stripped by tile routes
};

export type Ga4TopPagesResult = TileResponse<{
  pagePath: string;
  pageTitle: string;
  screenPageViews: number;
  activeUsers: number;
  engagementRate: number;
}>;

async function fetchGa4TopPagesRaw(params): Promise<RawResponse> { /* network */ }
function normalizeGa4TopPages(raw, params): Ga4TopPagesResult { /* pure */ }

export const getGa4TopPages = (params: Ga4TopPagesParams) => {
  const cacheKey = ["ga4_top_pages", JSON.stringify(sortedKeys(params))];
  const run = async () => {
    const raw = await fetchGa4TopPagesRaw(params);
    return normalizeGa4TopPages(raw, params);
  };
  if (params.forceFresh) return coalesce(cacheKey.join(":"), run);
  return unstable_cache(
    () => coalesce(cacheKey.join(":"), run),
    cacheKey,
    { revalidate: 600, tags: ["analytics:ga4", "analytics:ga4_top_pages"] },
  )();
};
```

Raw fetch and normalize are separately unit-testable. Normalizers are pure — no clock calls, no `todayInPropertyTz()`; all date logic stays in the public wrapper.

### Caching

| Layer | TTL | Keyed by | Invalidation |
|---|---|---|---|
| `unstable_cache` | 10 min | function name + sorted JSON of params | Tag-based |
| React Query (client) | `staleTime` 5 min, `gcTime` 15 min | report key + params | On date range change |
| In-flight coalescing | request lifetime | function + params | Automatic on resolve |

**Manual refresh:** "Refresh" button in dashboard header → POST `/api/internal/analytics/refresh` → `revalidateTag("analytics:ga4")` + `revalidateTag("analytics:gsc")` → all tiles refetch. Dashboard meta shows `last_refreshed_at` per source.

**Cache bypass for chat (`forceFresh`):** Only the chat route handler may set this (tile routes strip it). Triggered when the user question contains freshness intent ("today", "right now", "just now"). Claude's tool schema does not expose the flag. Logged to `analytics_chat_logs.force_fresh`.

### Report registry

```ts
export const REPORTS = {
  ga4_traffic_overview: {
    source: "ga4",
    description: "Sessions, active users, and pageviews over time with totals and trend.",
    paramsSchema: Ga4OverviewParamsSchema,
    handler: getGa4Overview,
    summaryRequired: ["totals", "trend_direction"],
    derivedMetrics: ["wow_delta", "trend_direction"],
  },
  ga4_top_pages: {
    source: "ga4",
    description: "Top pages by pageviews with engagement rate.",
    paramsSchema: Ga4TopPagesParamsSchema,
    handler: getGa4TopPages,
    summaryRequired: ["totals"],
  },
  ga4_upgrade_views: {
    source: "ga4",
    description: "Pageviews of /upgrade and conversion rate vs total sessions.",
    paramsSchema: Ga4UpgradeViewsParamsSchema,
    handler: getGa4UpgradeViews,
    summaryRequired: ["totals", "conversion_rate"],
    derivedMetrics: ["conversion_rate"],
  },
  gsc_performance: {
    source: "gsc",
    description: "Clicks, impressions, CTR, and position over time with period-over-period deltas.",
    paramsSchema: GscPerformanceParamsSchema,
    handler: getGscPerformance,
    summaryRequired: ["totals", "ctr_delta", "impressions_delta", "position_delta"],
    derivedMetrics: ["ctr_delta", "clicks_delta", "impressions_delta", "position_delta"],
  },
  gsc_top_queries: {
    source: "gsc",
    description: "Top search queries by clicks with CTR and average position.",
    paramsSchema: GscTopQueriesParamsSchema,
    handler: getGscTopQueries,
    summaryRequired: ["totals"],
  },
  gsc_landing_pages: {
    source: "gsc",
    description: "Top landing pages receiving search traffic (may display as Index Coverage in UI).",
    paramsSchema: GscLandingPagesParamsSchema,
    handler: getGscLandingPages,
    experimental: true,
  },
} as const;

export async function runReport<K extends keyof typeof REPORTS>(
  key: K,
  params: InferParams<K>,
): Promise<TileResponse<any>> {
  const report = REPORTS[key];
  const validated = report.paramsSchema.parse(params);
  return report.handler(validated);
}
```

Tiles and the chat `run_named_report` tool both go through `runReport()`. Single source of truth.

### Uniform response shape

Every `TileResponse` returns:

```ts
{
  report?: string,                       // e.g., "ga4_top_pages"
  source: "ga4" | "gsc",
  date_range: { start, end, preset? },
  timezone: string,                      // from GA4 property
  rows: Row[],
  row_count: number,
  totals: Record<string, number>,        // empty object when no data
  derived: Record<string, number | string>,  // trend_direction, *_delta, conversion_rate
  previous_period?: { rows, totals, derived },
  truncated: boolean,
  truncation_reason?: "limit_reached" | "api_max" | "post_filter",
  available_rows_hint?: number,
  data_freshness: "complete" | "partial",
  warnings: string[],
  generated_at: string,                  // ISO 8601
  debug?: { cost: { estimated_units, range_days, metric_count, dimension_count, limit } },
}
```

### Derived metrics (computed centrally)

- `conversion_rate = upgrade_views / sessions`
- `ctr_delta` = absolute percentage-point change
- `clicks_delta`, `impressions_delta`, `position_delta` (note: lower position is better, sign is flipped)
- `trend_direction: "up" | "down" | "flat"` + `trend_strength: number` (0..1, from linear regression slope normalized by mean)

### Freshness detection

```ts
function detectFreshness(source, dateRange): { freshness, warnings } {
  const today = todayInPropertyTz();
  if (source === "gsc" && dateRange.end >= addDays(today, -2)) {
    return { freshness: "partial", warnings: [`GSC data has a 2-3 day lag; results through ${dateRange.end} are incomplete.`] };
  }
  if (source === "ga4" && dateRange.end >= today) {
    return { freshness: "partial", warnings: ["GA4 data for today is still being collected."] };
  }
  return { freshness: "complete", warnings: [] };
}
```

### Error taxonomy

```ts
{
  error: {
    type: "VALIDATION" | "RATE_LIMIT" | "API_ERROR" | "NO_DATA" | "AUTH" | "QUOTA",
    message: string,          // plain-English, user-facing
    retryable: boolean,
    retry_after_ms?: number,  // for RATE_LIMIT
  }
}
```

`toTaxonomyError()` maps Google SDK errors: 429 → RATE_LIMIT, 403 → AUTH, 400 → VALIDATION, else → API_ERROR.

### Previous-period guardrail

```ts
if (params.compareToPrevious && rangeDays(params.dateRange) > 90) {
  throw { type: "VALIDATION", retryable: false,
          message: "Comparison disabled for ranges over 90 days (doubles API calls)." };
}
```

### Timezone normalization

At client init, `google-clients.ts` fetches the GA4 property timezone and caches it. `todayInPropertyTz()` is the single source for "today" across dates + freshness. GSC is UTC; mismatch is logged as a startup warning. Every response includes a `timezone` field so discrepancies are visible.

## Chat design

### Model + SDK

`claude-sonnet-4-6` via `@ai-sdk/anthropic`. Streaming enabled. Prompt caching on system prompt + tool schemas (long-lived).

### Tools (priority order)

#### 1. `run_named_report` (preferred)

```ts
{
  name: "run_named_report",
  description: "Run a pre-defined analytics report. Prefer this over raw queries when the question matches a known report.",
  parameters: {
    report: enum([
      "ga4_traffic_overview",
      "ga4_top_pages",
      "ga4_upgrade_views",
      "gsc_performance",
      "gsc_top_queries",
      "gsc_landing_pages",
    ]),
    date_range: DateRangeSchema,
    compare_to_previous: boolean?,
    limit: int 1..100?,
  }
}
```

#### 2. `query_ga4` (escape hatch)

```ts
{
  parameters: {
    metrics: array(enum(ALLOWED_GA4_METRICS), min 1, max 5),
    dimensions: array(enum(ALLOWED_GA4_DIMENSIONS), max 3)?,
    date_range: DateRangeSchema,
    filter: { dimension, match_type: "EXACT"|"CONTAINS"|"BEGINS_WITH", value }?,
    order_by: { metric, desc }?,
    limit: int 1..100,        // REQUIRED
  }
}
```

`ALLOWED_GA4_METRICS`: `activeUsers`, `sessions`, `screenPageViews`, `engagementRate`, `averageSessionDuration`, `bounceRate`, `eventCount`.
`ALLOWED_GA4_DIMENSIONS`: `date`, `pagePath`, `pageTitle`, `country`, `deviceCategory`, `sessionSource`, `sessionMedium`, `eventName`.

#### 3. `query_gsc` (escape hatch)

```ts
{
  parameters: {
    metrics: array(enum("clicks", "impressions", "ctr", "position"))?,
    dimensions: array(enum("date", "query", "page", "country", "device"), max 3),
    date_range: DateRangeSchema,
    filters: array({ dimension, operator: "equals"|"contains"|"notEquals"|"notContains", expression })?,
    limit: int 1..100,        // REQUIRED
  }
}
```

### Hard guardrails

- Date range ≤ 16 months (GA4 + GSC API limits).
- GSC end date of "today" auto-snaps to `today - 2` with a warning.
- `limit` capped at 100.
- Non-allowlisted metric/dimension → VALIDATION error to Claude; self-corrects.
- `ga4_upgrade_views` hard-codes `pagePath == "/upgrade"` filter.

### System prompt (sketch)

```
You are an analytics assistant for PitchRank, a youth soccer ranking platform.

Data sources:
- GA4 (property 514724174) — traffic, pageviews, events, conversions
- Google Search Console (sc-domain:pitchrank.io) — search queries, clicks, impressions, CTR, position

Common mappings (prefer these):
- "traffic", "users", "visitors", "sessions" → ga4_traffic_overview
- "top pages", "most viewed", "popular pages" → ga4_top_pages
- "conversions", "upgrade", "upgrade page", "pricing views" → ga4_upgrade_views
- "search performance", "SEO", "search traffic", "Google" → gsc_performance
- "queries", "keywords", "search terms", "ranking for" → gsc_top_queries
- "landing pages from search", "which pages get clicks" → gsc_landing_pages

Only use query_ga4 / query_gsc if you are certain no named report can answer the question.

Default limits when unspecified:
- Top/ranked lists → 10
- Broader exploration → 30

No-data handling:
If a tool returns no rows, say so clearly and suggest either (a) a broader date range, or (b) a different dimension.

GSC freshness:
GSC has a 2-3 day reporting lag. If the user asks about "today" or "yesterday", mention the lag and show the most recent complete data. Tool results include a data_freshness field — honor it.

Error handling:
On retryable: false, report the error to the user. On retryable: true, retry once with backoff. Never retry VALIDATION errors — fix the args.

The user's current dashboard date range is: {INHERITED_DATE_RANGE}. Use this unless the user specifies otherwise.

Numbers are pre-rounded by the tool. Do not reformat them. Show deltas when available.
Be concise. Answer the question, then offer one follow-up suggestion.
```

### Streaming + UX

- Vercel AI SDK `useChat` + `streamText`.
- Tool calls render inline as collapsible cards ("🔍 Running report: ga4_top_pages — last 7 days"). User can expand for args + row count.
- Final answer streams token-by-token.
- Chat history is in-memory (not persisted). Refresh clears conversation.

### Logging

Every tool call writes a row to `analytics_chat_logs`:

```
id, created_at, turn_id (uuid), user_email, model_name,
user_question, inherited_date_range, overridden_date_range,
tool_name, tool_args (jsonb), tool_result_summary (jsonb),
tool_call_hash (sha256 of tool_name + normalized args),
force_fresh (bool), cost_units (int),
execution_ms, success, error_type, error_message,
final_answer (nullable; set on the last tool call of a turn)
```

`tool_call_hash` enables future deduplication without schema change.

## Dashboard UX

### Date range picker

Presets: **Today**, **Last 7 days** (default), **Last 28 days**, **Month-to-date**. URL-synced via `?range=7d` so refresh preserves selection. Shared across all tiles and inherited by chat.

### Tiles

Six tiles in a responsive grid:

1. **Traffic Overview** — sessions, active users, pageviews over time. Sparkline + totals + trend badge.
2. **Top Pages** — table of top 10 pages by pageviews, with engagement rate.
3. **Upgrade Views** — big number of /upgrade pageviews + conversion rate (views / sessions) + trend vs previous period.
4. **Search Performance** — GSC clicks/impressions/CTR/position over time with period-over-period deltas.
5. **Top Queries** — table of top 10 queries by clicks with CTR and avg position.
6. **Landing Pages / Index Coverage** — top landing pages from search (may be labeled "Index Coverage" pending feasibility; see Open Questions).

### Tile states

Every tile supports: `loading` (skeleton), `error` (with retry), `empty` (with suggestion), `success`. Failure of one tile does not cascade.

### Chat sidebar

- Always visible on desktop (right panel).
- `DateContextChip` shows inherited range ("Using: Last 7 days — change"). Clickable to override per-question; natural-language override ("over the last 90 days") works too via the tool `date_range` param.
- Streaming answers with inline tool-call cards.

### Meta endpoint

`/api/internal/analytics/meta` returns: available presets, default preset, GA4 property label, GSC site label, admin identity, per-source `last_refreshed_at` timestamps. Used by the shell header.

## Data model

**New Supabase table `analytics_chat_logs`** — one migration. Not exposed via RLS to the frontend; written server-side only.

Columns as listed in Chat Logging section above. Indexes on `created_at DESC` and `user_email`.

## Testing strategy

### Unit tests (Vitest, no network)

- `dates.ts` — every preset across DST, `previousPeriod()`, `detectFreshness()` boundaries.
- `transforms/` — raw → normalized fixtures, `computeGscDeltas`, `computeTrend`.
- `queries/*` normalizers — with raw fixtures captured from real API, kept in `__fixtures__/`.
- Report registry — schema rejects bad params, accepts good ones.
- `_error.ts` — every Google error code maps correctly.
- `_coalesce.ts` — concurrent same-key returns same promise; different keys don't share.

### Integration tests (opt-in, hits live APIs)

Gated behind `ANALYTICS_INTEGRATION_TESTS=1`. Run manually before releases.

- `getGa4Overview({ dateRange: "last_7_days" })` returns non-empty rows with expected shape.
- Same for each `getXxx()`.

### E2E smoke (Playwright, local dev)

- Non-admin email → 404.
- Admin email → dashboard renders, all 6 tiles reach success within 15s.
- Date range change → tiles refetch, URL updates.
- Chat: "what's my top page this week?" → tool call renders, answer streams, log appears in Supabase.

### Manual verification checklist (v1 acceptance)

- [ ] Dashboard loads for admin, 404s for non-admin
- [ ] All 6 tiles render real data
- [ ] All date range presets work (Today, 7d, 28d, MTD)
- [ ] Manual refresh button clears cache and refetches
- [ ] Chat answers 5 baseline questions correctly
- [ ] Tool call logs appear in Supabase
- [ ] Deployed to Vercel with env var credentials

### Baseline chat questions (v1 acceptance)

1. "What was my traffic last week?"
2. "What are my top 5 pages this month?"
3. "How did search performance change vs the previous period?"
4. "What keywords drove the most clicks in the last 28 days?"
5. "How many people viewed the /upgrade page today?"

Each must produce a correct, cited answer using the expected named report.

## Rollout plan

Phases are each independently deployable and reviewable.

### Phase 1 — Scaffolding
- `types.ts`, `constants.ts`, `dates.ts`, `admin.ts`, `google-clients.ts`, `logging.ts`
- Middleware extension for `(internal)/*`
- Empty dashboard page behind admin gate
- `analytics_chat_logs` Supabase migration
- Verify: admin sees empty page, non-admin sees 404

### Phase 2 — Data layer
- Report registry + shared transforms
- All 6 `getXxx()` query functions with unit tests
- `/api/internal/analytics/meta` + `/refresh` routes

### Phase 3 — Tiles
- `DashboardGrid` + `DateRangePicker` with URL-synced state
- Six tile components + their API routes
- Manual verification against known analytics numbers

### Phase 4 — Chat
- Chat tools module + system prompt
- `/api/internal/analytics/chat` streaming route
- `ChatSidebar` + `DateContextChip`
- Verify 5 baseline questions

### Phase 5 — Polish & ship
- Loading / empty / error states for every tile
- Manual verification checklist
- Deploy to Vercel with env vars set
- Shadow-use for 1 week before v2 planning

## Open questions (resolve during implementation)

1. **`gsc_landing_pages` feasibility** — confirm whether to ship true index coverage (URL Inspection API: rate-limited at 2000 URLs/day, 600/min) or the documented fallback (Search Analytics API with `page` dimension). Decision gated at ~30 min of investigation. Registry key already renamed to `gsc_landing_pages` to avoid churn.
2. **React Query already installed?** — check `frontend/package.json`; add if missing.
3. **Existing admin-gating utility?** — quick scan for any existing `ADMIN_EMAILS` or role-check; reuse if found.
4. **GA4 service account property access** — verify during first test call; expected per memory.
5. **Chat history persistence** — in-memory only for v1; revisit after shadow-use.
6. **Cost observability** — log `cost_units` but no alerting in v1.

## Future enhancements

- Hot-report precompute cron (10-min cadence, zero architectural change)
- Precomputed daily aggregates in Supabase for > 90-day comparisons
- `explain_data` tool (inspects last tool result, generates reasoning)
- Chat history persistence via `chat_sessions` table
- Additional tiles: country / device breakdown, conversions beyond `/upgrade`
- CSV / PDF export
- Anomaly detection / alerts
- A/B model swapping via Vercel AI Gateway
- Per-density TTL tuning using the `density` cache tag
- Dedup chat tool calls using `tool_call_hash`

## References

- GA4 property: `514724174`
- GSC site: `sc-domain:pitchrank.io`
- Service account credentials: `~/.config/google-analytics/` (local); `GOOGLE_SERVICE_ACCOUNT_JSON` env var (deployed)
- Memory: `google_api_credentials.md`, `gotcha_ga4_metric_names.md`, `gotcha_supabase_ssr_shared_modules.md`
