import 'server-only';
import type Stripe from 'stripe';
import { getCustomerEmail, MIN_COHORT_SAMPLE, SECONDS_PER_DAY, TRIAL_DAYS } from './constants';

/** Window over which a converted subscriber is checked for surviving their first paid month. */
const CHURN_WINDOW_DAYS = 30;

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

export type TrialProjection = {
  trialsToDate: number;
  daysElapsed: number;
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
  grossNewMrr: number;
  observedChurn: number;
  churnedSubs: number;
  annualRenewalsAhead: number;
  lostMrr: number;
  netSubs: number;
  netMrr: number;
  cohortSubs: number;
  cohortMrr: number;
  avgLifetimeMonths: number | null;
  ltv: number | null;
  cohortValue: number | null;
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
    const paidCash = invoice.amount_paid > 0;
    const discountedActivation =
      invoice.total === 0 && invoice.discounts.length > 0 && invoice.billing_reason !== 'subscription_create';
    if (!paidCash && !discountedActivation) continue;
    const id = getInvoiceSubscriptionId(invoice);
    if (id) out.add(id);
  }
  return out;
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
  let sample = 0;
  let observed = 0;
  let excluded = 0;
  for (const sub of subs) {
    const trialEnd = sub.trial_end;
    if (trialEnd === null || trialEnd >= now || trialEnd < windowStart) continue;
    if (isExcluded(sub, excludedEmails)) {
      excluded += 1;
      continue;
    }
    sample += 1;
    if (paidSubIds.has(sub.id)) observed += 1;
  }
  return finalizeRate(observed, sample, excluded, FALLBACK_CONVERSION_RATE);
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

function monthBounds(now: Date): { monthStart: number; monthEnd: number; daysInMonth: number; daysElapsed: number } {
  const year = now.getUTCFullYear();
  const month = now.getUTCMonth();
  return {
    monthStart: Date.UTC(year, month, 1) / 1000,
    monthEnd: Date.UTC(year, month + 1, 1) / 1000,
    daysInMonth: new Date(Date.UTC(year, month + 1, 0)).getUTCDate(),
    daysElapsed: now.getUTCDate(),
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
 * Month boundaries are UTC, matching the Stripe timestamps counted.
 */
export function computeTrialProjection(
  subs: Stripe.Subscription[],
  now: Date,
  paidSubIds: Set<string>,
  excludedEmails: Set<string>
): TrialProjection {
  const { monthStart, monthEnd, daysInMonth, daysElapsed } = monthBounds(now);
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
    } else if (!sub.cancel_at_period_end) {
      // A trial already set to cancel has a known outcome: it will not convert.
      // Leaving it unresolved would multiply it by the conversion rate.
      landingKnownUnresolved += 1;
    }
  }

  const dailyRate = trialsToDate / daysElapsed;
  const projected = dailyRate * daysInMonth;
  const scale = daysInMonth / daysElapsed;
  const margin = PROJECTION_Z * Math.sqrt(trialsToDate);

  // Starts still to come that begin early enough for a 7-day trial to close
  // inside the month. Equivalent to futureStarts x (landingDays / remainingDays),
  // with the intermediates cancelled — which also removes a division by zero on
  // the last day of the month, when no days remain.
  const remainingLandingDays = Math.max(0, daysInMonth - TRIAL_DAYS - daysElapsed);

  return {
    trialsToDate,
    daysElapsed,
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
 * Assemble the month's projection.
 *
 * Two scopes are reported and must not be mixed. The month figures pair what
 * lands inside this month against what is lost inside it; the cohort figures
 * value every trial this month starts, whenever its charge lands.
 *
 * Both month halves are observation-first: conversions and cancellations that
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
  const cohortSubs = trials.projected * conversion.rate;
  const avgLifetimeMonths = churn.rate > 0 ? 1 / churn.rate : null;
  const ltv = avgLifetimeMonths === null ? null : avgLifetimeMonths * arpu;

  return {
    trials,
    conversion,
    churn,
    arpu,
    grossNewSubs,
    grossNewMrr: grossNewSubs * arpu,
    observedChurn,
    churnedSubs,
    annualRenewalsAhead,
    lostMrr: churnedSubs * arpu,
    netSubs,
    netMrr: netSubs * arpu,
    cohortSubs,
    cohortMrr: cohortSubs * arpu,
    avgLifetimeMonths,
    ltv,
    cohortValue: ltv === null ? null : cohortSubs * ltv,
  };
}

export type UnpaidInvoiceEntry = {
  id: string;
  email: string;
  amountRemaining: number;
  attemptCount: number;
  created: string;
  retryScheduled: boolean;
};

/**
 * Subscription invoices Stripe finalized, attempted, and did not collect.
 *
 * `amount_remaining` rather than `amount_due`, since a part-paid invoice still
 * carries its full original `amount_due` and this list is ordered by what is
 * actually recoverable.
 *
 * `retryScheduled` reports only whether Stripe has another attempt on the
 * calendar. It is not a promise the attempt will succeed or even run: after a
 * non-retryable decline Stripe keeps scheduling retries that execute only once a
 * new payment method arrives. So a scheduled row can still be unrecoverable, and
 * the count of unscheduled rows is a floor on the work outstanding, not the whole
 * of it.
 *
 * Invoices with no subscription behind them are excluded: a manual or one-off
 * invoice going unpaid is not a failed subscriber charge. What remains still
 * mixes first-charge failures with later renewal failures, which is why the
 * dashboard names these unpaid invoices rather than failed conversions.
 */
export function buildUnpaidInvoices(invoices: Stripe.Invoice[]): {
  list: UnpaidInvoiceEntry[];
  total: number;
  outstanding: number;
  noRetryScheduled: number;
} {
  const list: UnpaidInvoiceEntry[] = [];
  for (const invoice of invoices) {
    if (!invoice.attempted || invoice.amount_remaining <= 0) continue;
    if (!getInvoiceSubscriptionId(invoice)) continue;
    list.push({
      id: invoice.id,
      email: invoice.customer_email ?? '(no email)',
      amountRemaining: invoice.amount_remaining / 100,
      attemptCount: invoice.attempt_count,
      created: new Date(invoice.created * 1000).toISOString(),
      retryScheduled: invoice.next_payment_attempt !== null,
    });
  }
  list.sort((a, b) => b.amountRemaining - a.amountRemaining || a.created.localeCompare(b.created));
  return {
    list,
    total: list.length,
    outstanding: Math.round(list.reduce((sum, entry) => sum + entry.amountRemaining, 0) * 100) / 100,
    noRetryScheduled: list.filter((entry) => !entry.retryScheduled).length,
  };
}

/**
 * How a rate should be described beside the number it produced.
 *
 * Lives here rather than in the page because it is the one place the dashboard
 * distinguishes a measurement from a historical fallback, and that claim is a
 * single boolean away from being wrong.
 */
export function describeRate(estimate: RateEstimate): string {
  const percent = `${(estimate.rate * 100).toFixed(1)}%`;
  if (estimate.isFallback) {
    return `${percent} (historical fallback — only ${estimate.sample} in cohort)`;
  }
  return `${percent} from ${estimate.observed} of ${estimate.sample}`;
}
