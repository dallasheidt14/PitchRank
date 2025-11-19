'use client';

import Script from 'next/script';

interface GoogleAnalyticsProps {
  measurementId?: string;
}

/**
 * Google Analytics component
 * Add to root layout to track page views and user behavior
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
    <>
      {/* Global Site Tag (gtag.js) - Google Analytics */}
      <Script
        src={`https://www.googletagmanager.com/gtag/js?id=${measurementId}`}
        strategy="afterInteractive"
      />
      <Script id="google-analytics" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          gtag('config', '${measurementId}', {
            page_path: window.location.pathname,
          });
        `}
      </Script>
    </>
  );
}
