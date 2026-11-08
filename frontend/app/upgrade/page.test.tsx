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
    state: { next: null as string | null },
  };
});

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(state.next ? { next: state.next } : {}),
}));
vi.mock('@/hooks/useUser', () => ({ useUser: () => ({ user: null, isLoading: false }) }));
vi.mock('@/lib/events', () => ({
  trackUpgradePageViewed: vi.fn(),
  trackPlanSelected: vi.fn(),
  trackCheckoutInitiated: vi.fn(),
}));
vi.mock('@/lib/stripe/client', () => ({ startCheckout: mockStartCheckout }));
vi.mock('@/lib/api', () => ({
  api: {
    getDbStats: () => Promise.resolve({ totalTeams: 0, totalGames: 0 }),
    getPaywallTeamPreview: mockPreview,
  },
}));

import UpgradePage from './page';

let container: HTMLDivElement;
let root: Root;

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
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
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
    expect(mockStartCheckout).toHaveBeenCalledWith('price_monthly_test');
    expect(cardClasses(YEARLY_CARD)).toContain('ring-2');
  });

  it("starts Yearly from Yearly's own button while Monthly is selected, leaving the selection alone", async () => {
    await render();
    await tap(planCard(MONTHLY_CARD));
    await tap(planCard(YEARLY_CARD).querySelector('button')!);
    expect(mockStartCheckout).toHaveBeenCalledTimes(1);
    expect(mockStartCheckout).toHaveBeenCalledWith('price_yearly_test');
    expect(cardClasses(MONTHLY_CARD)).toContain('ring-2');
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
