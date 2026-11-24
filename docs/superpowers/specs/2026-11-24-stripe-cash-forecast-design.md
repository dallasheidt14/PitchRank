# Stripe cash forecast on the subscriptions page: design

Date: 2026-11-24. Size: small change. Approved by the owner on 2026-11-24.
No live business figures in this file; the repo is public.

## Intent

The owner wants an educated estimate of how much money Stripe will collect over the next 7 days,
the next 14 days, and by the end of the current month. It appears on
`/mission-control/subscriptions` and uses each plan's lifetime trial-to-paid rate.

## Goals, non-goals, anti-goals

- **Goal.** Three dollar figures, after Stripe's fee, each with a one-line breakdown of where the
  money comes from.
- **Non-goals.**
  - A day-by-day chart (approach B below; can be added later).
  - When collected money becomes available, or when it is paid out to the bank.
  - Refunds, disputes, and retries of past-due invoices.
  - Coupons: amounts are list prices, as `computeMrr` does.
- **Anti-goals.**
  - A confident $0 when a Stripe fetch failed. Show the section as unavailable, as Month
    Projection does.
  - A range. A range reads as a cap, so each window shows one figure.

## Approaches

- **A. Three cards, computed on each page load from data the page already fetches. Picked by the
  owner.**
- **B. A + a 30-day day-by-day chart.** It shows which days the money lands on, at roughly twice
  the work. Deferred.
- **C. Stripe's upcoming-invoice preview for each subscriber.** Exact to the cent, but about one
  Stripe call per subscriber on every load. Ruled out.

## Design

**Placement.** A new **Forecast** section directly below Month Projection, with the note "after
Stripe's fee". It has three cards:

1. **Next 7 days**
2. **Next 14 days**
3. **Rest of {Month}**, sub-line "through {Mon D}". The month ends at the start of the next month
   in `BUSINESS_TIMEZONE`.

Each card shows one dollar figure and a sub-line: `renewals $a · trials $b · new trials $c`.

**Placing and summing charges.** Every expected charge has a date. A window sums the charges dated
in `[now, window end)`. Internal emails (`HARDCODED_EXCLUDED_EMAILS`) are excluded throughout.

**Renewals.**
- *Which items:* every item on an `active` or `past_due` subscription without a scheduled
  cancellation (`isCancellationScheduled`).
- *Date:* the item's `current_period_end`.
- *Amount:* `price.unit_amount × quantity`.
- *Scaling:* the amount is scaled by the **renewal collection rate**: of past monthly renewal
  dates for activated subscribers who had not asked to cancel a week beforehand, the share
  followed by a paid invoice. Measured from the page's own lifetime lists. It falls back to a
  documented constant below `MIN_COHORT_SAMPLE`.
- *Annual renewals:* they use the same rate until annual renewal history exists.

**Current trials.**
- *Which trials:* every `trialing` subscription, including those already set to cancel.
- *Date and amount:* dated at `trial_end`, at the plan's price.
- *Scaling:* the plan's lifetime conversion rate (below).
- *Why trials set to cancel are included:* the rate was measured over all trials, including
  those that cancelled mid-trial. Applying it to all current trials compares like with like.
  Applying it only to the open pipeline would understate the figure, and the higher rate for
  trials that never cancelled would overstate it.

**Lifetime conversion rate per plan.**
- *Measured over:* trials whose `trial_end` is before now, split by the item's
  `recurring.interval`.
- *Counts as converted:* the subscription is in `collectPaidSubscriptionIds` over the lifetime
  paid invoices.
- *Fallback:* `FALLBACK_CONVERSION_RATE` when a plan's sample is below `MIN_COHORT_SAMPLE`.

**Trials not yet started.**
- *Daily rate per plan:* trials started in the trailing 14 days, divided by 14.
- *Which window it affects:* a new trial ends `TRIAL_DAYS` after it starts, so a window of `L`
  days gains `rate × max(0, L − TRIAL_DAYS)` trial endings per plan.
- *Value:* each ending is worth the plan's conversion rate × the plan's price.

**Stripe's fee.**
- *Per charge:* 2.9% of the amount + $0.30, rounded to the cent, then subtracted. This is Stripe's
  standard US card pricing: $0.50 on a $6.99 charge and $2.33 on a $69.99 one.
- *Where it applies:* every expected charge above is net of the fee.

**Unavailable.** The section is unavailable when any input list is not `ok`, the same rule as
`monthProjection.available`.

```
Forecast                                    after Stripe's fee
┌ Next 7 days ─────┐ ┌ Next 14 days ────┐ ┌ Rest of November ─┐
│ $___             │ │ $___             │ │ $___              │
│ renewals $_ ·    │ │ renewals $_ ·    │ │ through Nov 30    │
│ trials $_ ·      │ │ trials $_ ·      │ │ renewals $_ · …   │
│ new trials $_    │ │ new trials $_    │ │                   │
└──────────────────┘ └──────────────────┘ └───────────────────┘
```

## As built

The code differs from the design above in these ways:
- **Availability.** The section is unavailable when any of the five status lists or the lifetime
  paid invoices failed. It is not `monthProjection.available`: the 187-day cohort and paid invoices
  play no part.
- **No `new trials` part on short windows.** A trial that starts later cannot end within 7 days,
  so Next 7 Days never shows one, and Rest of {Month} drops it in the month's last 7 days.
- **Renewals for payers only.** Renewals are forecast only for subscribers who have paid
  before (an activating payment, as `collectPaidSubscriptionIds` counts one), the population the
  collection rate is measured on. A subscription left past due by a declined first charge is not
  forecast to renew.
- **Which renewal dates the rate scores:**
  - A date is scored only once 21 days have passed since it, so retries can land.
  - A date is left out when, a week ahead of it, the subscriber had asked to cancel or service had
    ended, even with no `canceled_at`.
  - A subscription is scored up to its first miss, so a stalled account counts once.
  - A date counts as collected when a paid `subscription_cycle` invoice was created within two
    days of it.
- **Exclusions.** Internal accounts are excluded through `getExcludedEmails()`, which adds
  `ADMIN_DASHBOARD_EXCLUDED_EMAILS` to the hard-coded list.
- **Labels.** The cards read "Next 7 Days" and "Next 14 Days", in the title case the page's
  other cards use (owner, 2026-11-24).
- **One month between rebuilt renewals.** The collection rate rebuilds past renewal dates one month
  apart, so it assumes `interval_count` 1; every live price had it as of 2026-11-24. The forecast's
  own dates come from `current_period_end` and assume nothing.

## Calls made by Claude (owner to check)

- Current trials are counted including those set to cancel, at the lifetime rate.
- Renewals are scaled by a measured collection rate, not counted in full.
- New trials use a trailing 14-day rate. The month-to-date rate is empty on the 1st.
- Placement is below Month Projection, with a single figure per card.

## Left to the builder

- Whether the pure functions go in `month-projection.ts` or a new `forecast.ts`.
- How renewal dates are reconstructed when measuring the collection rate.
- Test design: literal expected values, and one row per condition.
