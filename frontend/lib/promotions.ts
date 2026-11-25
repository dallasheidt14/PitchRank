/**
 * Site-wide sales, one entry each. Every surface (banner, upgrade card, checkout, webhook events)
 * reads its copy, prices, campaign and event prefix from the entry, so the next sale is a new entry
 * rather than new code. Pure and directive-free: client and server code both import it.
 *
 * Windows are UTC instants, so a countdown reads the same in every time zone. Only the server
 * decides whether a sale is live (`lib/promotions.server.ts`); the browser asks it for the time.
 */

import { hasAdminPlan, hasPremiumPlan } from './plan';

export type PromotionState = 'upcoming' | 'live' | 'ended';

/** A sale's funnel: the browser sends the view, click and checkout-start steps; the Stripe webhook sends the rest. */
export type PromotionEventStep =
  | 'banner_view'
  | 'banner_click'
  | 'offer_view'
  | 'checkout_started'
  | 'purchase_completed'
  | 'checkout_expired';

export interface Promotion {
  id: string;
  /** Inclusive start, ISO UTC. */
  startsAt: string;
  /** Exclusive end, ISO UTC. */
  endsAt: string;
  planInterval: 'year';
  /** The `campaign` query value campaign links carry. */
  campaign: string;
  /** GA4 event names are `<analyticsPrefix>_<step>`. */
  analyticsPrefix: string;
  display: {
    listPrice: string;
    firstYearPrice: string;
    monthlyPrice: string;
    percentOff: string;
    /** What the first invoice charges, for analytics. */
    amountCents: number;
  };
  copy: {
    bannerDesktop: string;
    bannerMobile: string;
    cardLabel: string;
    cta: string;
    endedNotice: string;
    upgradeHeaderLine: string;
  };
}

export const PROMOTIONS: readonly Promotion[] = [
  {
    id: 'black-friday-2026',
    // Wed 2026-11-25 00:00 through Mon 2026-11-30 23:59:59, America/Phoenix (UTC-7 all year).
    startsAt: '2026-11-25T07:00:00Z',
    endsAt: '2026-12-01T07:00:00Z',
    planInterval: 'year',
    campaign: 'black-friday-2026',
    analyticsPrefix: 'black_friday',
    display: {
      listPrice: '$69.99',
      firstYearPrice: '$47.88',
      monthlyPrice: '$3.99',
      percentOff: '32%',
      amountCents: 4788,
    },
    copy: {
      bannerDesktop: 'BLACK FRIDAY: Get a full year of PitchRank Premium for just $3.99/mo.',
      bannerMobile: 'Black Friday: Premium for $3.99/mo.',
      cardLabel: 'Black Friday Exclusive',
      cta: 'Unlock Premium',
      endedNotice: 'The Black Friday sale has ended.',
      upgradeHeaderLine:
        "Open this team's full page with a full year of Premium for $3.99/mo — Black Friday through Cyber Monday only.",
    },
  },
];

const DAY_MS = 24 * 60 * 60 * 1000;
const UPCOMING_LOOKAHEAD_MS = 7 * DAY_MS;
const ENDED_LOOKBACK_MS = 30 * DAY_MS;

export function promotionEventName(promotion: Promotion, step: PromotionEventStep): string {
  return `${promotion.analyticsPrefix}_${step}`;
}

export function promotionStateAt(promotion: Promotion, nowMs: number): PromotionState {
  if (nowMs < Date.parse(promotion.startsAt)) return 'upcoming';
  return nowMs < Date.parse(promotion.endsAt) ? 'live' : 'ended';
}

export function findPromotionById(id: string, promotions: readonly Promotion[] = PROMOTIONS): Promotion | null {
  return promotions.find((promotion) => promotion.id === id) ?? null;
}

/** The live sale, else the next one starting within 7 days, else the latest one ended within 30. */
export function findRelevantPromotion(nowMs: number, promotions: readonly Promotion[] = PROMOTIONS): Promotion | null {
  const live = promotions.find((promotion) => promotionStateAt(promotion, nowMs) === 'live');
  if (live) return live;
  const upcoming = promotions
    .filter((promotion) => {
      const startsIn = Date.parse(promotion.startsAt) - nowMs;
      return startsIn > 0 && startsIn <= UPCOMING_LOOKAHEAD_MS;
    })
    .sort((a, b) => Date.parse(a.startsAt) - Date.parse(b.startsAt));
  if (upcoming.length > 0) return upcoming[0];
  const ended = promotions
    .filter((promotion) => {
      const endedFor = nowMs - Date.parse(promotion.endsAt);
      return endedFor >= 0 && endedFor <= ENDED_LOOKBACK_MS;
    })
    .sort((a, b) => Date.parse(b.endsAt) - Date.parse(a.endsAt));
  return ended[0] ?? null;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** `3d 4h 12m` from a day out, `hh:mm:ss` under 24 hours, never below zero. */
export function formatCountdown(msRemaining: number): string {
  const totalSeconds = Math.max(0, Math.floor(msRemaining / 1000));
  const days = Math.floor(totalSeconds / 86_400);
  const hours = Math.floor((totalSeconds % 86_400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

/**
 * Whether a viewer may be offered the sale: anyone signed out, anyone signed in on a plan without
 * premium, or an admin previewing it. Nothing is offered while the user or profile is loading or
 * failed, since a paying subscriber is indistinguishable from a free one until it resolves.
 */
export function isInSaleAudience({
  user,
  profile,
  isLoading,
  error,
  preview,
}: {
  user: unknown;
  profile: { plan: string } | null;
  isLoading: boolean;
  error: unknown;
  preview: boolean;
}): boolean {
  if (isLoading) return false;
  if (!user) return true;
  if (!profile || error) return false;
  if (preview && hasAdminPlan(profile.plan)) return true;
  return !hasPremiumPlan(profile.plan);
}
