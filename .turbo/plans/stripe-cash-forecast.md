---
status: done
---

# Plan: Stripe cash forecast on the subscriptions page

## As built (2026-11-24)

Built as planned, with these differences:
- **One guard for plans.** A single null-plan `continue` in `buildCashForecast` covers both the
  trial and the new-trial paths. Mutating it fails the planless-subscription test.
- **The payment test runs while grouping.** `isActivatingPayment` and the `subscription_cycle` test
  are applied when invoices are grouped by subscription, not at each date match. This is equivalent,
  and the mutation that skips it is caught.
- **An extra test row for the notice check.** A subscription whose service ended with no
  `canceled_at` is held out of the sample, so each half of the notice check fails a test of its own.
- **The fee comment points to the balance transaction.** `netOfStripeFee`'s doc comment says where
  Stripe's actual fee can be read.
- **The `payingAt` docstring is corrected too.** The same `cancel_at`-alone claim as the skill
  sentence fixed in Step 11 was in `payingAt` (`subscription-metrics.ts`), and it is corrected the
  same way.
- **Code review fixes:**
  - Renewals are forecast only for subscribers in the ever-paid set (`buildCashForecast` takes
    `paidSubIds`). A past-due subscription whose first charge was declined has never paid, and
    the collection rate is measured on payers.
  - `computeMrr` and the forecast read item prices through one helper, `pricedItemCents`.
  - Renewal and trial charges are kept in two lists.
  - The month window ends at `monthBounds(now).monthEnd`.
  - `TrialPipelineEntry.interval` is typed `Plan`.
- **Owner calls in code review (2026-11-24):**
  - The cards read "Next 7 Days" and "Next 14 Days", matching the page's other labels.
  - The page's month name, for Month Projection and Trials by Month too, now comes from the
    forecast's month window rather than `generatedAt`. That fixes an older mislabel on loads
    spanning midnight at month end.
- **More test rows:**
  - A trialing subscription whose item period ends in the window books no renewal, and neither
    does an unpaid one.
  - A trial cancelled outright before its end books no trial charge.
  - A total whose rounding would differ if the whole were rounded.
  - All six inputs of the availability check.
  - The internal-account exclusion in the annual conversion rate.
  - A never-paid past-due subscription in the end-to-end fixture books no renewal.
  - When the forecast is unavailable, its month window still names the measured month, on the
    page and in the metrics.
- **Test-double changes beyond Step 10:**
  - `setStripe` takes `extraInvoices`, so no test copies its invoice double.
  - `makeStripeSubscription` (`frontend/test/fixtures.ts`) defaults a trialing item's period end to
    its trial end, as Stripe bills it, so a trialing fixture cannot sit outside every window.
- **Out of scope as well:** prices with `interval_count` above 1, and a `cancel_at` set beyond the
  current period. `isCancellationScheduled` treats any `cancel_at` as scheduled, so a renewal still
  due before such a date would be dropped. Neither occurs in live data.
- **Changes to the end-to-end fixture:**
  - `sub_m1` renews on Sept 20.
  - `matured`, `sub_sep_done`, `sub_established` and `sub_unpaid` carry explicit anchors.
  - `sub_established` has its eight monthly renewal invoices, three of them older than 187 days.
- **The preview was skipped by the owner:** the page needs the Vercel-only Stripe key. The owner
  checks the live page after merge.
- **Verification before code review:**
  - The four suites passed (219 tests), and the full frontend gate was green (1,822 tests, lint,
    format, typecheck, llms.txt).
  - All 23 mutations failed a named new test.
  - `test_agent_doc_references.py` passed.
- **Verification after two code-review rounds:**
  - The full frontend suite passes (1,832 tests).
  - The review fixes' 11 guard mutations each fail the new test written for them.

## Context

The owner wants an educated estimate of how much money Stripe will collect over the next 7 days,
the next 14 days, and by the end of the current month. It is shown on
`/mission-control/subscriptions` and built on each plan's lifetime trial-to-paid rate. The design was
approved on 2026-11-24 (approach A: three cards). Read it first; this plan does not restate its
reasoning. It was written outside the repo, and Step 2 copies it to
`docs/superpowers/specs/2026-11-24-stripe-cash-forecast-design.md`.

What it adds is a **Forecast** section directly below Month Projection, with three cards:

- **Next 7 days**
- **Next 14 days**
- **Rest of {Month}**, through the last day of the month in `BUSINESS_TIMEZONE`

Each card shows one dollar figure, after Stripe's fee, and a breakdown:
`renewals $a · trials $b · new trials $c`.

- A **renewal** is dated at its item's `current_period_end` and scaled by a measured renewal
  collection rate.
- A **current trial** is dated at its `trial_end` and scaled by its plan's lifetime conversion rate.
  Trials already set to cancel are included, on purpose (see the design doc).
- **New trials** (those not started yet) come from the trailing 14-day pace.

The repo is public. Keep live business figures (rates, counts, totals) out of this plan, the design
doc, tests, commit messages and the PR. Fixture values are invented.

**Out of scope because live Stripe has none of them** (checked read-only on 2026-11-24 across every
subscription):
- `paused` subscriptions;
- `pause_collection` set;
- more than one item, or `items.has_more`;
- a zero or missing `unit_amount`;
- a subscription paid at both plan prices, i.e. a plan switch.

The code reads the first item's plan, as `getInterval` does, and handles none of these specially. A
change that makes any of them possible (a second product, a coupon-free $0 price, plan switching)
should revisit this section.

## Pattern Survey

### Analogous Features
- `frontend/lib/admin/month-projection.ts:460` `countAnnualRenewals` dates renewals inside a window.
  - It walks every item in `sub.items.data` for a `current_period_end` in `[nowSec, monthEnd)`.
  - It takes `now: Date` and derives `nowSec`.
  - It counts only, with no amounts.
- `month-projection.ts:389` `computeTrialProjection` projects future trial starts as
  `dailyRate × max(0, daysInMonth − TRIAL_DAYS − daysElapsed)` (`:430`). That is the "starts early
  enough to end inside the window" idea.
  - Unlike the approved Forecast, it treats trials that are set to cancel or already cancelled as
    non-converting (`:408`).
  - So the two sections treat those trials differently on purpose. Say so in the skill paragraph
    (Step 9).
- `month-projection.ts:519` `buildMonthProjection` is a pure assembler. It is wired at
  `subscription-metrics.ts:637-649` and returned at `:705` as `{ available: measurable, ...x }`.
- `page.tsx:158-204` is Month Projection. When unavailable, the heading-row span reads
  `'could not be loaded'`, and a single `<Card variant="flat">` sentence replaces the KPI grid
  (`:167-174`). It is pinned by `page.test.tsx:308-323`.

### Reusable Utilities
- `computeTrialConversionRate` (`month-projection.ts:165`).
  - Window: `trial_end` in `[windowStart, now)`, through the private `trialsIn` (`:261`).
  - Excludes internal emails (`isExcluded`, `:150`).
  - Falls back below `MIN_COHORT_SAMPLE` (private `finalizeRate`, `:322`).
  - Called with `windowStart: 0`, `paidSubIds: everPaidIds` and subscriptions pre-filtered by
    plan, it gives the lifetime per-plan rate unchanged.
- `collectPaidSubscriptionIds` (`month-projection.ts:106`) already runs over the lifetime paid
  invoices as `everPaidIds` (`subscription-metrics.ts:665`).
- Private helpers in `month-projection.ts`, all reachable if the new code lives in the same module:
  - `isStillSubscribed` (`:257`): active or past_due, with no scheduled cancellation.
  - `getInvoiceSubscriptionId` (`:127`).
  - `finalizeRate` (`:322`).
  - `monthBounds` (`:353`).
  - `isExcluded` (`:150`).
  - `getServiceEnd` (`:146`).
- `monthsBack(now, 0).monthEnd` (`month-projection.ts:330`) is the Phoenix start of next month, in
  seconds: the end of the "Rest of {Month}" window.
- `getInterval` (`subscription-metrics.ts:250`) is private and reads `items.data[0]`. It is used at
  `:311` and `:343`.
- `computeMrr` (`subscription-metrics.ts:261-274`) reads amounts:
  - It skips an item when `!recurring || unit_amount == null`.
  - It uses `quantity ?? 1`.
  - It works in cents, then returns dollars rounded to the cent.
- No Stripe-fee helper exists anywhere.
- `isCancellationScheduled` (`frontend/lib/stripe/server.ts:106`).
- Constants (`constants.ts`): `TRIAL_DAYS` (`:17`), `MIN_COHORT_SAMPLE` (`:14`), `SECONDS_PER_DAY`
  (`:4`), `getCustomerEmail` (`:19`). `FALLBACK_CONVERSION_RATE` and `FALLBACK_CHURN_RATE` are at
  `month-projection.ts:29-30`.
- Data in `getSubscriptionMetrics` (`subscription-metrics.ts:580`):
  - The unbounded lists are `active`, `trialing`, `pastDue`, `canceled` and `unpaid` (`:586-590`),
    plus `lifetimePaidInvoices` (`:601`, `status: 'paid'`, no date floor).
  - `everySub` (`:654-659`) is their union, keyed by id.
  - `statusListsOk` (`:661`).
  - `cohort` and `paidInvoices` are bounded to 187 days. Do not use them here.
  - Only **paid** invoices are fetched, so a missed renewal shows up only as a missing paid invoice.
- Fields in the pinned typings:
  - Subscription: `billing_cycle_anchor` (`Subscriptions.d.ts:40`), `trial_start`, `trial_end`,
    `canceled_at` (when cancellation was requested), `ended_at`, and the per-item
    `current_period_end`.
  - Invoice: `created`, `billing_reason`, `amount_paid`, `total`, `discounts`, and
    `parent.subscription_details.subscription`.
- Test doubles in `frontend/test/fixtures.ts`:
  - `makeStripeSubscription` (`:195`) has no `billingCycleAnchor` option.
  - `makeStripeInvoice` (`:267`) supports `created`, `billingReason` (default
    `subscription_cycle`), `subscription`, `amountPaid`, `total` and `discounts`.

### Convention Anchors
- **Pure functions:** they live in `month-projection.ts`, take `now` and `excludedEmails` as
  parameters, and never call Stripe. Fetching and wiring live in `getSubscriptionMetrics`.
- **Section types:** each section's type joins `SubscriptionMetrics` (`subscription-metrics.ts:74-105`)
  as `{ available: boolean } & X`.
- **Unavailable data:** compose availability from `.ok` flags. Never show a confident zero
  (`stripe-billing-data` SKILL "Where the code is", last paragraph).
- **Money:** `unit_amount` is integer cents, while `SubscriptionMetrics` carries dollars.
- **Page formatting:**
  - `formatDollars` (`page.tsx:13`) shows two decimals.
  - `KpiCard` (`page.tsx:461`) takes `label`, `value`, `sub` and `emphasize`.
  - `monthName` (`page.tsx:70-73`) is the long month name in `BUSINESS_TIMEZONE`, taken from
    `generatedAt`.
- **Tests:**
  - Pure suites inject `now` directly, using a local `phoenix(y, m, d, h)` helper in each describe
    (`month-projection.test.ts:176`).
  - `get-subscription-metrics.test.ts` fakes the clock (`:220-226`), mocks `@/lib/stripe/server` but
    keeps the real `isCancellationScheduled`, and has `setStripe` failure switches (`:184`).
  - Its invoice mock ignores `status` (`:212-217`).
  - Expected values are literals.
- **Page test fixture:** `metrics()` (`page.test.tsx:44-103`) is cast `as SubscriptionMetrics`, so a
  new field still typechecks and then crashes at render. Add it to the fixture.
- **Two page assertions the new section collides with:**
  - `page.test.tsx:334` asserts there is no `'$0.00'` anywhere on the page. Its subject is the LTV
    card.
  - `page.test.tsx:123` asserts there is no `'October'` on the last evening of September.
- **Do not double-count:** `mrrSubs` (`subscription-metrics.ts:607`) concatenates `active` and
  `pastDue` without de-duplicating (backlog `.turbo/improvements.md:2939`). The renewal sum must key
  by id.

### Proposed Alignment
- Add pure, injected-`now` functions to `month-projection.ts`, reusing its private helpers in place.
- Wire them in `getSubscriptionMetrics` from the unbounded lists, with `available` built from their
  `.ok` flags.
- Render with Month Projection's unavailable branch.
- Departures, each covered by a step below:
  - Move `getInterval` into `month-projection.ts`.
  - Add a fee helper.
  - Add the first per-subscription walk over invoice dates.
  - Fix the two page-test collisions.

## Implementation Steps

1. **Start from the prepared worktree.**
   - Work in `C:/pitchrank-stripe-forecast`, on branch `feat/stripe-cash-forecast`, cut from
     `origin/main` `94323d915`.
   - Do **not** work in `C:/PitchRank`. It sits on an unrelated branch with staged work in its shared
     index.
   - Before editing, run `git -C C:/pitchrank-stripe-forecast status --short`. It should list
     exactly two entries. If anything else appears, stop and ask.
     - `?? .turbo/plans/stripe-cash-forecast.md`: this plan.
     - ` M .turbo/improvements.md`: the backlog entry IMP-409 (pr_wait), added during planning.
       It ships with this PR and is not part of the feature.

     The design doc arrives in Step 2.
   - Then run `git fetch` and `git log --oneline HEAD..origin/main -- frontend/lib/admin frontend/app/mission-control frontend/test/fixtures.ts`.
     If it lists commits, merge `origin/main` (never rebase) and re-check the anchors this plan
     cites.
   - The worktree has no `node_modules`. Run `npm ci --no-audit --no-fund` in
     `C:/pitchrank-stripe-forecast/frontend`. Prefer it to a junction, which auto mode may refuse.
2. **Put the design doc in the repo.**
   - Copy the approved design from the planning session's scratchpad to
     `docs/superpowers/specs/2026-11-24-stripe-cash-forecast-design.md`.
   - Drop its "Destination once approved" line.
   - If the scratchpad file is gone, stop and ask the owner. Do not rebuild it from memory.
3. **Move `getInterval` to `month-projection.ts`.**
   - Cut `getInterval` (`subscription-metrics.ts:250-255`) and export it from `month-projection.ts`
     unchanged.
   - Import it in `subscription-metrics.ts` for its two callers (`:311`, `:343`). This avoids an
     import cycle, since `subscription-metrics` already imports from `month-projection`.
   - Insert after an existing function's closing brace, never between a function and its doc
     comment.
4. **Add the fee helper.**
   - In `month-projection.ts`, add `STRIPE_FEE_PERCENT = 0.029` and `STRIPE_FEE_FIXED_CENTS = 30`.
   - Add `netOfStripeFee(cents: number): number`. It returns `0` when `cents <= 0`, because there
     is no charge and so no fee. Otherwise it returns `cents − Math.round(cents × 0.029 + 30)`.
   - Name Stripe's standard US card pricing on the fee constants, and keep the 699 → 649 and
     6999 → 6766 examples in its tests rather than its doc comment.
   - Apply it once per expected charge, not to a sum.
5. **Add `computeRenewalCollectionRate`.**
   - Signature:
     `computeRenewalCollectionRate(subs, paidInvoices, now: Date, paidSubIds, excludedEmails): RateEstimate`.
   - *Who counts:* each subscription whose `getInterval` is `'month'`, that is in `paidSubIds`, and
     that is not excluded.
   - *Renewal dates:* `T_k = addMonthsClamped(billing_cycle_anchor, k)` for `k ≥ 1`, each computed
     from the anchor rather than chained. A day-31 anchor clamps to the month's last day and returns
     to 31 later, as Stripe does. Compute in UTC.
   - Stop at the first `T_k ≥ now − RENEWAL_SETTLE_DAYS × day`, with `RENEWAL_SETTLE_DAYS = 21`. That
     leaves time for Stripe's retries, which are an account setting.
   - **A subscription's walk also ends at its first miss.** That miss counts once, and no later
     dates are scored. This is the forecast's own counting rule, not a statement about Stripe's
     retries:
     - An `unpaid` or long-`past_due` subscription keeps reaching renewal dates with `canceled_at`
       and `ended_at` both null.
     - For `unpaid`, Stripe documents that later invoices are created and closed without an
       attempt (`Subscriptions.d.ts:217` in the pinned typings).
     - A `past_due` one may still be retried. The paid-only invoice list cannot tell a retry from
       no attempt at all.

     Without the stop, one stalled subscription adds a miss every month for as long as it stays
     open. Live data on 2026-11-24 had `past_due` subscriptions open past more than one renewal.
   - *Eligible:* a renewal date counts only if, `RENEWAL_NOTICE_DAYS = 7` days before `T_k`, the
     subscriber had not asked to cancel (`canceled_at` null or later than that) and service had not
     ended (`ended_at` null or later than that).
   - *Collected:* some lifetime paid invoice of that subscription (`getInvoiceSubscriptionId`) has
     `billing_reason === 'subscription_cycle'`, has `created` within `RENEWAL_MATCH_DAYS = 2` days of
     `T_k`, and passes the same cash or discounted-activation test as `collectPaidSubscriptionIds`.
     Extract that test into a private `isActivatingPayment(invoice)` and have
     `collectPaidSubscriptionIds` call it, so there is one definition.
   - *Fallback:* return through `finalizeRate`, with `FALLBACK_RENEWAL_RATE = 1 − FALLBACK_CHURN_RATE`.
     It is derived from an already-published constant, so it adds no new figure.
   - Group invoices by subscription once, as a `Map` from id to `created[]`, not by scanning per
     date.
   - Doc comment points to note:
     - Stripe does not document `canceled_at` for a cancellation made through `cancel_at` alone.
       Measured on 2026-11-24, every live cancellation of that kind (flexible billing mode, from the
       Customer Portal) had `canceled_at` set to the request time, at or before `ended_at`. So the
       7-day check reads those cancellations correctly.
     - A plan switch resets the anchor, so its renewals read as misses. No live subscription had
       switched as of 2026-11-24.
     - Only paid invoices are fetched.
   - Annual renewals use the same rate until annual history exists.
6. **Add the lifetime per-plan conversion.**
   - `computeLifetimeConversionByPlan(subs, paidSubIds, now: number, excludedEmails): { month: RateEstimate; year: RateEstimate }`.
   - It calls `computeTrialConversionRate` once per plan, with the subscriptions filtered by
     `getInterval` and `windowStart: 0`.
7. **Add `buildCashForecast`.**
   - Signature:
     `buildCashForecast({ now: Date, subs, conversion: { month, year }, renewalRate, excludedEmails })`.
     `subs` is the de-duplicated union of every status list.
   - It returns `CashForecast = { renewalRate: RateEstimate; conversion: { month; year }; windows: { week; fortnight; month } }`.
     Each window is `{ end: number /* seconds */; renewals; trials; newTrials: number | null; total }`.
   - *Windows:* `week` and `fortnight` end at `nowSec + 7 / 14 × day`. `month` ends at
     `monthsBack(now, 0).monthEnd`. Every sum covers `[nowSec, end)`.
   - *Renewals:* subscriptions passing `isStillSubscribed` and not excluded. Group each
     subscription's priced items (skip `!recurring || unit_amount == null`, use `quantity ?? 1`) by
     `current_period_end`. Each group is one charge: `netOfStripeFee(Σ cents) × renewalRate.rate`.
   - *Trials:* subscriptions with `status === 'trialing'` that are not excluded, including those set
     to cancel. One charge at `trial_end`: `netOfStripeFee(Σ item cents) × conversion[plan].rate`.
   - *Null plans:* skip any subscription whose `getInterval` is null on both the trial and new-trial
     paths. Otherwise `conversion[null]` is undefined and the sum becomes NaN. Renewals do not read
     a plan.
   - *New trials:*
     - `perDay = Σ over subscriptions with trial_start in [nowSec − 14 × day, nowSec)`, not excluded,
       of `conversion[plan].rate × netOfStripeFee(Σ item cents)`, divided by 14.
     - `newTrials = perDay × max(0, windowDays − TRIAL_DAYS)`, where
       `windowDays = (end − nowSec) / day`.
     - `newTrials` is `null` when `windowDays ≤ TRIAL_DAYS`, because no trial that starts later can
       end inside the window.
   - *Units:* cents are converted to dollars at the end. Round each part to the cent, and make
     `total` the sum of the rounded parts, so the breakdown adds up exactly.
   - The doc comment says why trials set to cancel are included (the rate was measured over all
     trials) and that Month Projection deliberately treats them otherwise.
8. **Wire it in `getSubscriptionMetrics` and the type.**
   - Add `cashForecast: { available: boolean } & CashForecast` to `SubscriptionMetrics`.
   - Compute `everPaidIds`, then:
     - `conversionByPlan = computeLifetimeConversionByPlan([...everySub.values()], everPaidIds, nowSec, excludedEmails)`
     - `renewalRate = computeRenewalCollectionRate([...everySub.values()], lifetimePaidInvoices.items, now, everPaidIds, excludedEmails)`
     - `buildCashForecast({ now, subs: [...everySub.values()], ... })`
   - `available` is `statusListsOk && lifetimePaidInvoices.ok`. When it is false, pass empty lists so
     nothing confident is computed, mirroring `measurable`.
   - Preserve every existing field and its wiring. This step only adds.
9. **Render the Forecast section in `page.tsx`.**
   - Place it directly after the Month Projection `<section>` (ends at `:205`), with the same heading
     row: `<h2>Forecast</h2>`.
   - The right-hand span reads `after Stripe's fee` when available, or `could not be loaded`.
   - When unavailable, show one `<Card variant="flat">` sentence, as at `:167-174`, saying Stripe did
     not return the data the forecast is built from.
   - When available, show a `grid gap-4 md:grid-cols-3` of three `KpiCard`s, with
     `value = formatDollars(total)`:
     - **`Next 7 days`**: sub-line `renewals $a · trials $b`.
     - **`Next 14 days`**: sub-line `renewals $a · trials $b · new trials $c`.
     - **`Rest of {Month}`**: sub-line `through {Mon D} · renewals $a · trials $b`, adding
       `· new trials $c` when non-null.
   - Derive both `{Month}` (long month name) and `{Mon D}` from `windows.month.end − 1` second,
     formatted in `BUSINESS_TIMEZONE`. Do not use the page's `monthName`: that comes from
     `generatedAt`, which is stamped after the Stripe reads, while the window comes from `nowSec`,
     taken before them. A load that spans midnight at month end would otherwise show
     "Rest of October · through Sep 30". Formatting `end` itself would print the 1st of the next
     month.
   - Omit the `new trials` part whenever `newTrials` is null.
10. **Tests.**
    - **Fixtures:** add `billingCycleAnchor` to `makeStripeSubscription` (`fixtures.ts:195`), defaulting
      to `trialEnd ?? startDate`. `startDate` defaults to `created = 0`, so a no-trial fixture
      anchors at 1970. Every test that scores renewals sets the anchor explicitly.
    - **`month-projection.test.ts`** (literal expectations, one fixture row per condition, invented
      values):
      - `netOfStripeFee(699) === 649`, `netOfStripeFee(6999) === 6766` and `netOfStripeFee(0) === 0`.
      - Renewal rate, one row per condition:
        - collected;
        - missed;
        - an `unpaid` subscription open for four renewal dates contributes exactly one miss, and
          advancing `now` by a month adds nothing;
        - a miss followed by a later paid renewal still contributes only the one miss;
        - asked to cancel more than 7 days before (ineligible);
        - asked to cancel inside the 7 days (eligible, missed);
        - inside the settle window (ignored);
        - internal email;
        - a paid invoice two days off versus three days off;
        - for a subscriber already in `paidSubIds` through an earlier payment, the payment test is
          applied at the date match. A matched `subscription_cycle` invoice with `amountPaid: 0`,
          `total: 0` and no discount is a miss. One with `total: 0` and a discount is collected.
          Assert the literal `observed` and `sample`, so a matcher that skips
          `isActivatingPayment` fails;
        - a `subscription_create` invoice is not a renewal;
        - a day-31 anchor;
        - below `MIN_COHORT_SAMPLE`, which takes the fallback.
      - Lifetime conversion split by plan, ignoring a trial that is still running.
      - `buildCashForecast`:
        - each window's boundaries, including a charge exactly at `end`, which is excluded;
        - a scheduled-cancellation renewal is excluded;
        - a set-to-cancel trial is included;
        - an internal email is excluded;
        - two items with one `current_period_end` make one charge, with the fee applied once;
        - two separate 699 renewals in one window total `2 × 649` cents × rate. A fee taken on
          the sum would give `1398 − 71`;
        - `newTrials` is null for the 7-day window and for a rest-of-month window of 7 days or
          fewer;
        - `newTrials` is positive for the 14-day window and has a literal value. The fixture
          includes one trial started 13 days ago, which counts, and one started 15 days ago, which
          does not;
        - a trialing subscription with no recurring price contributes nothing. Build it with
          `makeStripeSubscription`, then set `items.data[0].price.recurring` to null. Give it
          `trial_start` 3 days ago and `trial_end` 4 days ahead, so it lands inside both the
          trailing 14 days and the week. Its cents are 0, but `0 × conversion[null]` is still NaN,
          so the guard is what keeps it out. Assert that `trials` and the fortnight's `newTrials`
          are each finite and equal to their values without that row. Mutate the trial-path skip
          and the new-trial-path skip one at a time;
        - the parts add exactly to `total`.
    - **`get-subscription-metrics.test.ts`:** the current fixture cannot see renewals at all.
      - No monthly subscription renews inside any window. `matured` sets `currentPeriodEnd` to
        Oct 5 (`:50`), and `NOW` is Sept 16.
      - Every `PAID` invoice is dated `nowSec − 10 × DAY` (`:154`), inside the settle window. The
        one exception is `sub_unpaid`'s invoice at `nowSec − 400 × DAY` (`:157`), the only invoice
        older than 187 days.

      **Keep every existing literal passing.** The shared `allSubscriptions()` feeds literal
      assertions on `activePaid` (`:237`), MRR (`:247`), churned subscribers (`:329`) and growth.
      Adding a row there, or returning one row from two status lists, changes them. So:
      - **In the shared fixture, change only fields no current code reads.**
        - Move `sub_m1`'s `currentPeriodEnd` inside the 7-day window. No existing assertion reads
          a monthly item's period end, because `countAnnualRenewals` filters to `year`.
        - Give the ever-paid monthly rows explicit `billingCycleAnchor` values. Find that set by
          enumerating the fixture rather than from a list here: the `PAID` ids built with interval
          `month`, plus `sub_unpaid`. `sub_past_due` is annual (`:117`) and never feeds the rate.
      - **Renewal invoices.** Add `subscription_cycle` paid invoices at the reconstructed renewal
        dates to `paidInvoices()`. They are for subscriptions already in `PAID`, so no paid-id set
        changes.
      - **The lifetime-only renewal.** Anchor `sub_unpaid` exactly one calendar month before its
        `:157` invoice, so that invoice is its first renewal (collected) and the next date is its
        first miss. Then passing the bounded `paidInvoices` instead of `lifetimePaidInvoices`
        changes the measured rate.
      - **Everything else forecast-specific** goes in a per-test `subscriptionsList.mockImplementation`
        override, as the tests at `:518` and `:536` do.

      Tests:
      - **End to end:** drive `getSubscriptionMetrics` and assert `cashForecast.available`, the
        measured `renewalRate` (`isFallback: false`, literal `observed`/`sample`), and the week
        window's literal renewals, trials and total.
      - **Deduplication at its real boundary:** in a per-test override, return one billable active
        subscription from the `past_due` call as well. Assert the integrated renewal dollars count
        it once.
      - **An annual past-due renewal, charged in full:** in a per-test override, give a `past_due`
        annual subscription with quantity 2 a `currentPeriodEnd` inside the week. Assert it
        contributes `netOfStripeFee(2 × 6999) = 13562` cents × the renewal rate. That catches a
        dropped `past_due` list, a dropped annual plan, or dividing by 12 as `computeMrr` does.
      - **Lifetime evidence reaches trial conversion:** in a per-test override, add a completed
        monthly trial whose only paid invoice is older than 187 days. Assert the literal `observed`
        and `sample` of `cashForecast.conversion.month`, so substituting the bounded paid ids in the
        conversion call fails.
      - **The lifetime request:** make the `invoicesList` double reject any request whose `status`
        is not `'paid'`. Assert that the lifetime call (the one with no `created`) was made with
        `status: 'paid'` and `limit: 100`.
      - **Unavailable:** flip one `setStripe` failure (the trialing list, then lifetime invoices)
        and assert `available === false`.
      - **Still available:** flip `cohortThrows`, then `paidThrows` (the two 187-day fetches).
        Assert `cashForecast.available === true` with a literal non-zero week total, so gating the
        forecast on Month Projection's `measurable` fails.
    - **`page.test.tsx`:**
      - Add `cashForecast` to the `metrics()` fixture, giving the three windows distinct totals
        and a positive `newTrials` for the 14-day one.
      - Assert each card's value and sub-line beside its own label, so swapping totals between
        cards fails. Read one card with `flatten` from `frontend/test/flatten.ts`:
        `flatten(tree).find((el) => el.props.label === 'Next 7 days')`, then `textOf` that element.
        `KpiCard` is not exported, so its `label` prop is the only handle. Do not write a second
        tree walker.
      - Assert that `new trials` is absent from the 7-day card.
      - Assert the unavailable sentence, with no card labels.
      - On the last evening of September, assert it shows `Rest of September` and `through Sep 30`,
        and still no `October`.
      - Set `generatedAt` a few seconds into October (Phoenix) while `windows.month.end` is the
        Sept 30/Oct 1 boundary. Assert the Forecast card still reads `Rest of September` and
        `through Sep 30`.
      - Scope the `:334` `'$0.00'` assertion to the text of the card labelled `LTV` (`page.tsx:194`),
        read the same way, since a Forecast part can legitimately be $0.00.
    - Check each new guard by mutation, and confirm the failing test names include the new test.
11. **Document the section in the `stripe-billing-data` skill.**
    - Add a paragraph to `.claude/skills/stripe-billing-data/SKILL.md`, under "Measuring trial
      conversion", covering:
      - the Forecast's data sources (the unbounded lists and lifetime paid invoices);
      - the three rates and their fallbacks;
      - that it counts trials set to cancel while Month Projection does not, and why;
      - that renewal collection is measured only from paid invoices.
    - Add `buildCashForecast` to the "Where the code is" table row for `month-projection.ts`.
    - Correct the sentence ending "since Stripe does not document `canceled_at` for that path"
      (under "Measuring trial conversion"). Measured on 2026-11-24, every live cancellation made
      through `cancel_at` alone (flexible billing mode) had `canceled_at` set to the request
      time, at or before `ended_at`. Say that it is measured, not documented, and keep the date.
    - Under "Reading live Stripe from a session", add that the fee Stripe took on each charge is on
      its balance transaction (`fee`, `net`). Read it with the Stripe MCP's `GetBalanceTransactions`
      and `type: 'charge'`. Recent charges matched standard US card pricing (2.9% + 30¢), which is
      what `netOfStripeFee` assumes; check there first if the fee ever looks off.

## Verification

- Run from `C:/pitchrank-stripe-forecast/frontend`:
  - `npx vitest run lib/admin/__tests__/month-projection.test.ts lib/admin/__tests__/get-subscription-metrics.test.ts lib/admin/__tests__/subscription-metrics.test.ts app/mission-control/subscriptions/__tests__/page.test.tsx`.
    Every new test should pass, and the existing ones still pass unchanged, except the scoped
    `'$0.00'` assertion.
  - The full frontend gate: `npx eslint .`, `npx prettier --check .`, `npm run typecheck`,
    `npm run test`, and `npm run generate-llms && git diff --exit-code public/llms.txt`.
- **Mutations**, each killing a named new test on its own:
  - drop the `isStillSubscribed` filter;
  - drop the `RENEWAL_NOTICE_DAYS` check;
  - use `<=` at the window end;
  - apply the fee to the sum instead of per charge;
  - read `newTrials` for windows of 7 days or fewer;
  - format `end` instead of `end − 1`;
  - label the month card from `generatedAt`;
  - remove the de-duplication by id (killed by the end-to-end test);
  - remove the stop-at-first-miss;
  - drop the `cents <= 0` guard in `netOfStripeFee`;
  - pass the 187-day `paidInvoices` to the renewal rate;
  - drop `status: 'paid'` from the lifetime invoice call;
  - pass the 187-day paid ids to the conversion call;
  - skip `isActivatingPayment` in the renewal matcher;
  - remove the trial-path null-plan skip, and separately the new-trial-path one;
  - divide annual renewal cash by 12, and separately drop the `past_due` list;
  - gate `cashForecast.available` on `measurable`.
- After staging the SKILL.md edit, run `python -m pytest tests/unit/test_agent_doc_references.py`
  from the repo root. It checks every backticked path in `.claude/skills/*/SKILL.md` against
  `git ls-files`, so stage the design doc first.
- **No local preview:** the page needs the Vercel-only Stripe key and an admin sign-in.
- **Live check after merge:**
  - Recompute the three windows from Stripe with a scratchpad script that reads the same lists and
    the same rules, using the Stripe MCP `stripe_api_read`.
  - Compare it with the deployed page.
    - The renewals and trials parts should match to the cent, unless a renewal or trial moved
      between the two reads.
    - The new-trials part depends on the read time: `perDay × max(0, windowDays − TRIAL_DAYS)`,
      measured to a fixed month end. The page stamps `generatedAt` after its Stripe reads, so it
      is not the forecast's own instant. Bracket the page load (note the time before and after),
      and treat a new-trials gap within `perDay × (elapsed seconds / 86400)` as clock drift rather
      than a defect.
  - The renewal collection rate should not be the fallback, since the sample is well above
    `MIN_COHORT_SAMPLE`.
  - Report the figures to the owner in chat only.

## Context Files

- `docs/superpowers/specs/2026-11-24-stripe-cash-forecast-design.md`: the approved design and the
  owner's choices.
- `frontend/lib/admin/month-projection.ts`: where every new function goes, and the private helpers
  they reuse.
- `frontend/lib/admin/subscription-metrics.ts` (`:580-712`): the wiring, the `ok` flags and the
  `SubscriptionMetrics` type.
- `frontend/app/mission-control/subscriptions/page.tsx`: the Month Projection section to mirror,
  `KpiCard` and the formatters.
- `frontend/app/mission-control/subscriptions/__tests__/page.test.tsx`: the `metrics()` fixture and
  the two colliding assertions.
- `frontend/lib/admin/__tests__/get-subscription-metrics.test.ts`: the end-to-end mock and the
  failure switches.
- `frontend/test/fixtures.ts`: `makeStripeSubscription` and `makeStripeInvoice`.
- `.claude/skills/stripe-billing-data/SKILL.md`: the field locations, the $0-invoice trap, and the
  rule against a confident zero.
