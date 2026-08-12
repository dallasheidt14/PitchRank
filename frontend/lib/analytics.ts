/**
 * Google Analytics 4 helpers
 * Core utilities for tracking events and page views
 */

// gtag type is declared in types/gtag.d.ts

type GtagFn = NonNullable<Window['gtag']>;

/**
 * Resolve window.gtag, installing the standard shim when gtag.js has not loaded yet.
 *
 * gtag.js only replays dataLayer entries that are `arguments` objects — the shim it
 * installs pushes `arguments`, and a plain array is discarded without error. Queuing
 * through this shim keeps events fired before the script loads (page-view trackers on
 * mount) from being dropped; gtag.js replaces window.gtag and replays the queue on load.
 */
function ensureGtag(): GtagFn {
  const w = window as Window & { dataLayer?: unknown[] };

  if (typeof w.gtag !== 'function') {
    w.dataLayer = w.dataLayer || [];
    w.gtag = function gtag() {
      // eslint-disable-next-line prefer-rest-params
      (w.dataLayer as unknown[]).push(arguments);
    } as GtagFn;
  }

  return w.gtag as GtagFn;
}

/**
 * Send a custom event to Google Analytics 4.
 *
 * @param eventName - The name of the event (snake_case, no spaces)
 * @param eventParams - Optional parameters to send with the event
 */
export function gtagEvent(
  eventName: string,
  eventParams?: Record<string, string | number | boolean | null | undefined>
): void {
  if (typeof window === 'undefined' || process.env.NODE_ENV === 'development') {
    if (process.env.NODE_ENV === 'development') {
      console.log('[Analytics Event]', eventName, eventParams);
    }
    return;
  }

  const cleanParams = eventParams
    ? Object.fromEntries(Object.entries(eventParams).filter(([, value]) => value !== null && value !== undefined))
    : undefined;

  ensureGtag()('event', eventName, cleanParams);
}

/**
 * Track a page view in Google Analytics 4
 * Note: This is typically handled automatically by the GoogleAnalytics component,
 * but can be called manually for SPAs or custom page tracking.
 */
