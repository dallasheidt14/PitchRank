import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { gaClientIdFromCookie, sendSubscriptionCompleted } from './analyticsServer';

const fetchMock = vi.fn();

function sentRequest() {
  const [url, init] = fetchMock.mock.calls[0];
  return { url: new URL(url), body: JSON.parse(init.body), init };
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, status: 204 });
  vi.stubGlobal('fetch', fetchMock);
  vi.stubEnv('NEXT_PUBLIC_GA_MEASUREMENT_ID', 'G-TEST');
  vi.stubEnv('GA_API_SECRET', 'secret-value');
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('gaClientIdFromCookie', () => {
  it('reads the client id out of a _ga cookie', () => {
    expect(gaClientIdFromCookie('GA1.1.123456789.1700000000')).toBe('123456789.1700000000');
    expect(gaClientIdFromCookie('GA1.2.987.654')).toBe('987.654');
  });

  it.each([
    [undefined],
    [''],
    ['123456789.1700000000'],
    ['GA1.1.abc.def'],
    ['GA1.1.1.2.extra'],
    [`GA1.1.${'1'.repeat(21)}.2`],
  ])('finds no client id in %s', (cookie) => {
    expect(gaClientIdFromCookie(cookie)).toBeNull();
  });
});

describe('sendSubscriptionCompleted', () => {
  it('sends the event for that visitor to the Measurement Protocol endpoint', async () => {
    await sendSubscriptionCompleted('123.456');

    const { url, body, init } = sentRequest();
    expect(init.method).toBe('POST');
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(url.origin + url.pathname).toBe('https://www.google-analytics.com/mp/collect');
    expect(url.searchParams.get('measurement_id')).toBe('G-TEST');
    expect(url.searchParams.get('api_secret')).toBe('secret-value');
    expect(body.client_id).toBe('123.456');
    expect(body.events.map((event: { name: string }) => event.name)).toEqual(['subscription_completed']);
  });

  it('still sends the event for a buyer with no analytics cookie, under a throwaway id', async () => {
    await sendSubscriptionCompleted(undefined);

    expect(sentRequest().body.client_id).toMatch(/^[1-9]\d*\.[1-9]\d*$/);
  });

  it.each([['GA_API_SECRET'], ['NEXT_PUBLIC_GA_MEASUREMENT_ID']])('sends nothing when %s is not set', async (name) => {
    vi.stubEnv(name, '');

    await sendSubscriptionCompleted('123.456');

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('sends nothing from a development server', async () => {
    vi.stubEnv('NODE_ENV', 'development');

    await sendSubscriptionCompleted('123.456');

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('logs the status when Google refuses the request', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 403 });

    await sendSubscriptionCompleted('123.456');

    expect(vi.mocked(console.warn).mock.calls).toEqual([['subscription_completed not sent: status', 403]]);
  });

  it('does not throw when the request fails, and keeps the secret out of the log', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed for ...?api_secret=secret-value'));

    await expect(sendSubscriptionCompleted('123.456')).resolves.toBeUndefined();

    expect(vi.mocked(console.warn).mock.calls).toEqual([['subscription_completed not sent:', 'TypeError']]);
  });
});
