import 'server-only';

import {
  PROMOTIONS,
  findPromotionById,
  findRelevantPromotion,
  promotionStateAt,
  type Promotion,
  type PromotionState,
} from './promotions';

export type PromotionStatus = { promotion: Promotion; state: PromotionState } | { promotion: null; state: 'none' };

function promotionsDisabled(): boolean {
  return process.env.PROMOTIONS_DISABLED === 'true';
}

/**
 * `PROMOTION_WINDOW_OVERRIDE=<startISO>/<endISO>` moves every sale's window on a Vercel preview, so a
 * practice purchase can run before the real start. Production ignores it.
 */
function windowOverride(): { startsAt: string; endsAt: string } | null {
  const override = process.env.PROMOTION_WINDOW_OVERRIDE?.trim();
  if (process.env.VERCEL_ENV !== 'preview' || !override) return null;
  const [start, end] = override.split('/');
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    console.warn('PROMOTION_WINDOW_OVERRIDE ignored: expected <startISO>/<endISO>');
    return null;
  }
  return { startsAt: new Date(startMs).toISOString(), endsAt: new Date(endMs).toISOString() };
}

function effectivePromotions(): readonly Promotion[] {
  const override = windowOverride();
  return override ? PROMOTIONS.map((promotion) => ({ ...promotion, ...override })) : PROMOTIONS;
}

/** The sale every surface should describe right now. The kill switch reports a live sale as ended. */
export function getPromotionStatus(nowMs = Date.now()): PromotionStatus {
  const promotion = findRelevantPromotion(nowMs, effectivePromotions());
  if (!promotion) return { promotion: null, state: 'none' };
  const state = promotionStateAt(promotion, nowMs);
  return { promotion, state: state === 'live' && promotionsDisabled() ? 'ended' : state };
}

/** The sale with this id, only while the server clock says it is live and the kill switch is off. */
export function getLivePromotion(id: string, nowMs = Date.now()): Promotion | null {
  const promotion = findPromotionById(id, effectivePromotions());
  if (!promotion || promotionsDisabled()) return null;
  return promotionStateAt(promotion, nowMs) === 'live' ? promotion : null;
}

/** The Stripe coupon id from `STRIPE_COUPON_<ID>` (`black-friday-2026` → `STRIPE_COUPON_BLACK_FRIDAY_2026`). */
export function getPromotionCouponId(promotion: Promotion): string {
  const name = `STRIPE_COUPON_${promotion.id.toUpperCase().replace(/[^A-Z0-9]+/g, '_')}`;
  const couponId = process.env[name]?.trim();
  if (!couponId) throw new Error(`Missing ${name} environment variable`);
  return couponId;
}
