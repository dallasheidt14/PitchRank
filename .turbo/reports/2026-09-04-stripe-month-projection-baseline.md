# Stripe month-projection baseline — 2026-09-04

## Bottom line

**47 unpaid invoices are sitting on $769.53, and 45 of them have no further retry scheduled.** These
subscribers did not cancel — they let a trial convert or a renewal come round, and the charge did not
clear. At September's rate that is roughly 20 lost customers this month, about $135 of MRR. Recovering
half would exceed every modelling correction in this document combined.

The projection itself: September is tracking **+29.3 net subscribers / +$198.51 MRR** for what lands
inside the month. Trial conversion is **47.3%**, close to the 47.8% the manual spreadsheet used; paid
churn is **16.07%**, well under the 25.68% it assumed, because that figure counted failed charges as
cancellations.

## Provenance

Source: the live PitchRank Stripe account, livemode, read 2026-09-04. 188 subscriptions
(2026-03-18 → 2026-09-04), 326 `paid`-status invoices, 47 `open`, 0 `uncollectible`.

The projection block — rates, trial counts, the month and cohort tables — was produced by running the
shipped functions over that data. The comparison material was not, and no shipped function computes it:
the 36.1% / 71.0% alternate conversion definitions, the weekday distribution, the prior-month trial
counts, and the 41-of-169 charge-failure figure are all ad-hoc analysis recorded here for context.

Internal/test emails are excluded by the shipped code but change nothing here: none of the four
addresses in `ADMIN_DASHBOARD_EXCLUDED_EMAILS` has a livemode customer.

## Account state

| | |
|---|---|
| Active | 60 (46 monthly, 14 annual) |
| MRR | $403.20 |
| Trialing | 15 (0 pending-cancel) |
| Past due | 2 |
| Canceled | 111 |
| Collected all-time | $1,909.62 across 138 real charges |

Prices: $6.99/mo, $69.99/yr. Trial length 7 days.

## Measuring conversion: three definitions, only one right

**Trial → paid conversion: 47.3%, 79 of the 167 trials that ended inside the 180-day window.**

| Method | Result | Why it is wrong |
|---|---|---|
| Current status is `active`/`past_due` | 36.1% | Writes off everyone who converted and later cancelled — measures retention, not conversion |
| Stripe advanced the billing period | 71.0% | Counts trials whose card was declined at conversion |
| **An invoice actually charged** | **47.3%** | — |

`status: "paid"` alone is not the third method: 168 of the 326 paid-status invoices are the $0 invoices
that open a trial. A fully-discounted invoice is also marked paid at $0 and *is* a real activation — but
only away from `billing_reason: subscription_create`, because Stripe copies a subscription-level discount
onto the trial-opening invoice too. Without that gate the predicate would identify "this subscription has
a coupon" rather than "this subscription activated". No coupon exists on the account today.

**Paid churn: 16.07%, 9 of 56 matured payers cancelling inside their first paid month.**

Measured from `ended_at`, not `canceled_at`: for a period-end cancellation Stripe records the *request*
time in `canceled_at`, so an annual subscriber who cancels days after converting but is served until
renewal would otherwise book as first-month churn up to a year early. Two subscriptions in the current
data turn on that distinction — it is the difference between 19.64% and 16.07%.

**Blended ARPU: $6.78/mo.** Roughly 20% of converters take the annual plan at $5.83 monthly-equivalent.

## Why the lookback is 180 days, and the fetch 187

Both rates need subscribers whose first paid month has finished, and that cohort is far smaller than the
subscriber count suggests: a 90-day window leaves 28 payers against 56 at 180 days, and measured churn
moves five points on sample size alone.

Subscriptions are fetched by *creation* date but the rates filter on *trial end*, so the fetch reaches
back `180 + TRIAL_DAYS`. Without the extra week the oldest trials inside the window belong to
subscriptions created before it and never fetched, and a card labelled "last 180 days" would report on
173.

## September projection (day 4 of 30)

11 trials in 4 days = 2.75/day → **82.5 projected trials, range 51–114**. Prior months: Jun 47, Jul 30,
Aug 53. September runs about 1.6× August, consistent with the season restart.

Two scopes are reported and must not be mixed.

**Lands inside September.** Counts what has already happened and estimates only the rest, so the figure
converges on the actual as the month fills rather than drifting from it. Includes August's carry-in (a
trial started Aug 30 converts Sept 6) and excludes September's late starters (a trial started Sept 28
converts in October).

| | |
|---|---|
| Already converted this month | 3 |
| Still to resolve | 71.3 |
| Gross new | +36.7 subs / $248.70 |
| Churned | −7.4 subs / $50.19 (1 already cancelled) |
| **Net** | **+29.3 subs / +$198.51** |

**September's whole cohort**, valued whenever it converts: 39.0 subs, $264.43 MRR, $1,645 lifetime value.
Average lifetime 6.2 months, LTV $42.16.

Churn is charged to monthly subscribers prorated over the days remaining, plus annual subscribers whose
renewal is still ahead inside the month at the full rate — a renewal is one dated event, not a risk spread
across the month. Zero annual subscriptions renew before 2027-04-05, so the annual at-risk count is 0
through March 2027. An earlier `rate / 12` approximation invented about 0.30 subscribers of churn per
month and would have reported the same figure for a month holding four renewals and a month holding none.

LTV is `1 / churn` derived from a rate that deliberately measures the first paid month — the period
subscribers are likeliest to leave — so it is a conservative floor rather than a true lifetime. With no
churn measured at all the card reads "not measurable": zero is a real rate, but rendering `1 / 0` as $0
would show perfect retention as a total loss.

## The leak

**41 of 169 ended trials (24.3%) had their charge fail at trial end.** They did not cancel; the payment
did not go through.

- 47 open invoices, **$769.53 outstanding**, every one attempted
- **45 have no further retry scheduled**
- Spread across every month: Apr 1, May 8, Jun 13, Jul 11, Aug 12, Sep 2

Whether Stripe will try again comes from `next_payment_attempt`, not from a count of attempts: the retry
ceiling is an account-level Smart Retries setting, and the recommended default is 8 over 2 weeks. The
converse does not hold either — after a hard decline Stripe keeps *scheduling* attempts that execute only
once a new card arrives, so 45 is a floor on the work outstanding rather than the whole of it. An earlier
draft of this report claimed "31 have exhausted all 3 retry attempts"; that inferred a ceiling of 3 and
was wrong in both directions.

The dashboard names these unpaid invoices rather than failed conversions. The open list mixes first-charge
failures with later renewal failures and nothing in the invoice separates them cheaply; invoices with no
subscription behind them are excluded, since a manual one-off going unpaid is not a failed subscriber
charge.

## Settled: no day-of-week adjustment

Trial starts by weekday (n=186): Mon 16.1%, Tue 22.0%, Wed 9.1%, Thu 12.4%, Fri 12.4%, Sat 12.4%,
Sun 15.6%. The elapsed Tue–Fri window holds 55.9% of trial volume against 57.1% of days — a 2%
underweight, i.e. noise. No weekend skew exists; do not build a weekday correction.

## Why the trial band ignores prior months

The range comes from the count's own sampling error, not a historical prior. Youth soccer is seasonal:
June–August is the off-season and September the restart, so blending a trailing average into an in-season
month drags the projection toward a different regime. The band widens early and tightens as days
accumulate, with no seasonality assumption either way. On an empty month it does not collapse to zero — a
count of zero cannot establish that no trial will arrive, so the upper bound falls back to the exact
one-sided 80% Poisson bound.

## Known limits

- **Currency is assumed USD.** Amounts are divided by 100 and formatted as dollars. Both live prices are
  USD and checkout validates against a two-price allowlist, so no other currency can enter through the
  product; a zero-decimal currency such as JPY would render wrong if one ever did.
- **Elapsed days are whole days.** Day-of-month is used directly, matching the spreadsheet this replaces,
  so a projection loaded early on the 1st extrapolates from a fraction of a day.
- **A pending cancellation is treated as an average-rate risk, not a certainty.** One active annual
  subscription carries `cancel_at_period_end` with a June 2027 period end; when that month arrives it will
  be multiplied by the churn rate rather than counted as the certain loss it is. Zero effect before then.
- **Lost MRR is priced at acquisition ARPU**, not at the mix actually at risk. Today that understates it by
  about $1.58 on a $50 line — an order of magnitude below the sampling error on the churn rate itself.
- **The open-invoice fetch is unbounded** — no date floor and no page cap, unlike the paid fetch beside it.
  Matches the existing `canceled` subscription fetch; fine at 47 invoices, poor at 4,700.
