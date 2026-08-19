'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import Script from 'next/script';
import { SECRET_QUERY_PARAMS, SECRET_QUERY_PATHS } from '@/lib/constants';
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
    if (!measurementId || process.env.NODE_ENV === 'development' || SECRET_QUERY_PATHS.includes(pathname)) {
      return;
    }

    const params = new URLSearchParams(searchParams);
    SECRET_QUERY_PARAMS.forEach((param) => params.delete(param));
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

  // Stripping the param from page_location is not enough on a SECRET_QUERY_PATHS
  // page: gtag.js lives in the document and re-reads location on history
  // navigations, so the tag must not load at all.
  if (!measurementId || process.env.NODE_ENV === 'development' || SECRET_QUERY_PATHS.includes(pathname)) {
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
          // GA4 derives page_location from document.location
          var sanitized = new URL(window.location.href);
          ${JSON.stringify([...SECRET_QUERY_PARAMS])}.forEach(function (p) { sanitized.searchParams.delete(p); });
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
