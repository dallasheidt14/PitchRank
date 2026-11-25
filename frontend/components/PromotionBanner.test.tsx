import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { state, mockStartCheckout } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY = 'price_yearly_test';
  return {
    mockStartCheckout: vi.fn(),
    state: {
      pathname: '/',
      user: null as { id: string } | null,
      profile: null as { plan: string } | null,
      error: null as Error | null,
      isLoading: false,
    },
  };
});

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => state.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock('next/image', () => ({ default: () => null }));
vi.mock('@/hooks/useUser', () => ({
  useUser: () => ({
    user: state.user,
    profile: state.profile,
    isLoading: state.isLoading,
    error: state.error,
    signOut: vi.fn(),
  }),
}));
vi.mock('./GlobalSearch', () => ({
  GLOBAL_SEARCH_INPUT_IDS: { mobile: 'global-search-mobile', desktop: 'global-search-desktop' },
  GlobalSearch: () => null,
}));
vi.mock('./FeedbackTrigger', () => ({ FeedbackTrigger: () => null }));
vi.mock('@/lib/events', () => ({
  trackPromotionEvent: vi.fn(),
  trackUpgradePageViewed: vi.fn(),
  trackPlanSelected: vi.fn(),
  trackCheckoutInitiated: vi.fn(),
}));
vi.mock('@/lib/stripe/client', () => ({ startCheckout: mockStartCheckout }));
vi.mock('@/lib/api', () => ({
  api: { getDbStats: () => Promise.resolve({ totalTeams: 0, totalGames: 0 }), getPaywallTeamPreview: vi.fn() },
}));

import { Navigation } from './Navigation';
import UpgradePage from '@/app/upgrade/page';
import { resetLivePromotionForTests } from '@/hooks/useLivePromotion';
import { readAttribution } from '@/lib/attribution';
import { PROMOTIONS } from '@/lib/promotions';
import { trackPromotionEvent } from '@/lib/events';

const BLACK_FRIDAY = PROMOTIONS[0];
const STARTS = Date.parse(BLACK_FRIDAY.startsAt);
const ENDS = Date.parse(BLACK_FRIDAY.endsAt);
const DURING = Date.parse('2026-11-28T12:00:00Z');
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

type Answer =
  | { state: 'live' | 'upcoming' | 'ended' | 'none'; serverSkewMs?: number; ageSeconds?: number }
  | 'reject'
  | 'hang'
  | 'stall-body';

let answers: Answer[] = [];
let fetchMock: ReturnType<typeof vi.fn>;
let container: HTMLDivElement;
let root: Root;

/** `/api/promotion` answers these in turn, repeating the last. */
function answerPromotion(...queue: Answer[]) {
  answers = queue;
}

function respond(init?: RequestInit): Promise<unknown> {
  const answer = answers.length > 1 ? answers.shift()! : answers[0];
  if (answer === 'reject') return Promise.reject(new TypeError('Failed to fetch'));
  // A stalled request settles only when its signal aborts, as fetch does, for the headers or the body.
  const onAbort = () =>
    new Promise((_, reject) =>
      init?.signal?.addEventListener('abort', () =>
        reject(new DOMException('The operation was aborted.', 'AbortError'))
      )
    );
  if (answer === 'hang') return onAbort();
  if (answer === 'stall-body') return Promise.resolve({ ok: true, headers: new Headers(), json: onAbort });
  return Promise.resolve({
    ok: true,
    headers: new Headers(answer.ageSeconds ? { age: String(answer.ageSeconds) } : {}),
    json: async () => ({
      state: answer.state,
      promotion: answer.state === 'none' ? null : BLACK_FRIDAY,
      serverNow: Date.now() + (answer.serverSkewMs ?? 0),
    }),
  });
}

const banner = () => container.querySelector<HTMLElement>('[data-testid="promotion-banner"]');
const bannerShown = () => banner() !== null;
const htmlHasBannerClass = () => document.documentElement.classList.contains('promo-banner-visible');
const promotionRequests = () => fetchMock.mock.calls.filter(([url]) => url === '/api/promotion').length;

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function renderAt(now: number, element: React.ReactElement = <Navigation />) {
  vi.setSystemTime(now);
  await act(async () => root.render(element));
  await advance(0);
}

/** Unmount every subscriber and mount again, as a client-side navigation or Strict Mode does. */
async function remount(element: React.ReactElement = <Navigation />) {
  await act(async () => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(element));
  await advance(0);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
  resetLivePromotionForTests();
  Object.assign(state, { pathname: '/', user: null, profile: null, error: null, isLoading: false });
  answerPromotion({ state: 'live' });
  fetchMock = vi.fn((_url: string, init?: RequestInit) => respond(init));
  vi.stubGlobal('fetch', fetchMock);
  window.sessionStorage.clear();
  window.history.replaceState(null, '', '/');
  document.documentElement.classList.remove('promo-banner-visible');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  resetLivePromotionForTests();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('who sees the sale banner', () => {
  it.each([
    ['a signed-out visitor', { user: null, profile: null }],
    ['a free account', { user: { id: 'u' }, profile: { plan: 'free' } }],
  ])('shows it to %s', async (_label, viewer) => {
    Object.assign(state, viewer);
    await renderAt(DURING);

    expect(bannerShown()).toBe(true);
    expect(banner()!.textContent).toContain(BLACK_FRIDAY.copy.bannerDesktop);
    expect(banner()!.textContent).toContain(BLACK_FRIDAY.copy.bannerMobile);
    expect(trackPromotionEvent).toHaveBeenCalledWith(BLACK_FRIDAY, 'banner_view', { source: 'banner' });
  });

  it.each([
    ['a premium account', { user: { id: 'u' }, profile: { plan: 'premium' } }],
    ['an admin not previewing', { user: { id: 'u' }, profile: { plan: 'admin' } }],
    ['anyone while the session loads', { isLoading: true }],
    ['a signed-in viewer with no profile', { user: { id: 'u' }, profile: null }],
    [
      'a signed-in viewer whose profile fetch failed',
      { user: { id: 'u' }, profile: { plan: 'free' }, error: new Error('x') },
    ],
  ])('hides it from %s', async (_label, viewer) => {
    Object.assign(state, viewer);
    await renderAt(DURING);

    expect(bannerShown()).toBe(false);
    expect(htmlHasBannerClass()).toBe(false);
  });

  it('shows an admin a preview before the sale starts, keeping the preview on its link', async () => {
    window.history.replaceState(null, '', '/?promo_preview=1');
    Object.assign(state, { user: { id: 'a' }, profile: { plan: 'admin' } });
    answerPromotion({ state: 'upcoming' });
    await renderAt(STARTS - 2 * 24 * 60 * MINUTE);

    expect(bannerShown()).toBe(true);
    expect(banner()!.querySelector('a')!.getAttribute('href')).toBe(
      '/upgrade?campaign=black-friday-2026&source=banner&promo_preview=1'
    );
  });

  it('is not shown on the page a buyer returns to after paying', async () => {
    state.pathname = '/upgrade/success';
    await renderAt(DURING);

    expect(bannerShown()).toBe(false);
  });

  it('never asks for the sale outside a campaign period', async () => {
    await renderAt(Date.parse('2026-10-01T12:00:00Z'));

    expect(bannerShown()).toBe(false);
    expect(promotionRequests()).toBe(0);
  });
});

describe('the banner in the header', () => {
  it("sits first in Navigation's header, above the menu row, and grows the header while shown", async () => {
    await renderAt(DURING);

    const header = container.querySelector('[data-testid="main-navigation"]')!;
    expect(header.firstElementChild).toBe(banner());
    expect(banner()!.nextElementSibling!.className).toContain('h-16');
    // It takes over the header's safe-area padding (globals.css drops the header's while the class is set).
    expect(banner()!.className.split(/\s+/)).toContain('safe-top');
    expect(banner()!.firstElementChild!.className.split(/\s+/)).toContain('h-10');
    expect(htmlHasBannerClass()).toBe(true);
  });

  it('goes away when dismissed, for the rest of the session', async () => {
    await renderAt(DURING);

    await act(async () =>
      banner()!.querySelector<HTMLButtonElement>('button[aria-label="Dismiss the sale banner"]')!.click()
    );

    expect(bannerShown()).toBe(false);
    expect(htmlHasBannerClass()).toBe(false);

    await act(async () => root.unmount());
    root = createRoot(container);
    await renderAt(DURING + MINUTE);
    expect(bannerShown()).toBe(false);
  });

  it('links to the sale from any other page', async () => {
    await renderAt(DURING);

    expect(banner()!.querySelector('a')!.getAttribute('href')).toBe(
      '/upgrade?campaign=black-friday-2026&source=banner'
    );
  });

  it("scrolls to the sale card on /upgrade, and the card's checkout still says the banner sent them", async () => {
    state.pathname = '/upgrade';
    window.history.replaceState(null, '', '/upgrade?utm_source=facebook');
    await renderAt(
      DURING,
      <>
        <Navigation />
        <UpgradePage />
      </>
    );

    const link = banner()!.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('#sale');
    await act(async () => link.click());
    expect(readAttribution()).toEqual({ utm_source: 'facebook', campaign: 'black-friday-2026', source: 'banner' });

    await act(async () => container.querySelector<HTMLElement>('#sale button')!.click());
    expect(mockStartCheckout).toHaveBeenCalledWith('price_yearly_test', null, {
      promotion: 'black-friday-2026',
      attribution: { utm_source: 'facebook', campaign: 'black-friday-2026', source: 'banner' },
    });
    // The page's own URL names no source; the browser event must say what the purchase will say.
    expect(trackPromotionEvent).toHaveBeenCalledWith(BLACK_FRIDAY, 'checkout_started', {
      source: 'banner',
      price: 47.88,
    });
  });
});

describe("the banner's clock", () => {
  it("counts down by the server's clock, allowing for a cached answer's age", async () => {
    // The answer was generated 30s ago on a server 60s behind this browser: net 30s behind.
    answerPromotion({ state: 'live', serverSkewMs: -60 * SECOND, ageSeconds: 30 });
    await renderAt(ENDS - 2 * 60 * MINUTE);

    const countdown = () => container.querySelector('[data-testid="promotion-banner-countdown"]')!.textContent;
    expect(countdown()).toBe('Ends in 02:00:30');
    await advance(5 * SECOND);
    expect(countdown()).toBe('Ends in 02:00:25');
  });

  it('hides itself at the end with no answer from the server and no reload', async () => {
    answerPromotion({ state: 'live' }, 'hang');
    await renderAt(ENDS - 3 * SECOND);
    expect(bannerShown()).toBe(true);

    await advance(4 * SECOND);

    expect(bannerShown()).toBe(false);
    expect(htmlHasBannerClass()).toBe(false);
  });

  it('hides within a second of the end even when its end timer runs late, as on a device waking from sleep', async () => {
    answerPromotion({ state: 'live' }, 'hang');
    await renderAt(ENDS - 3 * MINUTE);
    expect(bannerShown()).toBe(true);

    // The clock jumps past the end while the timer queue stands still.
    vi.setSystemTime(ENDS + SECOND);
    await advance(SECOND);

    expect(bannerShown()).toBe(false);
  });

  it('retries a failed first request just after the start within 5 seconds, not 5 minutes', async () => {
    answerPromotion('reject', { state: 'live' });
    await renderAt(STARTS + 10 * SECOND);
    expect(bannerShown()).toBe(false);

    await advance(5 * SECOND);

    expect(bannerShown()).toBe(true);
  });

  it('retries a failed first request mid-sale after 30 seconds, not 5 minutes or 5 seconds', async () => {
    answerPromotion('reject', { state: 'live' });
    await renderAt(DURING);
    expect(bannerShown()).toBe(false);

    await advance(29 * SECOND);
    expect(promotionRequests()).toBe(1);
    await advance(SECOND);

    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('recovers from a first request that stalls mid-sale', async () => {
    answerPromotion('hang', { state: 'live' });
    await renderAt(DURING);

    // The stalled request is abandoned after 10 seconds, then retried 30 seconds later.
    await advance(40 * SECOND);

    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('retries a failed first request within 30 seconds on a browser whose clock is two hours behind', async () => {
    answerPromotion('reject', { state: 'live', serverSkewMs: 2 * HOUR });
    await renderAt(STARTS - HOUR);

    await advance(30 * SECOND);

    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('keeps retrying a failed first request on a browser whose clock is past the end', async () => {
    answerPromotion('reject', { state: 'live', serverSkewMs: -HOUR });
    await renderAt(ENDS + 5 * MINUTE);

    await advance(30 * SECOND);

    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('recovers from a first answer whose body stalls mid-sale', async () => {
    answerPromotion('stall-body', { state: 'live' });
    await renderAt(DURING);

    await advance(40 * SECOND);

    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('asks once before the start, then at the start, when the sale is upcoming', async () => {
    answerPromotion({ state: 'upcoming' }, { state: 'live' });
    await renderAt(STARTS - HOUR);

    await advance(30 * MINUTE);
    expect(promotionRequests()).toBe(1);
    await advance(30 * MINUTE);

    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('retries a failed first request 10 seconds before the start at the start, not 30 seconds on', async () => {
    answerPromotion('reject', { state: 'live' });
    await renderAt(STARTS - 10 * SECOND);

    await advance(10 * SECOND);

    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('retries a failed first request just after the end within 5 seconds', async () => {
    answerPromotion('reject', { state: 'ended' });
    await renderAt(ENDS + 10 * SECOND);

    await advance(5 * SECOND);

    expect(promotionRequests()).toBe(2);
  });

  it('starts asking once a page load that began outside a campaign period reaches one', async () => {
    await renderAt(STARTS - 8 * DAY, <UpgradePage />);
    // Still outside, a remount asks nothing.
    await remount(<UpgradePage />);
    expect(promotionRequests()).toBe(0);

    vi.setSystemTime(DURING);
    await remount(<Navigation />);

    expect(promotionRequests()).toBe(1);
    expect(bannerShown()).toBe(true);
  });

  it('keeps retrying a page load that reached a campaign period when its first request there fails', async () => {
    answerPromotion('reject', { state: 'live' });
    await renderAt(STARTS - 8 * DAY, <UpgradePage />);

    vi.setSystemTime(DURING);
    await remount(<Navigation />);
    expect(promotionRequests()).toBe(1);
    await advance(30 * SECOND);

    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('starts asking when the header mounts beside an upgrade page left open from before the campaign', async () => {
    // Fragments on both renders keep the upgrade page mounted, so the header is the second subscriber.
    await renderAt(
      STARTS - 8 * DAY,
      <>
        <UpgradePage />
      </>
    );

    vi.setSystemTime(DURING);
    await act(async () =>
      root.render(
        <>
          <UpgradePage />
          <Navigation />
        </>
      )
    );
    await advance(0);

    expect(promotionRequests()).toBe(1);
    expect(bannerShown()).toBe(true);
  });

  it('asks once when the header remounts while its first request is in flight', async () => {
    answerPromotion('hang');
    await renderAt(DURING);

    await remount();

    expect(promotionRequests()).toBe(1);
  });

  it('starts no second request at the start while the first is still in flight', async () => {
    answerPromotion('hang', { state: 'live' });
    await renderAt(STARTS - 2 * SECOND);
    await remount();

    await advance(3 * SECOND);
    expect(promotionRequests()).toBe(1);

    // The stalled request is abandoned at 10 seconds; the near-start retry follows 5 seconds later.
    await advance(12 * SECOND);
    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);
  });

  it('retries a failed refresh mid-sale on the 5-minute schedule, not every 5 seconds', async () => {
    answerPromotion({ state: 'live' }, 'reject', { state: 'live' });
    await renderAt(DURING);

    await advance(5 * MINUTE);
    await advance(30 * SECOND);
    expect(promotionRequests()).toBe(2);
    expect(bannerShown()).toBe(true);

    await advance(5 * MINUTE);
    expect(promotionRequests()).toBe(3);
  });

  it('stops retrying a failed request soon after the end', async () => {
    answerPromotion({ state: 'live' }, 'reject');
    await renderAt(ENDS - 3 * SECOND);

    await advance(200 * SECOND);
    const afterTheEnd = promotionRequests();
    await advance(10 * MINUTE);

    expect(promotionRequests()).toBe(afterTheEnd);
    expect(bannerShown()).toBe(false);
  });

  it('appears at the start once the server says so', async () => {
    answerPromotion({ state: 'upcoming' }, { state: 'live' });
    await renderAt(STARTS - 10 * SECOND);
    expect(bannerShown()).toBe(false);

    await advance(10 * SECOND);

    expect(bannerShown()).toBe(true);
  });

  it('retries a stale answer at the start every 5 seconds until the server says live', async () => {
    answerPromotion({ state: 'upcoming' }, { state: 'upcoming' }, { state: 'live' });
    await renderAt(STARTS - SECOND);

    await advance(SECOND);
    expect(bannerShown()).toBe(false);
    await advance(5 * SECOND);
    expect(bannerShown()).toBe(true);
  });

  it('retries a failed request at the start after 5 seconds', async () => {
    answerPromotion({ state: 'upcoming' }, 'reject', { state: 'live' });
    await renderAt(STARTS - SECOND);

    await advance(SECOND);
    expect(bannerShown()).toBe(false);
    await advance(5 * SECOND);
    expect(bannerShown()).toBe(true);
  });

  it('goes away within 5 minutes of the kill switch', async () => {
    answerPromotion({ state: 'live' }, { state: 'ended' });
    await renderAt(DURING);
    expect(bannerShown()).toBe(true);

    await advance(5 * MINUTE);

    expect(bannerShown()).toBe(false);
  });

  it('stays up through a failed refresh and keeps refreshing', async () => {
    answerPromotion({ state: 'live' }, 'reject', { state: 'live' });
    await renderAt(DURING);

    await advance(5 * MINUTE);
    expect(bannerShown()).toBe(true);
    expect(promotionRequests()).toBe(2);

    await advance(5 * MINUTE);
    expect(bannerShown()).toBe(true);
    expect(promotionRequests()).toBe(3);
  });
});
