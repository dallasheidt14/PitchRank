'use client';

import { usePathname } from 'next/navigation';
import Script from 'next/script';

interface MetaPixelProps {
  pixelId?: string;
}

// Stripe appends the session_id bearer secret to this URL on the post-checkout
// redirect, and the Pixel auto-reports document.location — so the tag is skipped
// on this page (a fresh full page load from Stripe). Tracking resumes on the next
// navigation. The payment/sync flow is untouched.
const SESSION_SECRET_PATH = '/upgrade/success';

/**
 * Meta Pixel component
 * Add to root layout to build remarketing audiences
 *
 * fbevents.js auto-tracks SPA route changes (it hooks history.pushState), so no
 * manual route-change handler is needed.
 *
 * Usage:
 * 1. Get a Meta Pixel ID from https://business.facebook.com (Events Manager → Data Sources)
 * 2. Set NEXT_PUBLIC_META_PIXEL_ID environment variable
 * 3. Component will automatically initialize when pixelId is provided
 */
export function MetaPixel({ pixelId }: MetaPixelProps) {
  const pathname = usePathname();

  // Don't render in development, without a pixel ID, or on the post-checkout page.
  // The exact path match is leak-safe only under Next's default trailingSlash: it
  // 308-redirects `/upgrade/success/` and usePathname() returns the stripped path.
  // Flipping trailingSlash:true would require normalizing this guard.
  if (!pixelId || process.env.NODE_ENV === 'development' || pathname === SESSION_SECRET_PATH) {
    return null;
  }

  return (
    <Script id="meta-pixel" strategy="afterInteractive">
      {`
        !function(f,b,e,v,n,t,s)
        {if(f.fbq)return;n=f.fbq=function(){n.callMethod?
        n.callMethod.apply(n,arguments):n.queue.push(arguments)};
        if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
        n.queue=[];t=b.createElement(e);t.async=!0;
        t.src=v;s=b.getElementsByTagName(e)[0];
        s.parentNode.insertBefore(t,s)}(window, document,'script',
        'https://connect.facebook.net/en_US/fbevents.js');
        fbq('init', '${pixelId}');
        fbq('track', 'PageView');
      `}
    </Script>
  );
}
