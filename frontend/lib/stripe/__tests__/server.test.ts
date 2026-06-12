import { describe, it, expect } from 'vitest';
import type Stripe from 'stripe';
import { isSessionPaymentSettled } from '../server';

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
