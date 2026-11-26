import { describe, expect, it } from 'vitest';
import {
  PROMOTIONS,
  findPromotionById,
  findRelevantPromotion,
  formatCountdown,
  isInSaleAudience,
  promotionEventName,
  promotionStateAt,
  type Promotion,
} from './promotions';

const BLACK_FRIDAY = PROMOTIONS[0];
const at = (iso: string) => Date.parse(iso);

/** A second sale with nothing in common with the first, to show no surface hard-codes the first. */
const SPRING_SALE: Promotion = {
  id: 'spring-2027',
  startsAt: '2027-04-01T07:00:00Z',
  endsAt: '2027-04-03T07:00:00Z',
  planInterval: 'year',
  campaign: 'spring-2027',
  analyticsPrefix: 'spring_sale',
  display: {
    listPrice: '$69.99',
    firstYearPrice: '$59.88',
    monthlyPrice: '$4.99',
    percentOff: '14%',
    amountCents: 5988,
  },
  copy: {
    bannerLabel: 'Spring sale',
    bannerDesktop: 'Spring sale desktop',
    bannerMobile: 'Spring sale',
    cardLabel: 'Spring Exclusive',
    cta: 'Grab it',
    endedNotice: 'The spring sale has ended.',
    upgradeHeaderLine: 'Spring header line',
  },
};

describe('the Black Friday 2026 entry', () => {
  it('runs Wed 00:00 to the end of Monday, Arizona time, for $47.88 then $69.99', () => {
    expect(BLACK_FRIDAY).toMatchObject({
      id: 'black-friday-2026',
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
    });
  });
});

describe('promotionStateAt', () => {
  it.each([
    ['2026-11-25T06:59:59Z', 'upcoming'],
    ['2026-11-25T07:00:00Z', 'live'],
    ['2026-12-01T06:59:59Z', 'live'],
    ['2026-12-01T07:00:00Z', 'ended'],
  ])('reads %s as %s: the start counts, the end does not', (iso, state) => {
    expect(promotionStateAt(BLACK_FRIDAY, at(iso))).toBe(state);
  });
});

describe('findRelevantPromotion', () => {
  it('finds a sale starting within 7 days, and none further out', () => {
    expect(findRelevantPromotion(at('2026-11-18T07:00:00Z'))).toBe(BLACK_FRIDAY);
    expect(findRelevantPromotion(at('2026-11-18T06:59:59Z'))).toBeNull();
  });

  it('keeps a sale for 30 days after it ends, then lets it go', () => {
    expect(findRelevantPromotion(at('2026-12-31T07:00:00Z'))).toBe(BLACK_FRIDAY);
    expect(findRelevantPromotion(at('2026-12-31T07:00:01Z'))).toBeNull();
  });

  it('prefers a live sale, then the next upcoming one, over one that ended', () => {
    const list = [BLACK_FRIDAY, SPRING_SALE];
    expect(findRelevantPromotion(at('2027-04-02T00:00:00Z'), list)).toBe(SPRING_SALE);
    expect(findRelevantPromotion(at('2026-11-28T00:00:00Z'), list)).toBe(BLACK_FRIDAY);
    const earlyEnded = { ...BLACK_FRIDAY, endsAt: '2027-03-30T00:00:00Z' };
    expect(findRelevantPromotion(at('2027-03-31T00:00:00Z'), [earlyEnded, SPRING_SALE])).toBe(SPRING_SALE);
  });

  it('follows any entry it is given, by its own window', () => {
    expect(findRelevantPromotion(at('2027-04-01T07:00:00Z'), [SPRING_SALE])).toBe(SPRING_SALE);
    expect(promotionStateAt(SPRING_SALE, at('2027-04-03T07:00:00Z'))).toBe('ended');
    expect(findPromotionById('spring-2027', [SPRING_SALE])).toBe(SPRING_SALE);
    expect(findPromotionById('black-friday-2026', [SPRING_SALE])).toBeNull();
  });
});

describe('promotionEventName', () => {
  it("names browser and server steps after the sale's own prefix", () => {
    expect(promotionEventName(BLACK_FRIDAY, 'banner_view')).toBe('black_friday_banner_view');
    expect(promotionEventName(SPRING_SALE, 'purchase_completed')).toBe('spring_sale_purchase_completed');
  });
});

describe('formatCountdown', () => {
  it.each([
    [3 * 86_400_000, '3d 0h 0m'],
    [3 * 86_400_000 + 4 * 3_600_000 + 12 * 60_000 + 59_000, '3d 4h 12m'],
    [3_600_000, '01:00:00'],
    [59_000, '00:00:59'],
    [86_399_000, '23:59:59'],
    [-5_000, '00:00:00'],
  ])('shows %i ms as %s', (ms, text) => {
    expect(formatCountdown(ms)).toBe(text);
  });
});

describe('isInSaleAudience', () => {
  const user = { id: 'user-1' };
  const base = { user, profile: { plan: 'free' }, isLoading: false, error: null, preview: false };

  it.each([
    ['a signed-out visitor', { user: null, profile: null }, true],
    ['anyone while the session is loading', { user: null, profile: null, isLoading: true }, false],
    ['a signed-in viewer whose profile has not loaded', { profile: null }, false],
    ['a signed-in viewer whose profile fetch failed', { error: new Error('down') }, false],
    ['a free account', {}, true],
    ['a premium account (paying, trialing, past_due or cancel-scheduled)', { profile: { plan: 'premium' } }, false],
    ['an admin', { profile: { plan: 'admin' } }, false],
    ['an admin previewing', { profile: { plan: 'admin' }, preview: true }, true],
    ['a premium account asking for a preview', { profile: { plan: 'premium' }, preview: true }, false],
  ])('%s: %s', (_label, overrides, expected) => {
    expect(isInSaleAudience({ ...base, ...overrides })).toBe(expected);
  });
});
