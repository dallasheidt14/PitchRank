import 'server-only';
import type Stripe from 'stripe';
import { stripe } from '@/lib/stripe/server';

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

export type SubscriptionMetrics = {
  mrr: number;
  activePaid: {
    total: number;
    monthly: number;
    annual: number;
  };
  trials: {
    total: number;
    endingIn3Days: number;
    endingIn7Days: number;
    list: TrialPipelineEntry[];
  };
  pastDue: {
    total: number;
    list: PastDueEntry[];
  };
  conversion: {
    window: '30d';
    sample: number;
    converted: number;
    percent: number | null;
  };
  generatedAt: string;
  errors: string[];
};

const SECONDS_PER_DAY = 86_400;
const COHORT_LOOKBACK_DAYS = 60;
const COHORT_TRIAL_END_THRESHOLD_DAYS = 30;
const MIN_COHORT_SAMPLE = 5;

function getInterval(sub: Stripe.Subscription): 'month' | 'year' | null {
  const recurring = sub.items.data[0]?.price?.recurring;
  if (recurring?.interval === 'month') return 'month';
  if (recurring?.interval === 'year') return 'year';
  return null;
}

function getCustomerEmail(sub: Stripe.Subscription): string {
  const customer = sub.customer;
  if (typeof customer === 'string') return customer;
  if ('deleted' in customer && customer.deleted) return '(deleted customer)';
  return customer.email ?? '(no email)';
}

/**
 * Sum of monthly-equivalent revenue across a list of subscriptions.
 * Returns whole dollars (Stripe amounts are cents).
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
  return Math.round(cents / 100);
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

export function buildTrialPipeline(
  subs: Stripe.Subscription[],
  now: number
): { list: TrialPipelineEntry[]; endingIn3Days: number; endingIn7Days: number } {
  const list: TrialPipelineEntry[] = [];
  for (const sub of subs) {
    if (!sub.trial_end) continue;
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
  return { list, endingIn3Days, endingIn7Days };
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
 * 30-day rolling conversion: of trials whose `trial_start` was 31–60 days ago
 * AND whose `trial_end` has passed, what % are now `active`?
 *
 * Returns null percent when sample < MIN_COHORT_SAMPLE so the UI can show
 * "not enough data yet".
 */
export function computeConversion(
  subs: Stripe.Subscription[],
  now: number
): { window: '30d'; sample: number; converted: number; percent: number | null } {
  const lookbackStart = now - COHORT_LOOKBACK_DAYS * SECONDS_PER_DAY;
  const trialEndCutoff = now - COHORT_TRIAL_END_THRESHOLD_DAYS * SECONDS_PER_DAY;

  let sample = 0;
  let converted = 0;
  for (const sub of subs) {
    if (!sub.trial_start || !sub.trial_end) continue;
    if (sub.trial_start < lookbackStart) continue;
    if (sub.trial_start >= trialEndCutoff) continue;
    if (sub.trial_end >= now) continue;
    sample += 1;
    if (sub.status === 'active') converted += 1;
  }

  const percent = sample >= MIN_COHORT_SAMPLE ? Math.round((converted / sample) * 100) : null;
  return { window: '30d', sample, converted, percent };
}

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
): Promise<Stripe.Subscription[]> {
  try {
    return await listAll(params);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    errors.push(`${label}: ${msg}`);
    return [];
  }
}

export async function getSubscriptionMetrics(): Promise<SubscriptionMetrics> {
  const errors: string[] = [];
  const nowSec = Math.floor(Date.now() / 1000);

  const [active, trialing, pastDue, cohort] = await Promise.all([
    safeList({ status: 'active' }, 'active subscriptions', errors),
    safeList({ status: 'trialing' }, 'trialing subscriptions', errors),
    safeList({ status: 'past_due' }, 'past_due subscriptions', errors),
    safeList(
      { status: 'all', created: { gte: nowSec - COHORT_LOOKBACK_DAYS * SECONDS_PER_DAY } },
      'conversion cohort',
      errors
    ),
  ]);

  const mrr = computeMrr(active);
  const activePaid = bucketActivePaid(active);
  const trialBuckets = buildTrialPipeline(trialing, nowSec);
  const pastDueOut = buildPastDue(pastDue);
  const conversion = computeConversion(cohort, nowSec);

  return {
    mrr,
    activePaid,
    trials: {
      total: trialing.length,
      endingIn3Days: trialBuckets.endingIn3Days,
      endingIn7Days: trialBuckets.endingIn7Days,
      list: trialBuckets.list,
    },
    pastDue: pastDueOut,
    conversion,
    generatedAt: new Date().toISOString(),
    errors,
  };
}
