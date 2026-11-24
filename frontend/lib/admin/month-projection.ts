import 'server-only';
import type Stripe from 'stripe';
import { isCancellationScheduled } from '@/lib/stripe/server';
import { getCustomerEmail, MIN_COHORT_SAMPLE, SECONDS_PER_DAY, TRIAL_DAYS } from './constants';
import { BUSINESS_TIMEZONE, startOfMonth, wallClockDate } from './timezone';

/** Window over which a converted subscriber is checked for surviving their first paid month. */
const CHURN_WINDOW_DAYS = 30;

const TRIALS_BY_MONTH_FIRST = { year: 2026, month: 6 };

/** z for an 80% interval — the band around the projected trial count. */
const PROJECTION_Z = 1.2816;

/**
 * One-sided 80% upper bound on a Poisson count when nothing has been observed,
 * i.e. −ln(1 − 0.8). Without it the band collapses to zero width on an empty
 * month and asserts that no trial will arrive, which is the one thing a month
 * with no data cannot establish.
 */
const POISSON_ZERO_UPPER = 1.6094;

/**
 * Rates used when a cohort is too small to measure, carried over from the manual
 * spreadsheet this dashboard replaced.
 * `.turbo/reports/2026-09-04-stripe-month-projection-baseline.md` records how they
 * were derived and how they compare to measured values.
 */
export const FALLBACK_CONVERSION_RATE = 0.478;
export const FALLBACK_CHURN_RATE = 0.2568;
/** Derived rather than measured, so this public file adds no business figure of its own. */
export const FALLBACK_RENEWAL_RATE = 1 - FALLBACK_CHURN_RATE;

/** Stripe's standard US card pricing, taken from every charge. */
const STRIPE_FEE_PERCENT = 0.029;
const STRIPE_FEE_FIXED_CENTS = 30;

/** How long after a renewal date a missing payment waits before it counts as a miss; retries are an account setting. */
const RENEWAL_SETTLE_DAYS = 21;
/** A cancellation requested at least this long before a renewal takes that renewal out of the sample. */
const RENEWAL_NOTICE_DAYS = 7;
/** How far from a renewal date the invoice that collected it may have been created. */
const RENEWAL_MATCH_DAYS = 2;
const NEW_TRIAL_PACE_DAYS = 14;

export type RateEstimate = {
  rate: number;
  observed: number;
  sample: number;
  excluded: number;
  isFallback: boolean;
};

export type CohortWindow = {
  subs: Stripe.Subscription[];
  paidSubIds: Set<string>;
  now: number;
  windowStart: number;
  excludedEmails: Set<string>;
};

export type MonthCohort = {
  label: string; // e.g. "September 2026"
  sample: number; // trials that started that month
  converted: number;
  retained: number; // of `converted`, still subscribed with no cancellation scheduled
  excluded: number;
};

export type MonthTrials = {
  label: string; // e.g. "September 2026"
  trials: number;
};

export type TrialProjection = {
  trialsToDate: number;
  /** Fraction of the month actually elapsed. Drives every rate; see `monthBounds`. */
  daysElapsed: number;
  /** Calendar day number, for display only — never a denominator. */
  dayOfMonth: number;
  daysInMonth: number;
  dailyRate: number;
  projected: number;
  low: number;
  high: number;
  /** Trials whose window closed inside this month and which activated — counted, not estimated. */
  landedConverted: number;
  /** Trials landing inside this month whose outcome is not yet known. */
  landingUnresolved: number;
};

export type MonthProjection = {
  trials: TrialProjection;
  conversion: RateEstimate;
  churn: RateEstimate;
  arpu: number;
  grossNewSubs: number;
  observedChurn: number;
  churnedSubs: number;
  annualRenewalsAhead: number;
  netSubs: number;
  netMrr: number;
  avgLifetimeMonths: number | null;
  ltv: number | null;
};

export type Plan = 'month' | 'year';

/** Expected cash collected from now until `end`, in dollars after Stripe's fee. */
export type ForecastWindow = {
  /** Exclusive, in seconds. */
  end: number;
  renewals: number;
  trials: number;
  /** Null when the window is too short for a trial that has not started yet to end inside it. */
  newTrials: number | null;
  total: number;
};

export type CashForecast = {
  renewalRate: RateEstimate;
  conversion: Record<Plan, RateEstimate>;
  windows: { week: ForecastWindow; fortnight: ForecastWindow; month: ForecastWindow };
};

/**
 * Subscription IDs whose trial produced a real activation.
 *
 * `status: 'paid'` alone does not mean this — a trial opens with a $0 invoice
 * Stripe also marks paid. Cash collected is the usual evidence; a fully
 * discounted invoice activates a subscription without requiring payment, so a
 * discounted $0 total counts too, but only away from `subscription_create`.
 * Stripe copies a subscription-level discount onto every invoice it generates,
 * including the trial-opening one, so without that gate the discount arm would
 * identify "this subscription has a coupon" rather than "this subscription
 * activated". The cash arm keeps accepting `subscription_create`, which is the
 * activation invoice for a returning customer who gets no trial.
 */
export function collectPaidSubscriptionIds(invoices: Stripe.Invoice[]): Set<string> {
  const out = new Set<string>();
  for (const invoice of invoices) {
    if (!isActivatingPayment(invoice)) continue;
    const id = getInvoiceSubscriptionId(invoice);
    if (id) out.add(id);
  }
  return out;
}

function isActivatingPayment(invoice: Stripe.Invoice): boolean {
  const paidCash = invoice.amount_paid > 0;
  const discountedActivation =
    invoice.total === 0 && invoice.discounts.length > 0 && invoice.billing_reason !== 'subscription_create';
  return paidCash || discountedActivation;
}

/**
 * The subscription that generated an invoice.
 *
 * `parent.subscription_details` is where this lives from API version
 * 2025-03-31.basil onward, and the client pins a later version still. The
 * line-item walk is a fallback only: `lines` is a sublist that paginates, so on
 * an invoice carrying enough line items the subscription row can be absent.
 */
function getInvoiceSubscriptionId(invoice: Stripe.Invoice): string | null {
  const fromParent = invoice.parent?.subscription_details?.subscription;
  if (typeof fromParent === 'string') return fromParent;
  if (fromParent) return fromParent.id;
  for (const line of invoice.lines?.data ?? []) {
    const fromLine = line.parent?.subscription_item_details?.subscription;
    if (fromLine) return fromLine;
  }
  return null;
}

/**
 * When a subscription stopped being served.
 *
 * `ended_at` before `canceled_at`: for a period-end cancellation Stripe records
 * the request time in `canceled_at`, so a subscriber who cancels days after
 * converting but is served until renewal would otherwise be booked as
 * first-month churn up to a year early.
 */
function getServiceEnd(sub: Stripe.Subscription): number | null {
  return sub.ended_at ?? sub.canceled_at ?? null;
}

function isExcluded(sub: Stripe.Subscription, excludedEmails: Set<string>): boolean {
  return excludedEmails.has(getCustomerEmail(sub).toLowerCase());
}

export function getInterval(sub: Stripe.Subscription): Plan | null {
  const recurring = sub.items.data[0]?.price?.recurring;
  if (recurring?.interval === 'month') return 'month';
  if (recurring?.interval === 'year') return 'year';
  return null;
}

/**
 * Trial → paid conversion over the trials that ended inside the window.
 *
 * Measured against activations rather than current status: scoring on status
 * writes off every subscriber who converted and later cancelled, conflating
 * conversion with retention, while scoring on Stripe advancing the billing
 * period counts trials whose card was declined at conversion.
 *
 * `windowStart` bounds `trial_end`, not subscription creation, so the window
 * this reports is the window it measured.
 */
export function computeTrialConversionRate({
  subs,
  paidSubIds,
  now,
  windowStart,
  excludedEmails,
}: CohortWindow): RateEstimate {
  const { trials, excluded } = trialsIn(subs, 'trial_end', windowStart, now, excludedEmails);
  const observed = trials.filter((sub) => paidSubIds.has(sub.id)).length;
  return finalizeRate(observed, trials.length, excluded, FALLBACK_CONVERSION_RATE);
}

/**
 * Of the trials that ended inside the window and activated, how many are still
 * subscribed today with no cancellation scheduled. Same cohort and activation
 * test as `computeTrialConversionRate`, so `retained` is a subset of its count.
 */
export function computeRetention({ subs, paidSubIds, now, windowStart, excludedEmails }: CohortWindow): number {
  const { trials } = trialsIn(subs, 'trial_end', windowStart, now, excludedEmails);
  return trials.filter((sub) => paidSubIds.has(sub.id) && isStillSubscribed(sub)).length;
}

/**
 * Trials that started in the calendar month `monthsAgo` before the current one
 * in {@link BUSINESS_TIMEZONE}, how many activated, and how many of those are
 * still subscribed today with no cancellation scheduled.
 *
 * `converted` uses the same activation test as `computeTrialConversionRate`, so
 * the cards cannot disagree on what counts as a conversion. A trial started in
 * the last days of a month is still running early in the next, so it counts as
 * not converted until it activates.
 */
export function computeMonthCohort(
  subs: Stripe.Subscription[],
  paidSubIds: Set<string>,
  now: Date,
  monthsAgo: number,
  excludedEmails: Set<string>
): MonthCohort {
  const { monthStart, monthEnd, label } = monthsBack(now, monthsAgo);
  const { trials, excluded } = trialsIn(subs, 'trial_start', monthStart, monthEnd, excludedEmails);
  const converted = trials.filter((sub) => paidSubIds.has(sub.id));
  return {
    label,
    sample: trials.length,
    converted: converted.length,
    retained: converted.filter(isStillSubscribed).length,
    excluded,
  };
}

/**
 * Trials started in each calendar month from {@link TRIALS_BY_MONTH_FIRST}
 * through the current one, oldest first, in {@link BUSINESS_TIMEZONE}. The
 * current month is a count to date. `subs` must reach back to the first month:
 * a rolling date window slides forward and empties the oldest months.
 */
export function countTrialsByMonth(subs: Stripe.Subscription[], now: Date, excludedEmails: Set<string>): MonthTrials[] {
  const { year, month } = wallClockDate(now);
  const monthsSinceFirst = (year - TRIALS_BY_MONTH_FIRST.year) * 12 + (month - TRIALS_BY_MONTH_FIRST.month);
  const months: MonthTrials[] = [];
  for (let monthsAgo = monthsSinceFirst; monthsAgo >= 0; monthsAgo -= 1) {
    const { monthStart, monthEnd, label } = monthsBack(now, monthsAgo);
    const { trials } = trialsIn(subs, 'trial_start', monthStart, monthEnd, excludedEmails);
    months.push({ label, trials: trials.length });
  }
  return months;
}

/**
 * Of everyone who ever activated, how many have since left: counted per person
 * by email, so a subscriber who cancels and later resubscribes is not churned.
 * A person counts as churned once every subscription they paid on is canceled.
 * `everPaidIds` must be lifetime activation evidence: a window-bounded invoice
 * list would drop long-standing subscribers and overstate churn.
 */
export function computeLifetimeChurn(
  subs: Stripe.Subscription[],
  everPaidIds: Set<string>,
  excludedEmails: Set<string>
): { paid: number; churned: number } {
  const stillSubscribed = new Map<string, boolean>();
  for (const sub of subs) {
    if (!everPaidIds.has(sub.id) || isExcluded(sub, excludedEmails)) continue;
    const email = getCustomerEmail(sub).toLowerCase();
    const person = email.includes('@') ? email : sub.id;
    stillSubscribed.set(person, (stillSubscribed.get(person) ?? false) || sub.status !== 'canceled');
  }
  const people = [...stillSubscribed.values()];
  return { paid: people.length, churned: people.filter((here) => !here).length };
}

function isStillSubscribed(sub: Stripe.Subscription): boolean {
  return (sub.status === 'active' || sub.status === 'past_due') && !isCancellationScheduled(sub);
}

function trialsIn(
  subs: Stripe.Subscription[],
  edge: 'trial_start' | 'trial_end',
  windowStart: number,
  windowEnd: number,
  excludedEmails: Set<string>
): { trials: Stripe.Subscription[]; excluded: number } {
  const trials: Stripe.Subscription[] = [];
  let excluded = 0;
  for (const sub of subs) {
    const at = sub[edge];
    if (at === null || at >= windowEnd || at < windowStart) continue;
    if (isExcluded(sub, excludedEmails)) {
      excluded += 1;
      continue;
    }
    trials.push(sub);
  }
  return { trials, excluded };
}

/**
 * Monthly churn among subscribers who actually activated.
 *
 * Restricted to activated subscriptions so a card declined at trial end is never
 * counted as a customer leaving — that is a collection failure, and mixing the
 * two inflates churn and deflates conversion at once.
 *
 * This measures the first paid month specifically, which runs hot as an ongoing
 * rate: subscribers are likeliest to leave just after the first charge lands.
 * Projecting with it errs toward understating growth.
 */
export function computePaidChurnRate({
  subs,
  paidSubIds,
  now,
  windowStart,
  excludedEmails,
}: CohortWindow): RateEstimate {
  const matured = now - CHURN_WINDOW_DAYS * SECONDS_PER_DAY;
  let sample = 0;
  let observed = 0;
  let excluded = 0;
  for (const sub of subs) {
    const trialEnd = sub.trial_end;
    if (trialEnd === null || trialEnd > matured || trialEnd < windowStart) continue;
    if (!paidSubIds.has(sub.id)) continue;
    if (isExcluded(sub, excludedEmails)) {
      excluded += 1;
      continue;
    }
    sample += 1;
    if (sub.status !== 'canceled') continue;
    const endedAt = getServiceEnd(sub);
    if (endedAt !== null && endedAt > trialEnd && endedAt - trialEnd <= CHURN_WINDOW_DAYS * SECONDS_PER_DAY) {
      observed += 1;
    }
  }
  return finalizeRate(observed, sample, excluded, FALLBACK_CHURN_RATE);
}

function finalizeRate(observed: number, sample: number, excluded: number, fallback: number): RateEstimate {
  if (sample < MIN_COHORT_SAMPLE) {
    return { rate: fallback, observed, sample, excluded, isFallback: true };
  }
  return { rate: observed / sample, observed, sample, excluded, isFallback: false };
}

/** The calendar month `n` before the one containing `now`, in the business timezone. */
export function monthsBack(now: Date, n: number): { monthStart: number; monthEnd: number; label: string } {
  let { monthStart, monthEnd } = monthBounds(now);
  for (let i = 0; i < n; i += 1) {
    ({ monthStart, monthEnd } = monthBounds(new Date((monthStart - 1) * 1000)));
  }
  const label = new Date(monthStart * 1000).toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
    timeZone: BUSINESS_TIMEZONE,
  });
  return { monthStart, monthEnd, label };
}

/**
 * The current calendar month in the business timezone, as instants.
 *
 * `daysElapsed` is how much of the month has actually passed, fractionally.
 * The calendar day number overstates that by up to a full day — on the 6th at
 * one minute past midnight, `6` claims six days of evidence for a few seconds
 * of it — which understates every run rate derived from it and made the
 * projection lurch downward each time the day ticked over. `dayOfMonth` keeps
 * the integer for display, where "day 5.2 of 30" would read as a defect.
 */
function monthBounds(now: Date): {
  monthStart: number;
  monthEnd: number;
  daysInMonth: number;
  daysElapsed: number;
  dayOfMonth: number;
} {
  const { year, month, day } = wallClockDate(now);
  const monthStartMs = startOfMonth(year, month);
  const monthEndMs = month === 12 ? startOfMonth(year + 1, 1) : startOfMonth(year, month + 1);
  return {
    monthStart: monthStartMs / 1000,
    monthEnd: monthEndMs / 1000,
    daysInMonth: new Date(Date.UTC(year, month, 0)).getUTCDate(),
    daysElapsed: (now.getTime() - monthStartMs) / (SECONDS_PER_DAY * 1000),
    dayOfMonth: day,
  };
}

/**
 * Trials started this calendar month, extrapolated to a full month.
 *
 * The point estimate is a plain run rate. The band around it comes from the
 * count's own sampling error rather than from prior months: this business is
 * seasonal, so blending a trailing average into an in-season month would drag
 * the projection toward a different regime.
 *
 * Landings are counted by when a trial *ends*, so last month's late starters
 * are picked up and this month's are not. They split by whether the outcome is
 * already known: a trial that has ended either activated or did not, and
 * `landedConverted` counts those rather than estimating them, so the figure
 * converges on the actual as the month fills instead of drifting from it.
 *
 * Month boundaries are the business timezone's, so the month the operator is
 * living in is the month this counts.
 */
export function computeTrialProjection(
  subs: Stripe.Subscription[],
  now: Date,
  paidSubIds: Set<string>,
  excludedEmails: Set<string>
): TrialProjection {
  const { monthStart, monthEnd, daysInMonth, daysElapsed, dayOfMonth } = monthBounds(now);
  const nowSec = Math.floor(now.getTime() / 1000);

  let trialsToDate = 0;
  let landedConverted = 0;
  let landingKnownUnresolved = 0;
  for (const sub of subs) {
    if (isExcluded(sub, excludedEmails)) continue;
    const { trial_start: trialStart, trial_end: trialEnd } = sub;
    if (trialStart !== null && trialStart >= monthStart && trialStart < monthEnd) trialsToDate += 1;
    if (trialEnd === null || trialEnd < monthStart || trialEnd >= monthEnd) continue;
    if (trialEnd < nowSec) {
      if (paidSubIds.has(sub.id)) landedConverted += 1;
    } else if (sub.status !== 'canceled' && !isCancellationScheduled(sub)) {
      // A trial already canceled or set to cancel has a known outcome: it will
      // not convert. Leaving it unresolved would multiply it by the conversion rate.
      landingKnownUnresolved += 1;
    }
  }

  // Floored at one day so the opening hours of a month cannot be scaled up:
  // undivided, two signups at 00:30 on the 1st extrapolate to well over a
  // thousand. Below a day of evidence the run rate is reported as that day's
  // rather than projected out of a fraction of it, and the same denominator
  // feeds the band so `projected` stays inside it.
  const elapsedForRate = Math.max(daysElapsed, 1);
  const dailyRate = trialsToDate / elapsedForRate;
  const projected = dailyRate * daysInMonth;
  const scale = daysInMonth / elapsedForRate;
  const margin = PROJECTION_Z * Math.sqrt(trialsToDate);

  // Starts still to come that begin early enough for a 7-day trial to close
  // inside the month. Equivalent to futureStarts x (landingDays / remainingDays),
  // with the intermediates cancelled — which also removes a division by zero on
  // the last day of the month, when no days remain.
  const remainingLandingDays = Math.max(0, daysInMonth - TRIAL_DAYS - daysElapsed);

  return {
    trialsToDate,
    daysElapsed,
    dayOfMonth,
    daysInMonth,
    dailyRate,
    projected,
    low: Math.max(0, (trialsToDate - margin) * scale),
    high: trialsToDate > 0 ? (trialsToDate + margin) * scale : POISSON_ZERO_UPPER * scale,
    landedConverted,
    landingUnresolved: landingKnownUnresolved + dailyRate * remainingLandingDays,
  };
}

/**
 * Annual subscribers whose renewal is still ahead of us inside this month.
 *
 * An annual plan can only lapse at renewal, so the at-risk population is the
 * renewals actually due rather than a twelfth of the base — a twelfth reports
 * the same figure for a month holding four renewals and a month holding none.
 * Renewals earlier in the month have already resolved and are counted as
 * observed instead.
 *
 * Every item is inspected rather than only the first: `current_period_end` is
 * documented per item, so a subscription carrying more than one can renew them
 * on different dates. `computeMrr` already reads all items; this keeps the two
 * consistent.
 */
export function countAnnualRenewals(subs: Stripe.Subscription[], now: Date): number {
  const { monthEnd } = monthBounds(now);
  const nowSec = Math.floor(now.getTime() / 1000);
  let count = 0;
  for (const sub of subs) {
    const renews = sub.items.data.some(
      (item) =>
        item.price?.recurring?.interval === 'year' &&
        item.current_period_end >= nowSec &&
        item.current_period_end < monthEnd
    );
    if (renews) count += 1;
  }
  return count;
}

/**
 * Activated subscribers whose service ended inside this month.
 *
 * The counterpart to `landedConverted` on the loss side: a cancellation that has
 * already happened is counted, not estimated, so both halves of the month figure
 * rest on observation for the elapsed part and on rates only for the rest.
 */
export function countObservedChurn(
  subs: Stripe.Subscription[],
  now: Date,
  paidSubIds: Set<string>,
  excludedEmails: Set<string>
): number {
  const { monthStart, monthEnd } = monthBounds(now);
  let count = 0;
  for (const sub of subs) {
    // Only a subscription that has actually stopped counts. A pending
    // cancellation carries `canceled_at` from the moment it is requested while
    // service runs to the period end, so without this guard a cancellation
    // requested now for service ending next year lands in this month's loss.
    if (sub.status !== 'canceled') continue;
    if (!paidSubIds.has(sub.id) || isExcluded(sub, excludedEmails)) continue;
    const endedAt = getServiceEnd(sub);
    if (endedAt !== null && endedAt >= monthStart && endedAt < monthEnd) count += 1;
  }
  return count;
}

/**
 * Assemble the month's projection: what lands inside this month against what is
 * lost inside it.
 *
 * Both halves are observation-first: conversions and cancellations that
 * have already happened are counted, and the rates apply only to the part of the
 * month still outstanding. Monthly subscribers are therefore prorated across the
 * days remaining, while annual renewals still ahead take the full rate — a
 * renewal is a single dated event, not a risk spread over the month.
 *
 * `arpu` is monthly-equivalent, so an annual plan contributes its twelfth rather
 * than its sticker price. Lifetime and LTV are null when no churn was measured:
 * zero is a real rate, but `1 / 0` has no finite value and rendering it as $0
 * would show the best possible retention as a total loss.
 */
export function buildMonthProjection(input: {
  trials: TrialProjection;
  conversion: RateEstimate;
  churn: RateEstimate;
  arpu: number;
  activeMonthly: number;
  annualRenewalsAhead: number;
  observedChurn: number;
}): MonthProjection {
  const { trials, conversion, churn, arpu, activeMonthly, annualRenewalsAhead, observedChurn } = input;
  const { daysInMonth, daysElapsed } = trials;

  const grossNewSubs = trials.landedConverted + trials.landingUnresolved * conversion.rate;
  const remainingShare = (daysInMonth - daysElapsed) / daysInMonth;
  const churnedSubs = observedChurn + activeMonthly * churn.rate * remainingShare + annualRenewalsAhead * churn.rate;
  const netSubs = grossNewSubs - churnedSubs;
  const avgLifetimeMonths = churn.rate > 0 ? 1 / churn.rate : null;
  const ltv = avgLifetimeMonths === null ? null : avgLifetimeMonths * arpu;

  return {
    trials,
    conversion,
    churn,
    arpu,
    grossNewSubs,
    observedChurn,
    churnedSubs,
    annualRenewalsAhead,
    netSubs,
    netMrr: netSubs * arpu,
    avgLifetimeMonths,
    ltv,
  };
}

/**
 * A charge's balance transaction carries the fee Stripe actually took, the
 * place to look if this ever disagrees. No charge means no fee, so zero stays
 * zero rather than going negative.
 */
export function netOfStripeFee(cents: number): number {
  if (cents <= 0) return 0;
  return cents - Math.round(cents * STRIPE_FEE_PERCENT + STRIPE_FEE_FIXED_CENTS);
}

/**
 * Of the monthly renewals that came due for activated subscribers, the share a
 * paid invoice collected.
 *
 * Renewal dates are rebuilt from `billing_cycle_anchor`, which is the trial end
 * for a trial, so the first date scored is the first renewal after the
 * converting charge. A date counts only when, `RENEWAL_NOTICE_DAYS` ahead of
 * it, the subscriber had not asked to cancel and was still being served. That
 * relies on `canceled_at` holding the request time, which Stripe documents for
 * `cancel_at_period_end` but not for a cancellation set through `cancel_at`
 * alone. A plan switch resets the anchor, so the renewals before one drop out
 * of the sample.
 *
 * A subscription stops being scored at its first miss. An `unpaid` subscription
 * keeps reaching renewal dates with neither `canceled_at` nor `ended_at` set,
 * and Stripe closes those invoices without trying them, so scoring every date
 * would let one stalled account lower the rate a little more each month.
 * `paidInvoices` holds only paid invoices, so a miss means no paid renewal
 * invoice was created within `RENEWAL_MATCH_DAYS` of the date; whether Stripe
 * attempted the charge is not visible here.
 *
 * `observed` and `sample` count renewal dates, while `excluded` counts the
 * internal subscriptions left out, so the minimum sample is a number of dates.
 */
export function computeRenewalCollectionRate(
  subs: Stripe.Subscription[],
  paidInvoices: Stripe.Invoice[],
  now: Date,
  paidSubIds: Set<string>,
  excludedEmails: Set<string>
): RateEstimate {
  const renewalsBySub = new Map<string, number[]>();
  for (const invoice of paidInvoices) {
    if (invoice.billing_reason !== 'subscription_cycle' || !isActivatingPayment(invoice)) continue;
    const id = getInvoiceSubscriptionId(invoice);
    if (!id) continue;
    const created = renewalsBySub.get(id);
    if (created) created.push(invoice.created);
    else renewalsBySub.set(id, [invoice.created]);
  }

  const settled = Math.floor(now.getTime() / 1000) - RENEWAL_SETTLE_DAYS * SECONDS_PER_DAY;
  let sample = 0;
  let observed = 0;
  let excluded = 0;
  for (const sub of subs) {
    if (getInterval(sub) !== 'month' || !paidSubIds.has(sub.id)) continue;
    if (isExcluded(sub, excludedEmails)) {
      excluded += 1;
      continue;
    }
    const collectedAt = renewalsBySub.get(sub.id) ?? [];
    for (let k = 1; ; k += 1) {
      const due = addMonthsClamped(sub.billing_cycle_anchor, k);
      if (due >= settled) break;
      const noticeBy = due - RENEWAL_NOTICE_DAYS * SECONDS_PER_DAY;
      if (
        (sub.canceled_at !== null && sub.canceled_at <= noticeBy) ||
        (sub.ended_at !== null && sub.ended_at <= noticeBy)
      ) {
        break;
      }
      sample += 1;
      if (!collectedAt.some((created) => Math.abs(created - due) <= RENEWAL_MATCH_DAYS * SECONDS_PER_DAY)) break;
      observed += 1;
    }
  }
  return finalizeRate(observed, sample, excluded, FALLBACK_RENEWAL_RATE);
}

/** `anchor` moved `months` calendar months on in UTC, held to the target month's last day, as Stripe bills. */
function addMonthsClamped(anchor: number, months: number): number {
  const start = new Date(anchor * 1000);
  const year = start.getUTCFullYear();
  const month = start.getUTCMonth() + months;
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const day = Math.min(start.getUTCDate(), lastDay);
  return Date.UTC(year, month, day, start.getUTCHours(), start.getUTCMinutes(), start.getUTCSeconds()) / 1000;
}

export function computeLifetimeConversionByPlan(
  subs: Stripe.Subscription[],
  paidSubIds: Set<string>,
  now: number,
  excludedEmails: Set<string>
): Record<Plan, RateEstimate> {
  const forPlan = (plan: Plan) =>
    computeTrialConversionRate({
      subs: subs.filter((sub) => getInterval(sub) === plan),
      paidSubIds,
      now,
      windowStart: 0,
      excludedEmails,
    });
  return { month: forPlan('month'), year: forPlan('year') };
}

/**
 * The cash Stripe can be expected to collect over the next week, fortnight and
 * the rest of the month in the business timezone, after its fee.
 *
 * Every expected charge is dated and lands in each window that contains it: a
 * renewal on its item's period end, at the renewal collection rate; a trial on
 * its end, at its plan's lifetime conversion rate; and trials yet to start at
 * the pace of the last `NEW_TRIAL_PACE_DAYS`, in the part of a window long
 * enough for one to finish. Trials already set to cancel are counted at the same rate,
 * because the rate was measured over every trial, those that cancelled midway
 * included. Month Projection deliberately treats them as lost instead.
 *
 * A renewal is forecast only for a subscriber who has paid before, the
 * population the collection rate is measured on; annual renewals take the
 * monthly rate until annual history exists. A subscription left past due by a
 * declined first charge has never paid, and its trial already counts against
 * the conversion rate.
 *
 * Each part is rounded to the cent and `total` is their sum, so the breakdown
 * shown beside a figure adds up to it.
 */
export function buildCashForecast(input: {
  now: Date;
  subs: Stripe.Subscription[];
  paidSubIds: Set<string>;
  conversion: Record<Plan, RateEstimate>;
  renewalRate: RateEstimate;
  excludedEmails: Set<string>;
}): CashForecast {
  const { now, subs, paidSubIds, conversion, renewalRate, excludedEmails } = input;
  const nowSec = Math.floor(now.getTime() / 1000);
  const paceStart = nowSec - NEW_TRIAL_PACE_DAYS * SECONDS_PER_DAY;

  const renewalCharges: Charge[] = [];
  const trialCharges: Charge[] = [];
  let newTrialCentsPerDay = 0;
  for (const sub of subs) {
    if (isExcluded(sub, excludedEmails)) continue;
    const priced = pricedCentsByPeriodEnd(sub);
    if (isStillSubscribed(sub) && paidSubIds.has(sub.id)) {
      for (const [at, cents] of priced) {
        renewalCharges.push({ at, cents: netOfStripeFee(cents) * renewalRate.rate });
      }
    }
    const plan = getInterval(sub);
    if (plan === null) continue;
    const trialCents = netOfStripeFee(sumCents(priced)) * conversion[plan].rate;
    if (sub.status === 'trialing' && sub.trial_end !== null) {
      trialCharges.push({ at: sub.trial_end, cents: trialCents });
    }
    if (sub.trial_start !== null && sub.trial_start >= paceStart && sub.trial_start < nowSec) {
      newTrialCentsPerDay += trialCents / NEW_TRIAL_PACE_DAYS;
    }
  }

  const windowTo = (end: number): ForecastWindow => {
    const sumWithin = (charges: Charge[]) =>
      toDollars(charges.filter((c) => c.at >= nowSec && c.at < end).reduce((t, c) => t + c.cents, 0));
    const windowDays = (end - nowSec) / SECONDS_PER_DAY;
    const renewals = sumWithin(renewalCharges);
    const trials = sumWithin(trialCharges);
    const newTrials = windowDays > TRIAL_DAYS ? toDollars(newTrialCentsPerDay * (windowDays - TRIAL_DAYS)) : null;
    return { end, renewals, trials, newTrials, total: toDollars((renewals + trials + (newTrials ?? 0)) * 100) };
  };

  return {
    renewalRate,
    conversion,
    windows: {
      week: windowTo(nowSec + 7 * SECONDS_PER_DAY),
      fortnight: windowTo(nowSec + 14 * SECONDS_PER_DAY),
      month: windowTo(monthBounds(now).monthEnd),
    },
  };
}

type Charge = { at: number; cents: number };

/** What one subscription item bills per period, in cents, at list price; null without a recurring unit price. */
export function pricedItemCents(item: Stripe.SubscriptionItem): number | null {
  const { recurring, unit_amount: unitAmount } = item.price;
  if (!recurring || unitAmount == null) return null;
  return unitAmount * (item.quantity ?? 1);
}

/** A subscription's priced items, grouped into the one charge Stripe bills at each period end. */
function pricedCentsByPeriodEnd(sub: Stripe.Subscription): Map<number, number> {
  const byPeriodEnd = new Map<number, number>();
  for (const item of sub.items.data) {
    const cents = pricedItemCents(item);
    if (cents === null) continue;
    byPeriodEnd.set(item.current_period_end, (byPeriodEnd.get(item.current_period_end) ?? 0) + cents);
  }
  return byPeriodEnd;
}

function sumCents(byPeriodEnd: Map<number, number>): number {
  return [...byPeriodEnd.values()].reduce((total, cents) => total + cents, 0);
}

function toDollars(cents: number): number {
  return Math.round(cents) / 100;
}
