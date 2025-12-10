"use client";

/**
 * Client-side helper to initiate Stripe checkout
 * Redirects user to Stripe's hosted checkout page
 */
export async function startCheckout(priceId: string): Promise<void> {
  const res = await fetch("/api/stripe/checkout", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ priceId }),
  });

  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || "Failed to create checkout session");
  }

  const data = await res.json();

  if (!data.url) {
    throw new Error("No checkout URL returned");
  }

  // Redirect to Stripe Checkout
  window.location.href = data.url;
}

/**
 * Client-side helper to open Stripe Customer Portal
 * Allows users to manage their subscription (cancel, update payment, etc.)
 */
export async function openCustomerPortal(): Promise<void> {
  const res = await fetch("/api/stripe/portal", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.error || "Failed to create portal session");
  }

  const data = await res.json();

  if (!data.url) {
    throw new Error("No portal URL returned");
  }

  // Redirect to Stripe Customer Portal
  window.location.href = data.url;
}
