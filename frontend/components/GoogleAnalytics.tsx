'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import Script from 'next/script';
import { useEffect } from 'react';

interface GoogleAnalyticsProps {
  measurementId?: string;
}

// Declare gtag function for TypeScript
declare global {
  interface Window {
    gtag?: (
      command: string,
      targetId: string,
      config?: Record<string, unknown>
    ) => void;
  }
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
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Track page views on route change
  useEffect(() => {
    if (!measurementId || process.env.NODE_ENV === 'development') {
      return;
    }

    // Construct full URL with search params
    const url = searchParams?.toString()
      ? `${pathname}?${searchParams.toString()}`
      : pathname;

    // Send pageview event to GA4
    if (window.gtag) {
      window.gtag('config', measurementId, {
        page_path: url,
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
