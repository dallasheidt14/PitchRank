import 'server-only';
import type Stripe from 'stripe';
import { stripe } from '@/lib/stripe/server';
import { createServiceSupabase } from '@/lib/supabase/service';
import {
  buildMonthProjection,
  buildUnpaidInvoices,
  collectPaidSubscriptionIds,
  computePaidChurnRate,
  computeTrialConversionRate,
  computeTrialProjection,
  countAnnualRenewals,
  countObservedChurn,
  type CohortWindow,
  type MonthProjection,
  type RateEstimate,
  type UnpaidInvoiceEntry,
} from './month-projection';
import { getCustomerEmail, MIN_COHORT_SAMPLE, SECONDS_PER_DAY, TRIAL_DAYS } from './constants';

export type TrialPipelineEntry = {
  id: string;
  email: string;
  trialEnd: string;
  daysRemaining: number;
  interval: 'month' | 'year';
};

export type PastDueEntry = {
  id: string;
  email: string;
  interval: 'month' | 'year';
};

export type ReportCardLead = {
  id: string;
  email: string;
  teamId: string;
  teamName: string;
  role: string | null;
  createdAt: string; // ISO
};

export type ReportCardMetrics = {
  totalRequests: number;
  uniqueEmails: number;
  last7Days: number;
  last30Days: number;
  conversion: {
    leads: number;
    converted: number;
    percent: number | null;
    excluded: number;
  };
  trialConversion: {
    leads: number;
    trialed: number;
    percent: number | null;
    excluded: number;
  };
  recentLeads: ReportCardLead[];
};

export type SubscriptionMetrics = {
  mrr: number; // dollars with cents preserved (e.g. 61.25)
  activePaid: {
    total: number;
    monthly: number;
    annual: number;
  };
  trials: {
    total: number; // active trials only — excludes those marked cancel_at_period_end
    canceledPending: number; // trialing + cancel_at_period_end (won't renew)
    endingIn3Days: number;
    endingIn7Days: number;
    list: TrialPipelineEntry[];
  };
  pastDue: {
    total: number;
    list: PastDueEntry[];
  };
  conversion: {
    windowDays: number; // size of the lookback window
    sample: number;
    converted: number;
    percent: number | null;
    excluded: number; // test/internal users filtered from sample
  };
  reportCard: ReportCardMetrics;
  monthProjection: { available: boolean } & MonthProjection;
  unpaidInvoices: {
    /** False when the open-invoice fetch failed, so an empty list is not evidence of none. */
    available: boolean;
    total: number;
    outstanding: number;
    noRetryScheduled: number;
    list: UnpaidInvoiceEntry[];
  };
  generatedAt: string;
  errors: string[];
};

/**
 * How far back conversion and churn are measured, as a window on when a trial
 * ENDED. Wide because both rates need subscribers whose first paid month has
 * already finished, and that cohort is far smaller than the subscriber count
 * suggests; the sizing evidence is in
 * `.turbo/reports/2026-09-04-stripe-month-projection-baseline.md`.
 */
const COHORT_LOOKBACK_DAYS = 180;

/**
 * Subscriptions are fetched by creation date but the rates filter on trial end,
 * so the fetch reaches back one trial length further. Without the extra week the
 * oldest trials inside the window belong to subscriptions created before it, and
 * the card reports a wider window than it measured.
 */
const COHORT_FETCH_DAYS = COHORT_LOOKBACK_DAYS + TRIAL_DAYS;

/** Monthly list price, used for ARPU only when no converted sub is available to measure. */
const MONTHLY_LIST_PRICE = 6.99;

/**
 * Internal/test users whose subscriptions skew dashboard math (especially
 * conversion %). Compared case-insensitively. Add via env var
 * `ADMIN_DASHBOARD_EXCLUDED_EMAILS` (comma-separated) to extend at runtime
 * without a deploy.
 */
const HARDCODED_EXCLUDED_EMAILS = new Set([
  'cartermheidt@gmail.com',
  'brooksheidt@gmail.com',
  'dallasheidt@gmail.com',
  'dallas@rightsideuplending.com',
]);

function getExcludedEmails(): Set<string> {
  const fromEnv = (process.env.ADMIN_DASHBOARD_EXCLUDED_EMAILS ?? '')
    .split(',')
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
  return new Set([...HARDCODED_EXCLUDED_EMAILS, ...fromEnv]);
}

/**
 * Normalize and deduplicate a list of email strings. Lowercased + trimmed.
 * Non-string, empty, and whitespace-only values are dropped.
 */
export function dedupeEmails(emails: Array<string | null | undefined>): Set<string> {
  const out = new Set<string>();
  for (const raw of emails) {
    if (typeof raw !== 'string') continue;
    const normalized = raw.trim().toLowerCase();
    if (normalized.length === 0) continue;
    out.add(normalized);
  }
  return out;
}

/**
 * Lead → paid conversion. Returns the share of unique lead emails that are
 * currently paying Stripe customers (active or past_due — past_due means they
 * paid at least once and a renewal failed).
 *
 * Excluded (test/internal) emails are removed from both numerator and
 * denominator and reported separately. Percent is null when leads <
 * MIN_COHORT_SAMPLE so the UI can show "not enough data yet".
 *
 * Reuses the active + past_due lists already fetched by getSubscriptionMetrics
 * — no extra Stripe calls.
 */
export function computeLeadConversion(
  leadEmails: Set<string>,
  activeSubs: Stripe.Subscription[],
  pastDueSubs: Stripe.Subscription[],
  excludedEmails: Set<string> = getExcludedEmails()
): { leads: number; converted: number; percent: number | null; excluded: number } {
  // Build set of paying emails (lowercased).
  const paying = new Set<string>();
  for (const sub of [...activeSubs, ...pastDueSubs]) {
    const email = getCustomerEmail(sub).toLowerCase();
    paying.add(email);
  }

  let leads = 0;
  let converted = 0;
  let excluded = 0;
  for (const raw of leadEmails) {
    const email = raw.toLowerCase();
    if (excludedEmails.has(email)) {
      excluded += 1;
      continue;
    }
    leads += 1;
    if (paying.has(email)) converted += 1;
  }

  const percent = leads >= MIN_COHORT_SAMPLE ? Math.round((converted / leads) * 100) : null;
  return { leads, converted, percent, excluded };
}

/**
 * Lead → trial conversion. Returns the share of unique lead emails that have
 * EVER started a trial — currently trialing, already converted to paid, or
 * cancelled. A subscription counts as "started a trial" when it has a
 * `trial_start` set, regardless of its current status, so a lead who trialed
 * and later cancelled still counts.
 *
 * Excluded (test/internal) emails are removed from both numerator and
 * denominator and reported separately. Percent is null when leads <
 * MIN_COHORT_SAMPLE so the UI can show "not enough data yet".
 *
 * The caller passes the unbounded status lists that cover every bucket a
 * trialer can land in — active + trialing + past_due + canceled — so the
 * "trialed" set is date-complete: a lead who trialed and cancelled long ago is
 * still counted, with no time-window blind spot.
 */
export function computeLeadToTrial(
  leadEmails: Set<string>,
  subs: Stripe.Subscription[],
  excludedEmails: Set<string> = getExcludedEmails()
): { leads: number; trialed: number; percent: number | null; excluded: number } {
  // Build set of emails that ever started a trial (lowercased).
  const trialedEmails = new Set<string>();
  for (const sub of subs) {
    if (sub.trial_start == null) continue;
    trialedEmails.add(getCustomerEmail(sub).toLowerCase());
  }

  let leads = 0;
  let trialed = 0;
  let excluded = 0;
  for (const raw of leadEmails) {
    const email = raw.toLowerCase();
    if (excludedEmails.has(email)) {
      excluded += 1;
      continue;
    }
    leads += 1;
    if (trialedEmails.has(email)) trialed += 1;
  }

  const percent = leads >= MIN_COHORT_SAMPLE ? Math.round((trialed / leads) * 100) : null;
  return { leads, trialed, percent, excluded };
}

function getInterval(sub: Stripe.Subscription): 'month' | 'year' | null {
  const recurring = sub.items.data[0]?.price?.recurring;
  if (recurring?.interval === 'month') return 'month';
  if (recurring?.interval === 'year') return 'year';
  return null;
}

/**
 * Sum of monthly-equivalent revenue across a list of subscriptions.
 * Returns dollars with cents preserved (e.g. 61.25), rounded to the nearest cent.
 */
export function computeMrr(subs: Stripe.Subscription[]): number {
  let cents = 0;
  for (const sub of subs) {
    for (const item of sub.items.data) {
      const price = item.price;
      const recurring = price.recurring;
      if (!recurring || price.unit_amount == null) continue;
      const quantity = item.quantity ?? 1;
      const itemMonthly = (price.unit_amount * quantity) / (recurring.interval === 'year' ? 12 : 1);
      cents += itemMonthly;
    }
  }
  return Math.round(cents) / 100;
}

export function bucketActivePaid(subs: Stripe.Subscription[]): { total: number; monthly: number; annual: number } {
  let monthly = 0;
  let annual = 0;
  for (const sub of subs) {
    const interval = getInterval(sub);
    if (interval === 'month') monthly += 1;
    else if (interval === 'year') annual += 1;
  }
  return { total: monthly + annual, monthly, annual };
}

/**
 * Build the trial pipeline view. Excludes trials the user has already
 * canceled (cancel_at_period_end=true on a trialing sub) — those won't
 * convert and shouldn't show up as actionable in the dashboard.
 *
 * Returns both the actionable count (`activeTotal`) and the canceled-pending
 * count for transparency.
 */
export function buildTrialPipeline(
  subs: Stripe.Subscription[],
  now: number
): {
  list: TrialPipelineEntry[];
  activeTotal: number;
  canceledPending: number;
  endingIn3Days: number;
  endingIn7Days: number;
} {
  const list: TrialPipelineEntry[] = [];
  let canceledPending = 0;
  for (const sub of subs) {
    if (!sub.trial_end) continue;
    if (sub.cancel_at_period_end) {
      canceledPending += 1;
      continue;
    }
    const interval = getInterval(sub);
    if (!interval) continue;
    const daysRemaining = Math.ceil((sub.trial_end - now) / SECONDS_PER_DAY);
    list.push({
      id: sub.id,
      email: getCustomerEmail(sub),
      trialEnd: new Date(sub.trial_end * 1000).toISOString(),
      daysRemaining,
      interval,
    });
  }
  list.sort((a, b) => new Date(a.trialEnd).getTime() - new Date(b.trialEnd).getTime());
  const endingIn3Days = list.filter((e) => e.daysRemaining <= 3).length;
  const endingIn7Days = list.filter((e) => e.daysRemaining <= 7).length;
  return { list, activeTotal: list.length, canceledPending, endingIn3Days, endingIn7Days };
}

export function buildPastDue(subs: Stripe.Subscription[]): { list: PastDueEntry[]; total: number } {
  const list: PastDueEntry[] = [];
  for (const sub of subs) {
    const interval = getInterval(sub);
    if (!interval) continue;
    list.push({
      id: sub.id,
      email: getCustomerEmail(sub),
      interval,
    });
  }
  return { list, total: list.length };
}

/**
 * Trial conversion for the dashboard card: of the trials that ended inside the
 * lookback window, what share produced a real activation?
 *
 * A presentation of `computeTrialConversionRate` — the same measurement the
 * projection reads, shaped for this card. Measuring it twice is how the two
 * surfaces drifted apart, since only one of them applied the internal-email
 * exclusion.
 *
 * Returns a null percent below MIN_COHORT_SAMPLE so the UI can say "not enough
 * data yet" rather than print a percentage drawn from three subscribers.
 */
export function computeConversion(
  estimate: RateEstimate,
  windowDays: number
): { windowDays: number; sample: number; converted: number; percent: number | null; excluded: number } {
  const percent = estimate.sample >= MIN_COHORT_SAMPLE ? Math.round(estimate.rate * 100) : null;
  return {
    windowDays,
    sample: estimate.sample,
    converted: estimate.observed,
    percent,
    excluded: estimate.excluded,
  };
}

/**
 * A list Stripe returned, and whether it was actually returned.
 *
 * Every one of these lists has an empty state that is a valid answer, so a
 * failed fetch is indistinguishable from a genuine zero once the array is
 * handed on alone — and a consumer then reports a confident zero where it should
 * report "unknown". Carrying `ok` beside the items makes that distinction the
 * caller's to lose rather than the fetch's to hide.
 */
type Fetched<T> = { items: T[]; ok: boolean };

async function listAll(params: Stripe.SubscriptionListParams): Promise<Stripe.Subscription[]> {
  const out: Stripe.Subscription[] = [];
  for await (const sub of stripe.subscriptions.list({ ...params, limit: 100, expand: ['data.customer'] })) {
    out.push(sub);
  }
  return out;
}

async function safeList(
  params: Stripe.SubscriptionListParams,
  label: string,
  errors: string[]
): Promise<Fetched<Stripe.Subscription>> {
  try {
    return { items: await listAll(params), ok: true };
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    errors.push(`${label}: ${msg}`);
    return { items: [], ok: false };
  }
}

async function safeListInvoices(
  params: Stripe.InvoiceListParams,
  label: string,
  errors: string[]
): Promise<Fetched<Stripe.Invoice>> {
  const items: Stripe.Invoice[] = [];
  try {
    for await (const invoice of stripe.invoices.list({ ...params, limit: 100 })) {
      items.push(invoice);
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    errors.push(`${label}: ${msg}`);
    return { items: [], ok: false };
  }
  return { items, ok: true };
}

const REPORT_CARD_PAGE_CAP = 10_000;
const REPORT_CARD_RECENT_LIMIT = 15;

function formatSupabaseError(e: unknown): string {
  if (e && typeof e === 'object' && 'message' in e && typeof (e as { message: unknown }).message === 'string') {
    return (e as { message: string }).message;
  }
  return String(e);
}

type ReportCardFetchResult = {
  totalRequests: number;
  uniqueLeadEmails: Set<string>;
  last7Days: number;
  last30Days: number;
  recentLeads: ReportCardLead[];
};

/**
 * Fetch raw report-card lead data from Supabase. Each sub-query is wrapped
 * individually so a single failure degrades that metric (returns 0 / empty)
 * rather than blowing up the dashboard. Failure messages land in `errors`.
 */
async function fetchReportCardMetrics(errors: string[]): Promise<ReportCardFetchResult> {
  let supabase: ReturnType<typeof createServiceSupabase>;
  try {
    supabase = createServiceSupabase();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    errors.push(`report card client: ${msg}`);
    return {
      totalRequests: 0,
      uniqueLeadEmails: new Set(),
      last7Days: 0,
      last30Days: 0,
      recentLeads: [],
    };
  }

  const now = Date.now();
  const sevenDaysAgo = new Date(now - 7 * 86_400_000).toISOString();
  const thirtyDaysAgo = new Date(now - 30 * 86_400_000).toISOString();

  const [totalRes, emailsRes, last7Res, last30Res, recentRes] = await Promise.all([
    supabase
      .from('report_card_leads')
      .select('id', { count: 'exact', head: true })
      .then(
        (r) => r,
        (e) => ({ error: e, count: null }) as { error: unknown; count: null }
      ),
    supabase
      .from('report_card_leads')
      .select('email')
      .limit(REPORT_CARD_PAGE_CAP)
      .then(
        (r) => r,
        (e) => ({ error: e, data: null }) as { error: unknown; data: null }
      ),
    supabase
      .from('report_card_leads')
      .select('id', { count: 'exact', head: true })
      .gte('created_at', sevenDaysAgo)
      .then(
        (r) => r,
        (e) => ({ error: e, count: null }) as { error: unknown; count: null }
      ),
    supabase
      .from('report_card_leads')
      .select('id', { count: 'exact', head: true })
      .gte('created_at', thirtyDaysAgo)
      .then(
        (r) => r,
        (e) => ({ error: e, count: null }) as { error: unknown; count: null }
      ),
    supabase
      .from('report_card_leads')
      .select('id, email, team_id, team_name, role, created_at')
      .order('created_at', { ascending: false })
      .limit(REPORT_CARD_RECENT_LIMIT)
      .then(
        (r) => r,
        (e) => ({ error: e, data: null }) as { error: unknown; data: null }
      ),
  ]);

  let totalRequests = 0;
  if (totalRes.error) {
    errors.push(`report card total: ${formatSupabaseError(totalRes.error)}`);
  } else {
    totalRequests = totalRes.count ?? 0;
  }

  let uniqueLeadEmails = new Set<string>();
  if (emailsRes.error) {
    errors.push(`report card unique emails: ${formatSupabaseError(emailsRes.error)}`);
  } else {
    const rows = (emailsRes.data ?? []) as Array<{ email: string | null }>;
    uniqueLeadEmails = dedupeEmails(rows.map((r) => r.email));
    if (rows.length >= REPORT_CARD_PAGE_CAP) {
      errors.push(`report card unique emails: hit ${REPORT_CARD_PAGE_CAP}-row cap; count is a lower bound`);
    }
  }

  let last7Days = 0;
  if (last7Res.error) {
    errors.push(`report card last 7d: ${formatSupabaseError(last7Res.error)}`);
  } else {
    last7Days = last7Res.count ?? 0;
  }

  let last30Days = 0;
  if (last30Res.error) {
    errors.push(`report card last 30d: ${formatSupabaseError(last30Res.error)}`);
  } else {
    last30Days = last30Res.count ?? 0;
  }

  let recentLeads: ReportCardLead[] = [];
  if (recentRes.error) {
    errors.push(`report card recent leads: ${formatSupabaseError(recentRes.error)}`);
  } else {
    const rows = (recentRes.data ?? []) as Array<{
      id: string;
      email: string;
      team_id: string;
      team_name: string;
      role: string | null;
      created_at: string;
    }>;
    recentLeads = rows.map((r) => ({
      id: r.id,
      email: r.email,
      teamId: r.team_id,
      teamName: r.team_name,
      role: r.role,
      createdAt: r.created_at,
    }));
  }

  return { totalRequests, uniqueLeadEmails, last7Days, last30Days, recentLeads };
}

export async function getSubscriptionMetrics(): Promise<SubscriptionMetrics> {
  const errors: string[] = [];
  const nowSec = Math.floor(Date.now() / 1000);

  const [active, trialing, pastDue, canceled, cohort, paidInvoices, openInvoices, reportCardData] = await Promise.all([
    safeList({ status: 'active' }, 'active subscriptions', errors),
    safeList({ status: 'trialing' }, 'trialing subscriptions', errors),
    safeList({ status: 'past_due' }, 'past_due subscriptions', errors),
    safeList({ status: 'canceled' }, 'canceled subscriptions', errors),
    safeList(
      { status: 'all', created: { gte: nowSec - COHORT_FETCH_DAYS * SECONDS_PER_DAY } },
      'conversion cohort',
      errors
    ),
    safeListInvoices(
      { status: 'paid', created: { gte: nowSec - COHORT_FETCH_DAYS * SECONDS_PER_DAY } },
      'paid invoices',
      errors
    ),
    safeListInvoices({ status: 'open' }, 'open invoices', errors),
    fetchReportCardMetrics(errors),
  ]);

  const mrr = computeMrr(active.items);
  const activePaid = bucketActivePaid(active.items);
  const trialBuckets = buildTrialPipeline(trialing.items, nowSec);
  const pastDueOut = buildPastDue(pastDue.items);
  const paidSubIds = collectPaidSubscriptionIds(paidInvoices.items);
  const excludedEmails = getExcludedEmails();
  const now = new Date(nowSec * 1000);

  // Rates and the projection both need the cohort AND the evidence of payment.
  // Withhold the cohort when either fetch failed, so they report their fallback
  // or an unavailable projection rather than a confident zero.
  const measurable = cohort.ok && paidInvoices.ok;
  const cohortWindow: CohortWindow = {
    subs: measurable ? cohort.items : [],
    paidSubIds,
    now: nowSec,
    windowStart: nowSec - COHORT_LOOKBACK_DAYS * SECONDS_PER_DAY,
    excludedEmails,
  };
  const conversionEstimate = computeTrialConversionRate(cohortWindow);
  const churnEstimate = computePaidChurnRate(cohortWindow);
  const conversion = computeConversion(conversionEstimate, COHORT_LOOKBACK_DAYS);

  const paidCohort = cohortWindow.subs.filter(
    (sub) => paidSubIds.has(sub.id) && !excludedEmails.has(getCustomerEmail(sub).toLowerCase())
  );
  const arpu = paidCohort.length > 0 ? computeMrr(paidCohort) / paidCohort.length : MONTHLY_LIST_PRICE;
  const monthProjection = buildMonthProjection({
    trials: computeTrialProjection(cohortWindow.subs, now, paidSubIds, excludedEmails),
    conversion: conversionEstimate,
    churn: churnEstimate,
    arpu,
    activeMonthly: activePaid.monthly,
    annualRenewalsAhead: countAnnualRenewals(active.items, now),
    // The unbounded cancelled list, not the acquisition cohort: an established
    // subscriber whose service ends this month was created before the cohort
    // window and would otherwise be counted nowhere, since they are absent from
    // the active base the projected half is charged against.
    observedChurn: measurable ? countObservedChurn(canceled.items, now, paidSubIds, excludedEmails) : 0,
  });
  const unpaid = buildUnpaidInvoices(openInvoices.items);
  const leadConversion = computeLeadConversion(reportCardData.uniqueLeadEmails, active.items, pastDue.items);
  // Union the unbounded status lists so "ever trialed" is date-complete:
  // currently-trialing, trialed-then-paid (active + past_due), and
  // trialed-then-cancelled. Set dedup makes the overlap harmless.
  const leadToTrial = computeLeadToTrial(reportCardData.uniqueLeadEmails, [
    ...active.items,
    ...trialing.items,
    ...pastDue.items,
    ...canceled.items,
  ]);

  return {
    mrr,
    activePaid,
    trials: {
      total: trialBuckets.activeTotal,
      canceledPending: trialBuckets.canceledPending,
      endingIn3Days: trialBuckets.endingIn3Days,
      endingIn7Days: trialBuckets.endingIn7Days,
      list: trialBuckets.list,
    },
    pastDue: pastDueOut,
    conversion,
    reportCard: {
      totalRequests: reportCardData.totalRequests,
      uniqueEmails: reportCardData.uniqueLeadEmails.size,
      last7Days: reportCardData.last7Days,
      last30Days: reportCardData.last30Days,
      conversion: leadConversion,
      trialConversion: leadToTrial,
      recentLeads: reportCardData.recentLeads,
    },
    monthProjection: { available: measurable, ...monthProjection },
    unpaidInvoices: { available: openInvoices.ok, ...unpaid },
    generatedAt: new Date().toISOString(),
    errors,
  };
}
