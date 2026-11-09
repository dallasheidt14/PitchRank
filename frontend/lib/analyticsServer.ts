import 'server-only';

const COLLECT_URL = 'https://www.google-analytics.com/mp/collect';
const TIMEOUT_MS = 3000;
const GA_COOKIE = /^GA\d+\.\d+\.(\d{1,20}\.\d{1,20})$/;

/** The client id inside a `_ga` cookie such as `GA1.1.123456789.1700000000`. */
export function gaClientIdFromCookie(cookie: string | undefined): string | null {
  return GA_COOKIE.exec(cookie ?? '')?.[1] ?? null;
}

/**
 * For a buyer with no readable `_ga` cookie: two positive numbers, the format Google documents.
 * Google calls an event valid only under an id gtag.js has used, so GA may drop these.
 */
function throwawayClientId(): string {
  return `${Math.floor(Math.random() * 2147483647) + 1}.${Math.floor(Date.now() / 1000)}`;
}

/**
 * Sent from the server because the tag never loads on the page a buyer returns to (SECRET_QUERY_PATHS).
 * Never throws, so analytics cannot fail a Stripe webhook.
 */
export async function sendSubscriptionCompleted(clientId: string | undefined): Promise<void> {
  if (process.env.NODE_ENV === 'development') return;

  const measurementId = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID?.trim();
  const apiSecret = process.env.GA_API_SECRET?.trim();

  if (!measurementId || !apiSecret) {
    console.warn('subscription_completed not sent: NEXT_PUBLIC_GA_MEASUREMENT_ID or GA_API_SECRET not set');
    return;
  }

  const query = new URLSearchParams({ measurement_id: measurementId, api_secret: apiSecret });

  try {
    const res = await fetch(`${COLLECT_URL}?${query}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: clientId || throwawayClientId(),
        events: [{ name: 'subscription_completed' }],
      }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) console.warn('subscription_completed not sent: status', res.status);
  } catch (error) {
    // Only the error's name: its message can carry the request URL, which holds the secret.
    console.warn('subscription_completed not sent:', error instanceof Error ? error.name : 'unknown error');
  }
}
