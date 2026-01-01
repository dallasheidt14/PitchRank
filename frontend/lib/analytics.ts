/**
 * Google Analytics 4 helpers
 * Core utilities for tracking events and page views
 * Includes AI search referral tracking for 2026 optimization
 */

// gtag type is declared in types/gtag.d.ts

/**
 * AI Search Platform Referrers
 * Used to identify traffic from AI search engines and assistants
 */
export const AI_REFERRERS = {
  chatgpt: ['chat.openai.com', 'chatgpt.com'],
  perplexity: ['perplexity.ai', 'www.perplexity.ai'],
  claude: ['claude.ai', 'www.claude.ai'],
  gemini: ['gemini.google.com', 'bard.google.com'],
  copilot: ['copilot.microsoft.com', 'bing.com/chat'],
  you: ['you.com'],
  phind: ['phind.com', 'www.phind.com'],
} as const;

export type AIReferrerSource = keyof typeof AI_REFERRERS;

/**
 * Detect if the referrer is from an AI search platform
 * @returns The AI platform name or null if not from AI
 */
export function detectAIReferrer(): AIReferrerSource | null {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return null;
  }

  const referrer = document.referrer.toLowerCase();
  if (!referrer) return null;

  for (const [platform, domains] of Object.entries(AI_REFERRERS)) {
    if (domains.some((domain) => referrer.includes(domain))) {
      return platform as AIReferrerSource;
    }
  }

  return null;
}

/**
 * Track AI referral source on page load
 * Call this once on initial page load to capture AI traffic source
 */
export function trackAIReferral(): void {
  const aiSource = detectAIReferrer();
  if (aiSource) {
    gtagEvent('ai_referral', {
      ai_platform: aiSource,
      referrer_url: document.referrer,
      landing_page: window.location.pathname,
    });

    // Also set as user property for cohort analysis
    if (typeof window !== 'undefined' && window.gtag) {
      window.gtag('set', 'user_properties', {
        ai_traffic_source: aiSource,
      });
    }
  }
}

/**
 * Check if analytics is available and not in development mode
 */
function isAnalyticsEnabled(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.gtag === 'function' &&
    process.env.NODE_ENV !== 'development'
  );
}

/**
 * Send a custom event to Google Analytics 4
 *
 * @param eventName - The name of the event (snake_case, no spaces)
 * @param eventParams - Optional parameters to send with the event
 *
 * @example
 * gtagEvent('team_row_clicked', { team_id: '123', team_name: 'Rangers' });
 */
export function gtagEvent(
  eventName: string,
  eventParams?: Record<string, string | number | boolean | null | undefined>
): void {
  if (!isAnalyticsEnabled()) {
    // Log in development for debugging
    if (process.env.NODE_ENV === 'development') {
      console.log('[Analytics Event]', eventName, eventParams);
    }
    return;
  }

  // Filter out null/undefined values from params
  const cleanParams = eventParams
    ? Object.fromEntries(
        Object.entries(eventParams).filter(
          ([, value]) => value !== null && value !== undefined
        )
      )
    : undefined;

  window.gtag!('event', eventName, cleanParams);
}

/**
 * Track a page view in Google Analytics 4
 * Note: This is typically handled automatically by the GoogleAnalytics component,
 * but can be called manually for SPAs or custom page tracking.
 *
 * @param url - The URL/path to track
 * @param title - Optional page title
 *
 * @example
 * gtagPageView('/teams/123', 'Team Details - Rangers');
 */
export function gtagPageView(url: string, title?: string): void {
  if (!isAnalyticsEnabled()) {
    if (process.env.NODE_ENV === 'development') {
      console.log('[Analytics PageView]', url, title);
    }
    return;
  }

  const measurementId = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID;
  if (!measurementId) return;

  window.gtag!('config', measurementId, {
    page_path: url,
    ...(title && { page_title: title }),
  });
}
