'use client';

import type { Attribution } from '@/lib/attribution';

/**
 * Client-side helper to initiate Stripe checkout
 * Redirects user to Stripe's hosted checkout page
 *
 * `promotion` asks for a sale; the server alone decides whether it is live and applies the coupon.
 */
export async function startCheckout(
  priceId: string,
  next: string | null = null,
  options: { promotion?: string; attribution?: Attribution } = {}
): Promise<void> {
  const res = await fetch('/api/stripe/checkout', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ priceId, next, promotion: options.promotion, attribution: options.attribution }),
  });

  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || 'Failed to create checkout session');
  }

  const data = await res.json();

  if (!data.url) {
    throw new Error('No checkout URL returned');
  }

  // Redirect to Stripe Checkout
  window.location.href = data.url;
}
