---
name: stripe-billing-data
description: Reading Stripe subscription and invoice data correctly in PitchRank - where fields actually live in the pinned API version, and the measurement traps that silently produce wrong conversion, churn and MRR numbers. Use for any work touching Stripe here - the admin subscriptions dashboard, checkout, webhook, portal, sync, or reconcile_stripe_subscriptions.py. Also use when asked why a conversion, churn, MRR or subscriber figure looks wrong, or about past-due and failed payments, coupons, discounted or sale checkouts, promotion codes, expiring open checkout sessions, or trials. Also use when checking a sale checkout on a Vercel preview or making a live Stripe change such as a coupon or webhook events.
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

`allow_promotion_codes: true` is set on every checkout session that sets no `discounts`, so this
path goes live the moment anyone creates a coupon, with no deploy.

**`amount_remaining`, not `amount_due`**, is what is still owed. `amount_due` is fixed at
finalization and does not move when a partial payment lands.

## Cancellation timestamps

`canceled_at` is the **request** time for a scheduled cancellation; `ended_at` is when
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

**A cancellation can be scheduled through `cancel_at` alone**, leaving `cancel_at_period_end`
`false`. The Customer Portal does exactly that on flexible billing mode, the default for
subscriptions created on API version `2025-09-30.clover` or later (the client pins a later one).
Treat a subscription that still grants premium (`active`, `trialing`, `past_due`) as canceling
when either is set, through `isCancellationScheduled` (`frontend/lib/stripe/server.ts`) rather than
reading either field yourself. The stored `user_profiles.cancel_at_period_end` column holds that
helper's result, so it will not match Stripe's raw `cancel_at_period_end`. Write it only from the
webhook handlers that also route the Beehiiv lifecycle (subscription updated and deleted, checkout
fulfillment). They detect a canceling or reactivation transition by comparing against the stored
flag, so a write from anywhere else, such as the sync route, `invoice.paid` or the reconcile job,
swallows that email.

**Who cancelled** a scheduled cancellation is readable off `cancellation_details`. A `feedback`
reason (sometimes with a `comment`) comes from the Customer Portal's cancellation survey, so the
customer cancelled themselves. A null `feedback` points to the Stripe Dashboard, which is how the
owner cancels for customers who email in. Treat it as a strong signal rather than proof, since the
survey is a portal setting. It does not apply to an immediate cancel: a `reason` of
`payment_failed` or `payment_disputed` is not a person, and the webhook cancels duplicate anonymous
trials through the API with no feedback.

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

The dashboard's Last Month and 2 Months Ago cards (Trial → Paid, Retention) count trials by the
month they *started*, and print a percent whenever the denominator is non-zero ("—" at zero), even
below `MIN_COHORT_SAMPLE`; the 180-day conversion and lead cards keep their "not enough data yet"
rule. The owner chose this on 2026-10-07 so a quiet month still shows a figure beside its "X of Y"
counts. Leave the rules different. The 180-day Retention card counts by trial *end*, like the
conversion card above it, and is hidden whenever that card shows "not enough data yet".

All-time churn and monthly growth read the unbounded status lists, never the 187-day cohort, and
both count only subscriptions with a paid invoice from their own unbounded paid-invoice fetch; a
window-bounded one would drop long-standing subscribers and overstate churn. Churn is per person
(by email), so a subscriber who cancels and resubscribes is not churned. `unpaid` subscribers are
in its base but count as not churned, because they paid and never cancelled. Growth rebuilds MRR
at the start of last month and of this one from `trial_end`/`start_date` and the cancellation
request time (`canceled_at`), priced at today's plans, so a past price change skews the earlier
figure. It leaves `unpaid` out, as `mrr` does, because Stripe records no time at which an unpaid
subscription stopped paying. Stripe does not document `canceled_at` for a cancellation set through
`cancel_at` alone, but measured on 2026-11-24, every such cancellation in live Stripe data (flexible
billing, from the Customer Portal) carried the request time, at or before `ended_at`, so Growth drops
it when it was requested.

Trials by Month also reads the unbounded status lists (active, trialing, past_due, canceled and
unpaid), never the 187-day cohort: its first bar is fixed at June 2026 while the cohort window
slides forward with today, so a bounded fetch would empty the oldest bars one by one. It keys the
union by id, because a subscription that changes status while the lists are fetched in parallel
comes back in two of them. It counts by `trial_start` with the same month bounds and
internal-email exclusion as the Last Month cards. A trial in a status outside those five (`paused`,
from a no-card trial created in the Stripe Dashboard) is not counted; checkout cannot create one.

The Forecast section (`buildCashForecast`) estimates the cash Stripe collects over the next 7 days,
the next 14 days and the rest of the month, after Stripe's fee (`netOfStripeFee`). Like Trials by
Month it reads the unbounded status lists keyed by id, plus the lifetime paid invoices, and is
unavailable when any of them failed; the 187-day cohort and paid invoices play no part. Renewals are
dated at each item's `current_period_end`, skip scheduled cancellations, and count only for
subscribers who have paid before, the population `computeRenewalCollectionRate` measures (its doc
comment has the scoring rules), so a past-due subscription whose first charge was declined books no
renewal. That rate sees only paid invoices, so a miss means no paid renewal invoice near the rebuilt
date, not a failed attempt. Current trials are dated at `trial_end` at their plan's lifetime trial →
paid rate (`computeLifetimeConversionByPlan`), and trials already set to cancel count at that rate
too, because it was measured over every trial, including those that cancelled midway. Month
Projection's New Subs counts them as lost instead, so the two sections differ there on purpose.
Trials yet to start come from the trailing 14 days' pace. Each rate falls back below
`MIN_COHORT_SAMPLE`: conversion to `FALLBACK_CONVERSION_RATE`, renewal collection to
`FALLBACK_RENEWAL_RATE` (one minus the churn fallback).

`.turbo/reports/2026-09-04-stripe-month-projection-baseline.md` carries Month Projection's dated
figures and the derivation of the fallback rates. Read numbers from there rather than from this file, and re-measure before quoting them.

## Measuring a shift in the plan mix

Count trials (subscriptions with a `trial_start`) by the item price's `recurring.interval`, in 7-day
windows rather than one before-and-after average, and lead with the latest window. An average over
the whole period understates a mix that is still moving. List with `status: 'all'`: the default list
omits canceled subscriptions, so older windows lose trials the latest window still holds.

Stripe records no device, so attribute a shift with GA: `plan_selected` events split by
`customEvent:plan` and `deviceCategory`, reading a device whose layout did not change as the control.
Clicks show the shape of the shift; take trial counts from Stripe.

## Subscription counts in Google Analytics

`subscription_completed` comes from the Stripe webhook through the Measurement Protocol
(`frontend/lib/analyticsServer.ts`), because the tag never loads on `/upgrade/success`. Without
`GA_API_SECRET` it is skipped with only a log warning, so a sudden zero can be configuration. It is
counted for any checkout ending in a premium status, trials included, and a Stripe duplicate or a
manual resend counts twice. It carries no `source` parameter, so the upgrade-sources report files
every subscription under `(not set)` and shows 0% for each real source.

Keep the premium-status check (`plan === 'premium'`) rather than comparing against the stored
`user_profiles.subscription_status`. `invoice.paid` and `checkout.session.completed` arrive in either
order and both write that column, so when `invoice.paid` lands first, a signed-in buyer's checkout
reads its own new status and a real subscription goes uncounted. A checkout whose subscription has
already ended can pass the comparison too, and the premium check refuses it.

A buyer with no readable `_ga` cookie goes out under a throwaway id, and Google's docs call an event
valid only under a client id gtag.js has already used, so GA may drop those. Where it keeps them,
cart abandonment, which divides by the browser-fired `checkout_initiated`, can go negative over a
short window.

Counts from 2026-08-19, when the tag came off this page, until the webhook began sending the event
undercount heavily: read that span with Stripe.

A sale checkout also sends `<prefix>_purchase_completed`, named by `promotionEventName`
(`frontend/lib/promotions.ts`) from the sale's own prefix. It goes out for sale sessions only, as the
webhook's last action after every write. It has no dedupe gate either, but every event carries
`transaction_id` (the subscription id), so a count can be made distinct. `<prefix>_checkout_expired`
arrives only if `checkout.session.expired` is on the Stripe webhook endpoint's event list. It counts
sale checkouts that closed unpaid, whether at their own close time or expired by the checkout route
around a sale; an expired standard checkout sends nothing.

## MRR

Stripe's Billing MRR is the monthly-normalized value of `active` and `past_due` subscriptions,
**less any subscription with a scheduled cancellation** — Stripe drops it when the cancellation is
requested, not when service ends. Trials, taxes and metered prices are excluded, and forever
discounts are always subtracted. `getSubscriptionMetrics` applies the status and
scheduled-cancellation rules; `computeMrr` reads list prices and subtracts no discount, so a coupon
or a metered price makes the dashboard read higher than Stripe.

The scheduled-cancellation rule appears only in Stripe's support article *Understanding MRR*
(`support.stripe.com/questions/understanding-monthly-recurring-revenue-(mrr)`); the analytics docs
page omits it. Two inputs are account settings no session can read: whether repeating and one-time
discounts are subtracted, and whether a subscriber counts from the start of the subscription or
from the first payment. When a figure still differs from Stripe's after the rules above, ask the
user how those two are configured.

## A Checkout Session id does not prove who holds it

The Stripe-hosted checkout URL carries the session id (`checkout.stripe.com/c/pay/cs_...`, as in
Stripe's API reference example), so whoever started the checkout, anyone sent its link, and the
browser's history all hold it. The id alone may read a session's state and sync what Stripe already
says about it; it must never grant a sign-in. It is still the bearer credential for the sync route,
so keep it out of logs and URLs. `/api/stripe/checkout-login` adds, among other gates listed in
`frontend/CLAUDE.md` pitfall 20, the HttpOnly `checkout_browser` cookie, whose SHA-256 the
checkout route stores on the session as `browser_key_hash`.

That route rests on two Supabase behaviours:

- **Minting a one-time link replaces the user's earlier one.** A magic link and a recovery link
  share one stored token, so a set-password link emailed earlier stops working once a sign-in link
  is minted. A live run on 2026-11-09 saw the emailed link rejected after a sign-in.
- **Admin `updateUserById` merges `app_metadata` keys** rather than replacing the object (verified
  on the same run), and only admin calls can write `app_metadata` at all.

## Discounted checkouts and sale sessions

`.turbo/plans/black-friday-2026-sale.md` has the sale's design; these are the Stripe behaviours it
rests on.

- **One discount per session, and no promotion codes beside it.**
  - `discounts` takes at most one coupon or promotion code.
  - `baseSessionParams` (`frontend/app/api/stripe/checkout/route.ts`) sets `discounts` or
    `allow_promotion_codes`, never both: Stripe refuses the pair. The typings don't say so, so a test
    double must refuse it too.
- **`expires_at` is 30 minutes to 24 hours after creation, on Stripe's clock.** Clamp with a margin
  on both ends (for example `now + 31 min` to `now + 23 h`), never exactly 24 hours.
- **A coupon's `redeem_by` cannot be changed after the coupon exists.**
  - Set it with any grace period already included.
  - Deleting a coupon stops new applications and leaves applied discounts in place.
  - `duration: 'once'` discounts the first invoice only.
- **Expiring a customer's open sessions:**
  - `checkout.sessions.list` defaults to 10 per page (`limit` up to 100).
  - Collect every id with a `starting_after` loop until `has_more` is false, then expire each.
    Expiring during the walk changes the filtered set under the cursor. A stateful test double
    skipped rows that way; real Stripe's behaviour here is unverified, so collect first regardless.
  - Always pass `customer`. The parameter is optional, and omitting it lists other buyers'
    sessions.
  - `checkout.sessions.expire` works only on an `open` session. On an expire error, retrieve the
    session: if its status is no longer `open`, carry on and re-check the buyer's subscriptions
    before creating a new session (every live status for a sale, `active` and `trialing` for a
    standard checkout); otherwise rethrow.
- **Settlement:** before assuming every Checkout payment settles at once, read the account's payment
  method configuration with `stripe_api_read` `GetPaymentMethodConfigurations`. The default
  configuration had no delayed-settlement method enabled when read on 2026-11-24.

## Where the code is

| Concern | Location |
|---|---|
| Client, price IDs, webhook event names, field helpers | `frontend/lib/stripe/server.ts` |
| Shared constants and `getCustomerEmail` | `frontend/lib/admin/constants.ts` |
| Rates, projection, month cohorts, retention, lifetime churn, cash forecast (pure functions) | `frontend/lib/admin/month-projection.ts` |
| Stripe fetching and assembly | `frontend/lib/admin/subscription-metrics.ts` |
| Admin dashboard page | `frontend/app/mission-control/subscriptions/` |
| Checkout, checkout-login, webhook, portal, sync routes | `frontend/app/api/stripe/` |
| Sale settings and event names (client-safe); live check, kill switch, preview window, coupon env | `frontend/lib/promotions.ts`; `frontend/lib/promotions.server.ts` |
| Statuses that keep premium, plan checks (directive-free, so route handlers can import them) | `frontend/lib/plan.ts` |
| Browser tie for the return sign-in | `frontend/lib/stripe/checkoutBrowser.ts` |
| Reconciliation (every 6 hours) | `scripts/reconcile_stripe_subscriptions.py` |
| Shared test doubles | `frontend/test/fixtures.ts` (`makeStripeSubscription`, `makeStripeInvoice`, `makeCheckoutSession`) |

Every list Stripe returns has a valid empty state, so a failed fetch is indistinguishable from a
genuine zero once the array is passed on alone. `subscription-metrics.ts` carries an `ok` flag
beside the items for this reason; keep it when adding a fetch, and have consumers fall back or
render unavailable rather than report a confident zero.

## Reading live Stripe from a session

There is no `STRIPE_SECRET_KEY` in the local environment — the key lives in Vercel. Use the
claude.ai Stripe MCP connector. When it lists only `authenticate` and `complete_authentication`, the
connector is logged out: ask the user to run `/mcp` before anything else, and read account data
yourself once it reconnects.

The connector reaches the live account only (`list_available_accounts_or_orgs` returned one live
context on 2026-11-24), and it reads only: every `stripe_api_write` call fails with
`Insufficient scope: required "mcp"`, and a `/mcp` reconnect did not change that (2026-11-25).
Until a `stripe_api_write` succeeds, treat any live change (a coupon, a webhook endpoint's events, a
refund) as a Dashboard step for the user: say so before starting, give the fields one by one, then
read the object back to verify it. A test-mode checkout needs test keys and test-mode objects
(prices, coupon, webhook endpoint) on a Vercel preview, also set up by the user, so offer the unpaid
live check below first.

`stripe_analytics` query runs and metric templates fail with "requires a Sigma subscription or
trial". Claude in Chrome on `dashboard.stripe.com` returns "Permission denied for this action on
this domain". So Stripe's own MRR, churn and subscriber figures are the user's to read off the
Dashboard; compute yours from `stripe_api_read` REST lists and ask for theirs only to compare.

`GetSubscriptions` and `GetInvoices` responses run to hundreds of KB and will overflow a tool
result; they are written to a file instead. Analyse that file with `jq` or a Python script rather
than reading it, and page with `starting_after` from the last id.

The fee Stripe took on a charge is on its balance transaction (`fee`, `net`). Read it with
`GetBalanceTransactions` and `type: 'charge'`. Charges checked on 2026-11-24 matched standard US card pricing
(2.9% + 30¢), which is what `netOfStripeFee` assumes; check there first if the Forecast's fee ever
looks off.

## Checking a sale checkout against live Stripe without paying

To prove live Stripe accepts a sale checkout (price, coupon, no trial) before it ships, open one on
the PR's preview and stop before paying. Prefer this to a test-mode practice purchase (owner,
2026-11-25). Previews shared production's live Stripe keys as of 2026-11-25, so this is a real live
session that expires unpaid; its expiry reaches production's webhook and can add one
`<prefix>_checkout_expired` to the sale's funnel.

1. With the Vercel MCP `create_project_env`, add two preview variables scoped to the PR branch
   (`target: ["preview"]`, `gitBranch`): `STRIPE_COUPON_<ID>` set to the live coupon id, and
   `PROMOTION_WINDOW_OVERRIDE` set to `<startISO>/<endISO>` a few hours around now, so it closes on
   its own. A malformed override is ignored with only a log warning.
2. Rebuild the preview with `create_deployment` (a GitHub `gitSource` with ref and sha), and wait
   with `vercel inspect <deployment url> --wait`.
3. Get a share link with `get_access_to_vercel_url`. Drive it with a Node Playwright script that
   requires playwright from the main checkout's frontend node_modules and launches its own Chromium,
   since another session may hold the Playwright MCP browser.
4. Open `/upgrade` signed out, tap the sale card's button, wait for `checkout.stripe.com`, and read
   the page text: the amount due today, the renewal line, the discount line, and the absence of a
   code box. Enter nothing.
5. The window from step 1 closes on its own. To close it sooner, edit `PROMOTION_WINDOW_OVERRIDE` to
   a past window with `edit_project_env` and rebuild as in step 2, since Vercel applies an env edit
   only to new deployments. The MCP has no tool for deleting an env var, so tell the user both
   leftover branch variables are safe to delete.

## Exercising Stripe routes on a local production build

No Stripe key exists locally, so set a placeholder `STRIPE_SECRET_KEY` (the client throws without
one) and point the SDK at a fake. Preload a script with
`NODE_OPTIONS=--require` that wraps `https.request` and sends `api.stripe.com` to a local HTTPS
server. It must be HTTPS: the Node SDK waits for `secureConnect` before writing the request, so a
plain-HTTP fake hangs, and the wrapper must trust the fake's self-signed certificate (an agent with
`rejectUnauthorized: false` on the redirected request). Make that certificate with Python
`cryptography`; Git Bash's `openssl req` fails for want of its config file. Chromium keeps `Secure` cookies on
`http://localhost`, so cookie flags behave as in production.

The local `.env.local` holds no Stripe price ids, so a checkout click stops in the browser with
"Pricing is not configured" before any request. Set placeholder `NEXT_PUBLIC_STRIPE_PRICE_YEARLY`
and `NEXT_PUBLIC_STRIPE_PRICE_MONTHLY` before `next build` or `next dev` starts, since Next inlines
`NEXT_PUBLIC_` values into the bundle. The site's CSP (`connect-src 'self' https:`)
blocks a plain-HTTP local Supabase proxy for browser-side calls, so only server-side reads pass
through one.

Any run that creates an account on live Supabase auth needs the owner's OK first and deletes the
account in a `finally`.
