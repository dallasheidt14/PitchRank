import 'server-only';
import { createHash, randomBytes } from 'node:crypto';

/**
 * Proves a sign-in comes from the browser that started a guest checkout. The session id alone
 * is not enough: it sits in Stripe's hosted checkout URL, so it can travel to other people.
 */
export const CHECKOUT_BROWSER_COOKIE = 'checkout_browser';

const hashKey = (key: string) => createHash('sha256').update(key).digest('hex');

/** A fresh cookie for the browser, and the hash of its key to store on the Checkout Session. */
export function newCheckoutBrowserKey() {
  const key = randomBytes(32).toString('base64url');
  return {
    keyHash: hashKey(key),
    cookie: {
      name: CHECKOUT_BROWSER_COOKIE,
      value: key,
      httpOnly: true,
      secure: true,
      sameSite: 'lax' as const,
      path: '/api/stripe/checkout-login',
      // A Checkout Session stays open for at most a day.
      maxAge: 24 * 60 * 60,
    },
  };
}

/**
 * Whether `key`, from this browser's cookie, is the one whose hash was stored when checkout
 * started. A plain comparison is safe: what it could leak is the stored hash, which grants nothing
 * without the key behind it.
 */
export function isCheckoutBrowser(key: string | undefined, keyHash: string | undefined): boolean {
  if (!key || !keyHash) return false;
  return hashKey(key) === keyHash;
}
