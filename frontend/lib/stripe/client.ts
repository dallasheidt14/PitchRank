'use client';

/**
 * Client-side helper to initiate Stripe checkout
 * Redirects user to Stripe's hosted checkout page
 */
export async function startCheckout(priceId: string): Promise<void> {
  const res = await fetch('/api/stripe/checkout', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ priceId }),
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
