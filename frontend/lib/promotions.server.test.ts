import { afterEach, describe, expect, it, vi } from 'vitest';
import { getLivePromotion, getPromotionCouponId, getPromotionStatus } from './promotions.server';
import { PROMOTIONS } from './promotions';

const BLACK_FRIDAY = PROMOTIONS[0];
const at = (iso: string) => Date.parse(iso);
const DURING = at('2026-11-28T12:00:00Z');

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('getPromotionStatus', () => {
  it.each([
    ['2026-11-26T12:00:00Z', 'upcoming'],
    ['2026-11-28T12:00:00Z', 'live'],
    ['2026-12-02T12:00:00Z', 'ended'],
  ])('describes the sale at %s as %s', (iso, state) => {
    expect(getPromotionStatus(at(iso))).toEqual({ promotion: BLACK_FRIDAY, state });
  });

  it('reports none outside any campaign period', () => {
    expect(getPromotionStatus(at('2026-10-01T00:00:00Z'))).toEqual({ promotion: null, state: 'none' });
  });

  it('reports a live sale as ended once the kill switch is on', () => {
    vi.stubEnv('PROMOTIONS_DISABLED', 'true');

    expect(getPromotionStatus(DURING).state).toBe('ended');
    expect(getLivePromotion('black-friday-2026', DURING)).toBeNull();
  });

  it('moves the window on a preview with the override set, and nowhere else', () => {
    const override = '2026-11-24T00:00:00Z/2026-11-25T00:00:00Z';
    const now = at('2026-11-24T12:00:00Z');
    vi.stubEnv('PROMOTION_WINDOW_OVERRIDE', override);

    vi.stubEnv('VERCEL_ENV', 'production');
    expect(getPromotionStatus(now).state).toBe('upcoming');
    expect(getLivePromotion('black-friday-2026', now)).toBeNull();

    vi.stubEnv('VERCEL_ENV', 'preview');
    expect(getPromotionStatus(now)).toEqual({
      promotion: { ...BLACK_FRIDAY, startsAt: '2026-11-24T00:00:00.000Z', endsAt: '2026-11-25T00:00:00.000Z' },
      state: 'live',
    });
    expect(getLivePromotion('black-friday-2026', now)?.endsAt).toBe('2026-11-25T00:00:00.000Z');
  });

  it('ignores a malformed override', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.stubEnv('VERCEL_ENV', 'preview');
    vi.stubEnv('PROMOTION_WINDOW_OVERRIDE', 'yesterday/tomorrow');

    expect(getPromotionStatus(DURING)).toEqual({ promotion: BLACK_FRIDAY, state: 'live' });
  });
});

describe('getLivePromotion', () => {
  it('answers the sale only while it is live, and only for its own id', () => {
    expect(getLivePromotion('black-friday-2026', DURING)).toBe(BLACK_FRIDAY);
    expect(getLivePromotion('black-friday-2026', at('2026-11-27T06:59:59Z'))).toBeNull();
    expect(getLivePromotion('black-friday-2026', at('2026-12-01T07:00:00Z'))).toBeNull();
    expect(getLivePromotion('spring-2027', DURING)).toBeNull();
  });
});

describe('getPromotionCouponId', () => {
  it("reads the coupon from the sale's own environment variable", () => {
    vi.stubEnv('STRIPE_COUPON_BLACK_FRIDAY_2026', 'coupon_test_bf');

    expect(getPromotionCouponId(BLACK_FRIDAY)).toBe('coupon_test_bf');
  });

  it("reads another sale's coupon from that sale's own variable", () => {
    vi.stubEnv('STRIPE_COUPON_BLACK_FRIDAY_2026', 'coupon_test_bf');
    vi.stubEnv('STRIPE_COUPON_SPRING_2027', 'coupon_test_spring');

    expect(getPromotionCouponId({ ...BLACK_FRIDAY, id: 'spring-2027' })).toBe('coupon_test_spring');
  });

  it('throws when the coupon is not configured', () => {
    vi.stubEnv('STRIPE_COUPON_BLACK_FRIDAY_2026', '');

    expect(() => getPromotionCouponId(BLACK_FRIDAY)).toThrow('Missing STRIPE_COUPON_BLACK_FRIDAY_2026');
  });
});
