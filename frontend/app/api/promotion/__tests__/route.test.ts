import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Promotion } from '@/lib/promotions';

const { statusOverride } = vi.hoisted(() => ({ statusOverride: { current: null as unknown } }));

vi.mock('@/lib/promotions.server', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/promotions.server')>();
  return {
    ...actual,
    getPromotionStatus: (nowMs?: number) => statusOverride.current ?? actual.getPromotionStatus(nowMs),
  };
});

import { GET } from '../route';

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

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  statusOverride.current = null;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe('GET /api/promotion', () => {
  it("answers the live sale with the server's clock, cached for 30 seconds", async () => {
    vi.setSystemTime(new Date('2026-11-28T12:00:00Z'));
    vi.stubEnv('STRIPE_COUPON_BLACK_FRIDAY_2026', 'coupon_secret_value');

    const res = await GET();
    const body = await res.json();

    expect(res.headers.get('cache-control')).toBe('public, s-maxage=30');
    expect(body.state).toBe('live');
    expect(body.serverNow).toBe(Date.parse('2026-11-28T12:00:00Z'));
    expect(body.promotion).toMatchObject({
      id: 'black-friday-2026',
      startsAt: '2026-11-25T07:00:00Z',
      endsAt: '2026-12-01T07:00:00Z',
    });
    expect(JSON.stringify(body)).not.toContain('coupon_secret_value');
  });

  it('answers ended once the kill switch is on', async () => {
    vi.setSystemTime(new Date('2026-11-28T12:00:00Z'));
    vi.stubEnv('PROMOTIONS_DISABLED', 'true');

    expect((await (await GET()).json()).state).toBe('ended');
  });

  it('answers none outside any campaign period', async () => {
    vi.setSystemTime(new Date('2026-10-01T00:00:00Z'));

    expect(await (await GET()).json()).toEqual({ state: 'none', promotion: null, serverNow: Date.now() });
  });

  it('carries whatever sale the server resolves, with no code naming it', async () => {
    vi.setSystemTime(new Date('2027-04-02T00:00:00Z'));
    statusOverride.current = { promotion: SPRING_SALE, state: 'live' };

    expect(await (await GET()).json()).toEqual({ state: 'live', promotion: SPRING_SALE, serverNow: Date.now() });
  });
});
