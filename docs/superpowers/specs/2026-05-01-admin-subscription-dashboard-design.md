# Admin Subscription Dashboard

**Date:** 2026-05-01
**Author:** Dallas Heidt
**Status:** Approved — ready for implementation

## Goal

A clean internal dashboard at `/mission-control` that gives the admin a real-time view of the subscription business. Optimized for daily decision-making, not user display.

## Daily questions the dashboard must answer

1. How many paying customers do I have?
2. How much MRR do I have?
3. How many people are on trial?
4. Who is about to convert (trials ending soon)?
5. Are trials converting into paid?
6. Which paying customers need attention (past_due)?

## Scope

### In scope (v1)

- KPI cards: MRR, Active Paid Subs (with monthly/annual split), Active Trials, Trials Ending ≤7d
- Attention-needed section: count + table of `past_due` subscriptions
- Trial pipeline table: customer email, trial end date, days remaining, plan interval, sorted by soonest end
- Conversion: 30-day rolling cohort percentage (with Y of Z denominator visible)
- Auto-refresh on page load; manual refresh via plain link/reload

### Out of scope (v1)

- Trend chart (subscriptions over time)
- CSV export
- Date-range picker
- Reading from Supabase (`user_profiles`) — Stripe is single source of truth for this page
- Schema migrations

## Architecture

### Route

`frontend/app/mission-control/page.tsx` — React Server Component, `export const dynamic = 'force-dynamic'`. Auth is already enforced by `frontend/middleware.ts` which gates `/mission-control` to `plan = 'admin'`.

### Data layer

`frontend/lib/admin/subscription-metrics.ts` exports a single function:

```ts
export async function getSubscriptionMetrics(): Promise<SubscriptionMetrics>
```

Pulls from Stripe API only. No Supabase reads. Makes three list calls (auto-paginated):

1. `stripe.subscriptions.list({ status: 'active' })` — for MRR + active paid count + interval split.
2. `stripe.subscriptions.list({ status: 'trialing' })` — for trial count + pipeline table.
3. `stripe.subscriptions.list({ status: 'past_due' })` — for attention-needed section. Excluded from MRR.
4. `stripe.subscriptions.list({ created: { gte: now − 60d } })` (all statuses) — for conversion cohort.

Customer emails are resolved by `expand: ['data.customer']` on each list call so we don't make per-customer fetches.

### Output shape

```ts
type SubscriptionMetrics = {
  mrr: number; // USD dollars, computed from active subs only
  activePaid: {
    total: number;
    monthly: number;
    annual: number;
  };
  trials: {
    total: number;
    endingIn3Days: number;
    endingIn7Days: number;
    list: Array<{
      id: string;
      email: string;
      trialEnd: string; // ISO
      daysRemaining: number;
      interval: 'month' | 'year';
    }>;
  };
  pastDue: {
    total: number;
    list: Array<{
      id: string;
      email: string;
      interval: 'month' | 'year';
    }>;
  };
  conversion: {
    window: '30d';
    sample: number; // Z — trials started 31–60 days ago that have completed
    converted: number; // Y — of those, currently active
    percent: number | null; // null if sample < 5
  };
  generatedAt: string; // ISO
  errors: string[]; // section-level errors, empty if everything succeeded
};
```

### MRR formula

For each subscription where `status === 'active'`:

- For each line item, monthly equivalent = `unit_amount × quantity / (interval === 'year' ? 12 : 1)`.
- Sum across items, then across subscriptions.
- Divide by 100 to convert cents to dollars.

`past_due` and `trialing` are explicitly excluded from MRR.

### Active paid breakdown

For each `status === 'active'` subscription, classify by the recurring `interval` of its primary line item (`items.data[0].price.recurring.interval`). `month` → monthly; `year` → annual.

### Trials ending bucketing

`trial_end` is a Unix timestamp on the subscription. For each `trialing` subscription:

- `daysRemaining = ceil((trial_end - now) / 86400)`
- `endingIn3Days`: `daysRemaining <= 3`
- `endingIn7Days`: `daysRemaining <= 7` (superset of 3)

### Conversion math (30-day rolling)

- Denominator (`sample`): subscriptions where the original `trial_start` falls in `[now − 60d, now − 30d]` AND `trial_end < now` (trial completed). Statuses can be any.
- Numerator (`converted`): of those, `status === 'active'`.
- If `sample < 5`, return `percent: null` and the UI shows "Not enough data yet".

### Caching / freshness

None for v1. Page is admin-only and infrequent. Each load hits Stripe directly. Manual refresh is a hard reload.

### Error handling

`getSubscriptionMetrics()` wraps each Stripe list call in try/catch. On failure, the relevant section returns zero/empty values and an error message is appended to `errors[]`. The page renders an inline banner per error rather than crashing.

## UI

Server component renders into existing `Card` components from `@/components/ui/card`. Layout:

```
Header: "Mission Control · Subscriptions"  · "As of {generatedAt}"  · [Refresh link]

[ MRR card ]  [ Active Paid card ]  [ Active Trials card ]  [ Ending ≤7d card ]
                ↳ "M monthly · A annual"                       ↳ "K in 3d"

[ Attention Needed ]
  N past_due subscriptions
  table: email | interval

[ Trial Pipeline ]
  table: email | trial ends | days | interval
  sorted by trial end ascending

[ Conversion ]
  XX%  ·  Y of Z trials started 31–60 days ago are now active
  (or "Not enough data yet" when sample < 5)
```

Tailwind v4 classes mirroring existing app patterns (`bg-muted/30`, `text-muted-foreground`, `font-display`, `Card`, `Badge`).

## Files

**New:**

1. `frontend/lib/admin/subscription-metrics.ts` — data fetcher and math.
2. `frontend/app/mission-control/page.tsx` — Server Component renderer.
3. `frontend/lib/admin/__tests__/subscription-metrics.test.ts` — unit tests.

**Modified:** none. Middleware already gates the route.

## Testing

Unit tests in `frontend/lib/admin/__tests__/subscription-metrics.test.ts` with mocked Stripe responses:

- MRR sums monthly + (annual ÷ 12) correctly.
- MRR excludes `past_due` and `trialing`.
- Active paid split classifies monthly vs annual by `interval`.
- Trial bucketing: `endingIn3Days` ⊆ `endingIn7Days`.
- Trial list sorted ascending by `trial_end`.
- Conversion: `percent === null` when `sample < 5`.
- Conversion: Y/Z math on a fixed cohort.
- Section error fallback returns zero values + error string.

Manual verification: load `/mission-control` as the admin account, eyeball numbers against Stripe dashboard.

## Risks

- **Stripe rate limits:** Each load makes ~4 list calls with auto-pagination. Acceptable for admin-only page; not user-facing.
- **`trial_start` field availability:** Stripe puts `trial_start` on the subscription object only when there was a trial. For non-trial subs in the 60-day window, we filter them out (no trial → not part of cohort denominator).
- **Currency assumption:** v1 assumes USD. If multi-currency is added later, MRR math must convert.
