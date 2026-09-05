---
name: stripe-billing-data
description: Reading Stripe subscription and invoice data correctly in PitchRank - where fields actually live in the pinned API version, and the measurement traps that silently produce wrong conversion, churn and MRR numbers. Use for any work touching Stripe here - the admin subscriptions dashboard, checkout, webhook, portal, sync, or reconcile_stripe_subscriptions.py. Also use when asked why a conversion, churn, MRR or subscriber figure looks wrong, or about past-due and failed payments, coupons, or trials.
---

# Stripe Billing Data in PitchRank

The client pins an explicit `apiVersion` in `frontend/lib/stripe/server.ts`. Several fields moved
in versions before it, and TypeScript will not catch a read of a removed field once the value is
cast. Read the pin there, and verify any field you are unsure of against the installed typings
under `frontend/` — `node_modules/stripe/types/` — rather than from memory. That directory is the
pinned version's own truth.

## Where fields actually live

**The subscription behind an invoice is not `invoice.subscription`.** That field was removed in
`2025-03-31.basil` and is absent from the pinned version. Read:

```ts
invoice.parent?.subscription_details?.subscription   // string | Stripe.Subscription
```

The line-item fallback is `line.parent?.subscription_item_details?.subscription`, a plain
`string | null`. Use it only as a fallback: `invoice.lines` is a paginated sublist, so on an
invoice carrying enough line items the subscription row is not in the first page at all.

**Billing periods are on the subscription item, not the subscription.**
`current_period_start` / `current_period_end` live on `SubscriptionItem`. Read a period through
`extractPeriodEnd` (`frontend/lib/stripe/server.ts`), which handles both locations, rather than
reaching for the field yourself. When summing or scanning across items, iterate `sub.items.data`
in full as `computeMrr` (`frontend/lib/admin/subscription-metrics.ts`) does: Stripe designates no
canonical item, and periods can differ per item.

## The $0 invoice trap

A trial opens with a **$0 invoice that Stripe marks `status: 'paid'`**, so `status: 'paid'` proves
nothing on its own:

```ts
const paidCash = invoice.amount_paid > 0;
```

**A discount is copied onto that trial-opening invoice too.** A subscription-level coupon appears
on every invoice the subscription generates, so `total === 0 && discounts.length > 0` identifies
"this subscription has a coupon", not "this subscription activated". Gate the discounted-activation
case on the billing reason:

```ts
const discountedActivation =
  invoice.total === 0 && invoice.discounts.length > 0 && invoice.billing_reason !== 'subscription_create';
```

`billing_reason` is typed nullable, so a `null` satisfies the `!==` and passes the gate. That is
tolerable only while every invoice reaching this code is a subscription invoice; check it if a
non-subscription source is ever added. The cash arm must still accept `subscription_create` — that
is the activation invoice for a returning customer who gets no trial.

`allow_promotion_codes: true` is set on every checkout session, so this path goes live the moment
anyone creates a coupon, with no deploy.

**`amount_remaining`, not `amount_due`**, is what is still owed. `amount_due` is fixed at
finalization and does not move when a partial payment lands.

## Cancellation timestamps

`canceled_at` is the **request** time for a `cancel_at_period_end` cancellation; `ended_at` is when
service actually stopped. They can be a year apart on an annual plan. Prefer `ended_at`, falling
back to `canceled_at` only when no end was recorded.

Falling back is not enough on its own. A subscription with a pending cancellation is **still
`active`** and already carries `canceled_at`, so any loop that resolves an end timestamp must also
require the subscription to have actually stopped:

```ts
if (sub.status !== 'canceled') continue;
```

Without that guard a cancellation requested this month for service ending next year is booked as
this month's churn.

## Retries are scheduled, not promised

`next_payment_attempt !== null` means Stripe has another attempt **on the calendar**. It does not
mean the attempt will succeed or even run: after a non-retryable decline (lost or stolen card)
Stripe keeps scheduling retries that execute only once a new payment method arrives. The
`attempt_count` docstring in the pinned typings says so directly.

There is no fixed retry ceiling to compare against: the count is an account-level Smart Retries
setting. Read the scheduled/not-scheduled state off the invoice, and treat a count of unscheduled
invoices as a floor on the work outstanding rather than the whole of it.

## Measuring trial conversion

Three definitions are all reachable from the same data and only one is right:

| Method | What it actually measures |
|---|---|
| Current status is `active`/`past_due` | Retention, not conversion — writes off everyone who paid then cancelled |
| Billing period advanced past `trial_end` | Intent to bill — counts trials whose card was declined |
| **An invoice charged real money** | **Conversion** |

Churn has the mirror trap: restrict it to subscribers who actually paid, or a declined card at
trial end reads as a customer leaving when it is a collection failure.

`.turbo/reports/2026-09-04-stripe-month-projection-baseline.md` carries the dated figures and the
derivation. Read numbers from there rather than from this file, and re-measure before quoting them.

## Where the code is

| Concern | Location |
|---|---|
| Client, price IDs, webhook event names, field helpers | `frontend/lib/stripe/server.ts` |
| Shared constants and `getCustomerEmail` | `frontend/lib/admin/constants.ts` |
| Rates, projection, unpaid invoices (pure functions) | `frontend/lib/admin/month-projection.ts` |
| Stripe fetching and assembly | `frontend/lib/admin/subscription-metrics.ts` |
| Admin dashboard page | `frontend/app/mission-control/subscriptions/` |
| Checkout, webhook, portal, sync routes | `frontend/app/api/stripe/` |
| Nightly reconciliation | `scripts/reconcile_stripe_subscriptions.py` |
| Shared test doubles | `frontend/test/fixtures.ts` (`makeStripeSubscription`, `makeStripeInvoice`) |

Every list Stripe returns has a valid empty state, so a failed fetch is indistinguishable from a
genuine zero once the array is passed on alone. `subscription-metrics.ts` carries an `ok` flag
beside the items for this reason; keep it when adding a fetch, and have consumers fall back or
render unavailable rather than report a confident zero.

## Reading live Stripe from a session

There is no `STRIPE_SECRET_KEY` in the local environment — the key lives in Vercel. Use the
claude.ai Stripe MCP connector; the user authenticates it by running `/mcp`.

`stripe_analytics` is refused — the key lacks `reporting_write`, so Sigma queries and the
MRR/churn/subscriber metric templates all fail. Read account data with `stripe_api_read` and
compute those figures from the REST lists instead.

`GetSubscriptions` and `GetInvoices` responses run to hundreds of KB and will overflow a tool
result; they are written to a file instead. Analyse that file with `jq` or a Python script rather
than reading it, and page with `starting_after` from the last id.
