import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Promotion } from './promotions';

const { gtagEvent } = vi.hoisted(() => ({ gtagEvent: vi.fn() }));
vi.mock('./analytics', () => ({ gtagEvent }));

import { trackPromotionEvent } from './events';

const SPRING_SALE = {
  id: 'spring-2027',
  campaign: 'spring-2027',
  analyticsPrefix: 'spring_sale',
} as Promotion;

beforeEach(() => {
  gtagEvent.mockClear();
  window.sessionStorage.clear();
  window.history.replaceState(null, '', '/upgrade');
});

afterEach(() => {
  window.sessionStorage.clear();
});

describe('trackPromotionEvent', () => {
  it("names the event after the sale and carries the session's attribution", () => {
    window.sessionStorage.setItem(
      'pitchrank_attribution',
      JSON.stringify({ utm_source: 'facebook', source: 'banner' })
    );

    trackPromotionEvent(SPRING_SALE, 'checkout_started', { price: 59.88 });

    expect(gtagEvent).toHaveBeenCalledWith('spring_sale_checkout_started', {
      utm_source: 'facebook',
      source: 'banner',
      promotion_id: 'spring-2027',
      campaign: 'spring-2027',
      page_path: '/upgrade',
      price: 59.88,
    });
  });

  it('prefers the source it is given over the stored one', () => {
    window.sessionStorage.setItem('pitchrank_attribution', JSON.stringify({ source: 'banner' }));

    trackPromotionEvent(SPRING_SALE, 'offer_view', { source: 'clutch_factor' });

    expect(gtagEvent.mock.calls[0][1]).toMatchObject({ source: 'clutch_factor' });
  });
});
