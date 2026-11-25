import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const TEAM_ID = '11111111-1111-1111-1111-111111111111';

const { mockPreview, mockStartCheckout, state } = vi.hoisted(() => {
  process.env.NEXT_PUBLIC_STRIPE_PRICE_MONTHLY = 'price_monthly_test';
  process.env.NEXT_PUBLIC_STRIPE_PRICE_YEARLY = 'price_yearly_test';
  return {
    mockPreview: vi.fn(),
    mockStartCheckout: vi.fn(),
    state: {
      next: null as string | null,
      params: {} as Record<string, string>,
      user: null as { id: string } | null,
      profile: null as { plan: string } | null,
      profileError: null as Error | null,
      userLoading: false,
    },
  };
});

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams({ ...(state.next ? { next: state.next } : {}), ...state.params }),
}));
vi.mock('@/hooks/useUser', () => ({
  useUser: () => ({
    user: state.user,
    profile: state.profile,
    isLoading: state.userLoading,
    error: state.profileError,
  }),
}));
vi.mock('@/lib/events', () => ({
  trackUpgradePageViewed: vi.fn(),
  trackPlanSelected: vi.fn(),
  trackCheckoutInitiated: vi.fn(),
  trackPromotionEvent: vi.fn(),
}));
vi.mock('@/lib/stripe/client', () => ({ startCheckout: mockStartCheckout }));
vi.mock('@/lib/api', () => ({
  api: {
    getDbStats: () => Promise.resolve({ totalTeams: 0, totalGames: 0 }),
    getPaywallTeamPreview: mockPreview,
  },
}));

import UpgradePage from './page';
import { resetLivePromotionForTests } from '@/hooks/useLivePromotion';
import { PROMOTIONS } from '@/lib/promotions';
import { trackCheckoutInitiated, trackPlanSelected, trackPromotionEvent } from '@/lib/events';

const BLACK_FRIDAY = PROMOTIONS[0];
const DURING = new Date('2026-11-28T12:00:00Z');
const OUTSIDE = new Date('2026-10-01T12:00:00Z');

let container: HTMLDivElement;
let root: Root;

/** What `/api/promotion` answers; the page's own hook asks it once a campaign period is near. */
function answerPromotion(answer: 'live' | 'upcoming' | 'ended') {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      headers: new Headers(),
      json: async () => ({ state: answer, promotion: BLACK_FRIDAY, serverNow: Date.now() }),
    }))
  );
}

/** Lets the promotion request resolve and the page re-render. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function render() {
  await act(async () => {
    root.render(<UpgradePage />);
  });
}

const MONTHLY_CARD = 'Month-to-month';
const YEARLY_CARD = 'serious soccer families';

function planCard(text: string) {
  return Array.from(container.querySelectorAll<HTMLElement>('[data-slot="card"]')).find((card) =>
    card.textContent?.includes(text)
  )!;
}

function cardClasses(text: string) {
  return planCard(text).className.split(/\s+/);
}

function hidingClasses(text: string) {
  return cardClasses(text).filter((name) => /(^|:)hidden$/.test(name));
}

function planButton(name: string) {
  return Array.from(container.querySelectorAll('button')).find((button) => button.textContent?.startsWith(name))!;
}

async function tap(element: HTMLElement) {
  await act(async () => element.click());
}

beforeEach(() => {
  vi.clearAllMocks();
  state.next = null;
  state.params = {};
  state.user = null;
  state.profile = null;
  state.profileError = null;
  state.userLoading = false;
  // Outside any campaign period unless a test says otherwise, so the promotion hook fetches nothing.
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(OUTSIDE);
  resetLivePromotionForTests();
  window.sessionStorage.clear();
  window.history.replaceState(null, '', '/upgrade');
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  resetLivePromotionForTests();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('UpgradePage paywall', () => {
  it('names the team the parent tapped', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue({
      team_name: 'Phoenix Rising 2014',
      club_name: 'Phoenix Rising',
      age: 12,
      gender: 'M',
      rank_in_cohort_final: 7,
    });
    await render();
    expect(mockPreview).toHaveBeenCalledWith(TEAM_ID);
    expect(container.textContent).toContain('You were looking at');
    expect(container.textContent).toContain('Phoenix Rising 2014');
    expect(container.textContent).toContain('#7 nationally');
  });

  it('does not look anything up for a next that is not a team page', async () => {
    state.next = '/compare';
    await render();
    expect(mockPreview).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain('You were looking at');
  });

  it("holds the banner's place while the tapped team loads", async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockReturnValue(new Promise(() => {}));
    await render();
    expect(container.querySelector('[data-testid="tapped-team-placeholder"]')).not.toBeNull();
    expect(container.textContent).toContain('You were looking at');
  });

  it('drops the placeholder when the team lookup fails', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockRejectedValue(new Error('network'));
    await render();
    expect(container.querySelector('[data-testid="tapped-team-placeholder"]')).toBeNull();
    expect(container.textContent).not.toContain('You were looking at');
  });

  it('shows no banner when the team is unknown', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue(null);
    await render();
    expect(container.textContent).not.toContain('You were looking at');
  });

  it('shows both plan cards on phones, with Yearly first below md and highlighted', async () => {
    await render();
    expect(hidingClasses(MONTHLY_CARD)).toEqual([]);
    expect(hidingClasses(YEARLY_CARD)).toEqual([]);
    expect(cardClasses(YEARLY_CARD)).toEqual(expect.arrayContaining(['order-first', 'md:order-0', 'ring-2']));
    expect(cardClasses(MONTHLY_CARD)).not.toContain('ring-2');
  });

  it('keeps Monthly ahead of Yearly in one grid, so computers show Monthly on the left', async () => {
    await render();
    const monthly = planCard(MONTHLY_CARD);
    const yearly = planCard(YEARLY_CARD);
    expect(monthly.parentElement).toBe(yearly.parentElement);
    expect(monthly.parentElement!.className.split(/\s+/)).toEqual(expect.arrayContaining(['grid', 'md:grid-cols-2']));
    expect(monthly.compareDocumentPosition(yearly) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(cardClasses(MONTHLY_CARD).filter((name) => /(^|:)order-/.test(name))).toEqual([]);
    expect(cardClasses(YEARLY_CARD)).toContain('md:order-0');
  });

  it('brings the plan a button names to the top on phones, keeping the other visible', async () => {
    await render();
    await tap(planButton('Monthly'));
    expect(cardClasses(MONTHLY_CARD)).toContain('ring-2');
    expect(cardClasses(YEARLY_CARD)).not.toContain('ring-2');
    expect(cardClasses(YEARLY_CARD)).not.toContain('order-first');
    expect(hidingClasses(YEARLY_CARD)).toEqual([]);

    await tap(planButton('Yearly'));
    expect(cardClasses(YEARLY_CARD)).toEqual(expect.arrayContaining(['ring-2', 'order-first', 'md:order-0']));
    expect(cardClasses(MONTHLY_CARD)).not.toContain('ring-2');
    expect(hidingClasses(MONTHLY_CARD)).toEqual([]);
  });

  it('holds the card order when a plan button is tapped again', async () => {
    await render();
    await tap(planButton('Yearly'));
    expect(cardClasses(YEARLY_CARD)).toContain('order-first');

    await tap(planButton('Monthly'));
    await tap(planButton('Monthly'));
    expect(cardClasses(YEARLY_CARD)).not.toContain('order-first');
  });

  it('reorders from a plan button even when a card tap already chose that plan', async () => {
    await render();
    await tap(planCard(MONTHLY_CARD));
    await tap(planButton('Monthly'));
    expect(cardClasses(YEARLY_CARD)).not.toContain('order-first');

    await tap(planCard(YEARLY_CARD));
    await tap(planButton('Yearly'));
    expect(cardClasses(YEARLY_CARD)).toContain('order-first');
  });

  it('highlights a tapped card without moving either card on phones', async () => {
    await render();
    await tap(planCard(MONTHLY_CARD));
    expect(cardClasses(MONTHLY_CARD)).toContain('ring-2');
    expect(cardClasses(YEARLY_CARD)).not.toContain('ring-2');
    expect(cardClasses(YEARLY_CARD)).toContain('order-first');

    await tap(planButton('Monthly'));
    await tap(planCard(YEARLY_CARD));
    expect(cardClasses(YEARLY_CARD)).toContain('ring-2');
    expect(cardClasses(MONTHLY_CARD)).not.toContain('ring-2');
    expect(cardClasses(YEARLY_CARD)).not.toContain('order-first');
  });

  it("starts Monthly from Monthly's own button while Yearly is selected, leaving the selection alone", async () => {
    await render();
    await tap(planCard(MONTHLY_CARD).querySelector('button')!);
    expect(mockStartCheckout).toHaveBeenCalledTimes(1);
    expect(mockStartCheckout).toHaveBeenCalledWith('price_monthly_test', null);
    expect(cardClasses(YEARLY_CARD)).toContain('ring-2');
  });

  it("starts Yearly from Yearly's own button while Monthly is selected, leaving the selection alone", async () => {
    await render();
    await tap(planCard(MONTHLY_CARD));
    await tap(planCard(YEARLY_CARD).querySelector('button')!);
    expect(mockStartCheckout).toHaveBeenCalledTimes(1);
    expect(mockStartCheckout).toHaveBeenCalledWith('price_yearly_test', null);
    expect(cardClasses(MONTHLY_CARD)).toContain('ring-2');
  });

  it('passes the tapped team into checkout', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue(null);
    await render();
    await tap(planCard(MONTHLY_CARD).querySelector('button')!);
    expect(mockStartCheckout).toHaveBeenCalledWith('price_monthly_test', `/teams/${TEAM_ID}`);
  });

  it('passes nothing into checkout for a next that is not a team page', async () => {
    state.next = '/watchlist';
    await render();
    await tap(planCard(MONTHLY_CARD).querySelector('button')!);
    expect(mockStartCheckout).toHaveBeenCalledWith('price_monthly_test', null);
  });

  it("brings a failed checkout's message into view", async () => {
    const scrolledTo: Array<string | null> = [];
    const scrollIntoView = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function (this: Element) {
      scrolledTo.push(this.textContent);
    });
    mockStartCheckout.mockRejectedValueOnce(new Error('You already have an active subscription'));
    await render();
    expect(scrolledTo).toEqual([]);

    await tap(planCard(MONTHLY_CARD).querySelector('button')!);
    expect(scrolledTo).toEqual(['You already have an active subscription']);
    scrollIntoView.mockRestore();
  });

  it('keeps the sign-in link pointed at the tapped team', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue(null);
    await render();
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'));
    expect(hrefs).toContain(`/login?next=${encodeURIComponent(`/teams/${TEAM_ID}`)}`);
  });

  it.each([
    ['signed in', { id: 'user-1' }, false],
    ['still loading the session', null, true],
  ])('offers no sign-in link to a visitor %s', async (_label, user, userLoading) => {
    state.user = user;
    state.userLoading = userLoading;
    await render();
    const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href') ?? '');
    expect(hrefs.filter((href) => href.startsWith('/login'))).toEqual([]);
  });

  it('keeps the free-trial line under the tapped team outside a sale', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue({ team_name: 'Phoenix Rising 2014', club_name: null, age: 12, gender: 'M' });
    await render();
    expect(container.textContent).toContain("Start your free trial to open this team's full page.");
  });

  it('drops the old team banner when the destination is no longer a team', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue({
      team_name: 'Phoenix Rising 2014',
      club_name: null,
      age: 12,
      gender: 'M',
      rank_in_cohort_final: 7,
    });
    await render();
    expect(container.textContent).toContain('Phoenix Rising 2014');
    state.next = '/compare';
    await render();
    expect(container.textContent).not.toContain('Phoenix Rising 2014');
  });
});

describe('UpgradePage during a sale', () => {
  async function renderDuring(answer: 'live' | 'upcoming' | 'ended' = 'live', at: Date = DURING) {
    vi.setSystemTime(at);
    answerPromotion(answer);
    await render();
    await settle();
  }

  const saleCard = () => container.querySelector<HTMLElement>('#sale');

  it('adds the sale card between Monthly and Yearly, leaving both unchanged', async () => {
    await renderDuring();

    const cards = Array.from(container.querySelectorAll<HTMLElement>('[data-slot="card"]'));
    expect(cards.map((card) => card.id)).toEqual(['', 'sale', '']);
    expect(cards[0].textContent).toContain(MONTHLY_CARD);
    expect(cards[2].textContent).toContain(YEARLY_CARD);
    expect(cards[0].parentElement!.className.split(/\s+/)).toEqual(
      expect.arrayContaining(['grid', 'md:grid-cols-2', 'lg:grid-cols-3'])
    );
    expect(saleCard()!.className.split(/\s+/)).toEqual(
      expect.arrayContaining(['order-first', 'lg:order-0', 'md:col-span-2', 'lg:col-span-1'])
    );
    expect(saleCard()!.textContent).toContain('$3.99');
    expect(saleCard()!.textContent).toContain('$47.88 billed today for your first year');
    expect(saleCard()!.textContent).toContain('Renews at $69.99/year. Cancel anytime.');
    expect(saleCard()!.textContent).toContain('Ends in 2d 19h 0m');
    expect(planCard(MONTHLY_CARD).textContent).toContain('After trial: $6.99/month. Cancel anytime.');
    expect(planCard(YEARLY_CARD).textContent).toContain('After trial: $69.99/year. Cancel anytime.');
    expect(trackPromotionEvent).toHaveBeenCalledWith(BLACK_FRIDAY, 'offer_view', { source: 'direct', price: 47.88 });
  });

  it.each([
    ['before the sale starts', 'upcoming', new Date('2026-11-26T12:00:00Z')],
    ['after it ends', 'ended', new Date('2026-12-02T12:00:00Z')],
  ] as const)('shows the two usual cards %s', async (_label, answer, at) => {
    await renderDuring(answer, at);

    expect(saleCard()).toBeNull();
    expect(container.querySelectorAll('[data-slot="card"]')).toHaveLength(2);
  });

  it.each([
    ['a premium (paying or trialing) account', { plan: 'premium' }],
    ['an admin', { plan: 'admin' }],
  ])('offers no sale to %s', async (_label, profile) => {
    state.user = { id: 'user-1' };
    state.profile = profile;
    await renderDuring();

    expect(saleCard()).toBeNull();
  });

  it('offers no sale to a signed-in viewer whose profile did not load', async () => {
    state.user = { id: 'user-1' };
    state.profile = null;
    state.profileError = new Error('Could not load your subscription details');
    await renderDuring();

    expect(saleCard()).toBeNull();
  });

  it('offers no sale on a retained free profile once the profile fetch has failed', async () => {
    state.user = { id: 'user-1' };
    state.profile = { plan: 'free' };
    state.profileError = new Error('Could not load your subscription details');
    await renderDuring();

    expect(saleCard()).toBeNull();
  });

  it('offers the sale to a free account', async () => {
    state.user = { id: 'user-1' };
    state.profile = { plan: 'free' };
    await renderDuring();

    expect(saleCard()).not.toBeNull();
  });

  it('starts the sale checkout with its id and attribution, counted as yearly at the sale price', async () => {
    state.params = { campaign: 'black-friday-2026', source: 'banner' };
    window.sessionStorage.setItem('pitchrank_attribution', JSON.stringify({ utm_source: 'facebook' }));
    await renderDuring();

    await tap(saleCard()!.querySelector('button')!);

    expect(mockStartCheckout).toHaveBeenCalledWith('price_yearly_test', null, {
      promotion: 'black-friday-2026',
      attribution: { campaign: 'black-friday-2026', source: 'banner', utm_source: 'facebook' },
    });
    expect(trackPlanSelected).toHaveBeenCalledWith({ plan: 'yearly', price: 47.88, source: 'banner' });
    expect(trackCheckoutInitiated).toHaveBeenCalledWith({ plan: 'yearly', price: 47.88 });
    expect(trackPromotionEvent).toHaveBeenCalledWith(BLACK_FRIDAY, 'checkout_started', {
      source: 'banner',
      price: 47.88,
    });
  });

  it('sends the page source to Stripe and the checkout event alike when nothing recorded one', async () => {
    await renderDuring();

    await tap(saleCard()!.querySelector('button')!);

    expect(mockStartCheckout).toHaveBeenCalledWith('price_yearly_test', null, {
      promotion: 'black-friday-2026',
      attribution: { source: 'direct' },
    });
    expect(trackPromotionEvent).toHaveBeenCalledWith(BLACK_FRIDAY, 'checkout_started', {
      source: 'direct',
      price: 47.88,
    });
  });

  it("prefers this page's own campaign link over the session's first touch for the same key", async () => {
    window.sessionStorage.setItem('pitchrank_attribution', JSON.stringify({ source: 'email' }));
    state.params = { source: 'banner' };
    await renderDuring();

    expect(trackPromotionEvent).toHaveBeenCalledWith(BLACK_FRIDAY, 'offer_view', { source: 'banner', price: 47.88 });
  });

  it("counts the sale's view under the same source its checkout will name", async () => {
    window.sessionStorage.setItem('pitchrank_attribution', JSON.stringify({ source: 'banner' }));
    state.next = `/teams/${TEAM_ID}`;
    await renderDuring();

    expect(trackPromotionEvent).toHaveBeenCalledWith(BLACK_FRIDAY, 'offer_view', { source: 'banner', price: 47.88 });
  });

  it('names the sale under the tapped team', async () => {
    state.next = `/teams/${TEAM_ID}`;
    mockPreview.mockResolvedValue({ team_name: 'Phoenix Rising 2014', club_name: null, age: 12, gender: 'M' });
    await renderDuring();

    expect(container.textContent).toContain(BLACK_FRIDAY.copy.upgradeHeaderLine);
    expect(container.textContent).not.toContain('Start your free trial to open');
  });

  it('shows an admin the sale card in preview before it starts', async () => {
    window.history.replaceState(null, '', '/upgrade?promo_preview=1');
    state.user = { id: 'admin-1' };
    state.profile = { plan: 'admin' };
    await renderDuring('upcoming', new Date('2026-11-25T12:00:00Z'));

    expect(saleCard()).not.toBeNull();
  });

  it('shows no preview to a free account asking for one', async () => {
    window.history.replaceState(null, '', '/upgrade?promo_preview=1');
    state.user = { id: 'user-1' };
    state.profile = { plan: 'free' };
    await renderDuring('upcoming', new Date('2026-11-25T12:00:00Z'));

    expect(saleCard()).toBeNull();
  });

  describe('a campaign link', () => {
    const ended = () => container.querySelector('[role="status"]')?.textContent ?? null;

    it.each([
      ['after the sale ends', 'ended', new Date('2026-12-02T12:00:00Z')],
      ['once the kill switch is on', 'ended', DURING],
    ] as const)('says the sale has ended %s', async (_label, answer, at) => {
      state.params = { campaign: 'black-friday-2026' };
      await renderDuring(answer, at);

      expect(ended()).toBe('The Black Friday sale has ended.');
    });

    it('shows the normal page before the sale starts', async () => {
      state.params = { campaign: 'black-friday-2026' };
      await renderDuring('upcoming', new Date('2026-11-26T12:00:00Z'));

      expect(ended()).toBeNull();
      expect(saleCard()).toBeNull();
    });

    it('says nothing about a sale the link does not name', async () => {
      state.params = { campaign: 'spring-2027' };
      await renderDuring('ended', new Date('2026-12-02T12:00:00Z'));

      expect(ended()).toBeNull();
    });
  });
});
