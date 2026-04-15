/**
 * Google Analytics 4 helpers
 * Core utilities for tracking events and page views
 */

// gtag type is declared in types/gtag.d.ts

/**
 * Send a custom event to Google Analytics 4.
 *
 * Pushes directly to window.dataLayer so events emitted before the gtag script
 * finishes loading are still captured (dataLayer is initialized by GoogleAnalytics
 * before the script tag; gtag replays the queue on load).
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

  // Ensure dataLayer exists — GoogleAnalytics component initializes it, but guard
  // against the event firing before the Script tag has mounted.
  const w = window as Window & { dataLayer?: unknown[] };
  w.dataLayer = w.dataLayer || [];
  // Mirrors the shape gtag('event', name, params) pushes.
  w.dataLayer.push(['event', eventName, cleanParams]);
}

/**
 * Track a page view in Google Analytics 4
 * Note: This is typically handled automatically by the GoogleAnalytics component,
 * but can be called manually for SPAs or custom page tracking.
 */
