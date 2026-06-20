'use client';

import { usePathname } from 'next/navigation';
import Script from 'next/script';

interface GoogleAdsProps {
  conversionId?: string;
}

// gtag type is declared in types/gtag.d.ts

// Skip the post-checkout page: its URL carries the Stripe session_id bearer
// secret, and gtag auto-reports document.location. Tracking resumes on the next
// navigation. The payment/sync flow is untouched.
const SESSION_SECRET_PATH = '/upgrade/success';

/**
 * Google Ads remarketing tag
 * Add to root layout to build remarketing audiences
 *
 * Reuses the gtag.js library that GoogleAnalytics already loads — when GA is
 * configured this only pushes a second gtag('config', 'AW-…') to the shared
 * dataLayer. When GA is absent it self-loads gtag.js so the tag still fires.
 *
 * Usage:
 * 1. Get a remarketing conversion ID from https://ads.google.com (Audiences/Tag)
 * 2. Set NEXT_PUBLIC_GOOGLE_ADS_CONVERSION_ID environment variable (e.g., AW-XXXXXXXXX)
 * 3. Component will automatically initialize when conversionId is provided
 */
export function GoogleAds({ conversionId }: GoogleAdsProps) {
  const pathname = usePathname();

  // Don't render in development, without a conversion ID, or on the post-checkout page.
  // The exact path match is leak-safe only under Next's default trailingSlash: it
  // 308-redirects `/upgrade/success/` and usePathname() returns the stripped path.
  // Flipping trailingSlash:true would require normalizing this guard.
  if (!conversionId || process.env.NODE_ENV === 'development' || pathname === SESSION_SECRET_PATH) {
    return null;
  }

  // GoogleAnalytics loads gtag.js and calls gtag('js') when GA is configured.
  // Only self-load the library (and call gtag('js')) when GA is absent.
  const gaLoaded = Boolean(process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID);

  return (
    <>
      {!gaLoaded && (
        <Script src={`https://www.googletagmanager.com/gtag/js?id=${conversionId}`} strategy="afterInteractive" />
      )}
      <Script id="google-ads" strategy="afterInteractive">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          ${gaLoaded ? '' : "gtag('js', new Date());"}
          gtag('config', '${conversionId}');
        `}
      </Script>
    </>
  );
}
