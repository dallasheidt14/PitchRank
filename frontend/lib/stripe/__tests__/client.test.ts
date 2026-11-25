import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { startCheckout } from '../client';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: () => Promise.resolve({ url: 'https://checkout.stripe.com/x' }) });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function postedBody() {
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('/api/stripe/checkout');
  return JSON.parse(init.body);
}

describe('startCheckout', () => {
  it('posts the sale id and the attribution beside the price', async () => {
    await startCheckout('price_yearly', '/teams/abc', {
      promotion: 'black-friday-2026',
      attribution: { campaign: 'black-friday-2026', source: 'banner', utm_source: 'facebook' },
    });

    expect(postedBody()).toEqual({
      priceId: 'price_yearly',
      next: '/teams/abc',
      promotion: 'black-friday-2026',
      attribution: { campaign: 'black-friday-2026', source: 'banner', utm_source: 'facebook' },
    });
  });

  it('posts only the price and destination for a standard checkout', async () => {
    await startCheckout('price_monthly');

    expect(postedBody()).toEqual({ priceId: 'price_monthly', next: null });
  });

  it("shows the server's refusal", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ error: 'The Black Friday sale has ended.' }),
    });

    await expect(startCheckout('price_yearly', null, { promotion: 'black-friday-2026' })).rejects.toThrow(
      'The Black Friday sale has ended.'
    );
  });
});
