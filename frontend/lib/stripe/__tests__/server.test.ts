import { describe, it, expect } from 'vitest';
import type Stripe from 'stripe';
import { makeStripeSubscription } from '@/test/fixtures';
import { isCancellationScheduled, isSessionPaymentSettled } from '../server';

const session = (payment_status: string) => ({ payment_status }) as Stripe.Checkout.Session;

describe('isSessionPaymentSettled', () => {
  it('settles on paid', () => {
    expect(isSessionPaymentSettled(session('paid'))).toBe(true);
  });

  it('settles on no_payment_required (trial)', () => {
    expect(isSessionPaymentSettled(session('no_payment_required'))).toBe(true);
  });

  it('does not settle on unpaid (async pending or failed)', () => {
    expect(isSessionPaymentSettled(session('unpaid'))).toBe(false);
  });
});

describe('isCancellationScheduled', () => {
  const PERIOD_END = 1798761600;

  it('reads a cancellation scheduled through cancel_at alone', () => {
    expect(isCancellationScheduled(makeStripeSubscription({ cancelAt: PERIOD_END }))).toBe(true);
  });

  it('reads a cancellation scheduled through cancel_at_period_end alone', () => {
    expect(isCancellationScheduled(makeStripeSubscription({ cancelAtPeriodEnd: true }))).toBe(true);
  });

  it('is false for a subscription with neither set', () => {
    expect(isCancellationScheduled(makeStripeSubscription())).toBe(false);
  });

  it('applies to trials and past-due subscriptions too', () => {
    expect(isCancellationScheduled(makeStripeSubscription({ status: 'trialing', cancelAt: PERIOD_END }))).toBe(true);
    expect(isCancellationScheduled(makeStripeSubscription({ status: 'past_due', cancelAt: PERIOD_END }))).toBe(true);
  });

  it.each(['canceled', 'unpaid', 'paused'] as const)(
    'is false for a %s subscription, which no longer grants premium',
    (status) => {
      expect(isCancellationScheduled(makeStripeSubscription({ status, cancelAt: PERIOD_END }))).toBe(false);
      expect(isCancellationScheduled(makeStripeSubscription({ status, cancelAtPeriodEnd: true }))).toBe(false);
    }
  );
});
