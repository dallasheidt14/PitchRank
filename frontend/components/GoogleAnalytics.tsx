'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import Script from 'next/script';
import { useEffect, Suspense } from 'react';

interface GoogleAnalyticsProps {
  measurementId?: string;
}

// gtag type is declared in lib/analytics.ts

/**
 * Google Analytics component (internal - uses useSearchParams)
 * Must be wrapped in Suspense when used
 */
function GoogleAnalyticsContent({ measurementId }: GoogleAnalyticsProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Track page views on route change
  useEffect(() => {
    if (!measurementId || process.env.NODE_ENV === 'development') {
      return;
    }

    // Construct full URL with search params. session_id is the bearer secret
    // for /api/stripe/sync — never report it off-origin.
    const params = new URLSearchParams(searchParams);
    params.delete('session_id');
    const url = params.toString() ? `${pathname}?${params.toString()}` : pathname;

    // Send pageview event to GA4. page_location must be pinned too — GA4
    // otherwise derives it from document.location, re-leaking stripped params
    if (window.gtag) {
      window.gtag('config', measurementId, {
        page_path: url,
        page_location: `${window.location.origin}${url}`,
      });
    }
  }, [pathname, searchParams, measurementId]);

  // Don't render in development or if no measurement ID is provided
  if (!measurementId || process.env.NODE_ENV === 'development') {
    return null;
  }

  return (
    <>
      {/* Global Site Tag (gtag.js) - Google Analytics */}
      <Script src={`https://www.googletagmanager.com/gtag/js?id=${measurementId}`} strategy="afterInteractive" />
      <Script id="google-analytics" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          // Strip session_id (the /api/stripe/sync bearer secret) before the
          // initial pageview — GA4 derives page_location from document.location
          var sanitized = new URL(window.location.href);
          sanitized.searchParams.delete('session_id');
          gtag('config', '${measurementId}', {
            page_path: window.location.pathname,
            page_location: sanitized.toString(),
          });
        `}
      </Script>
    </>
  );
}

/**
 * Google Analytics component
 * Add to root layout to track page views and user behavior
 *
 * Features:
 * - Tracks initial page views
 * - Tracks client-side navigation (SPA routing)
 * - Auto-disabled in development mode
 *
 * Usage:
 * 1. Get a Google Analytics 4 (GA4) property ID from https://analytics.google.com
 * 2. Set NEXT_PUBLIC_GA_MEASUREMENT_ID environment variable (e.g., G-XXXXXXXXXX)
 * 3. Component will automatically initialize when measurementId is provided
 */
export function GoogleAnalytics({ measurementId }: GoogleAnalyticsProps) {
  // Don't render in development or if no measurement ID is provided
  if (!measurementId || process.env.NODE_ENV === 'development') {
    return null;
  }

  return (
    <Suspense fallback={null}>
      <GoogleAnalyticsContent measurementId={measurementId} />
    </Suspense>
  );
}
