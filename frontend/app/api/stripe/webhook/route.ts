import {
  stripe,
  WEBHOOK_EVENTS,
  extractPeriodEnd,
  mapStatusToPlan,
  updateUserProfile,
  isSessionPaymentSettled,
} from '@/lib/stripe/server';
import { getSupabaseAdmin } from '@/lib/supabase/service';
import { headers } from 'next/headers';
import { NextResponse } from 'next/server';
import Stripe from 'stripe';
import { notifyAdmin } from '@/lib/notifications/admin';
import {
  tagSubscriber,
  untagSubscriber,
  setLifecycle,
  setSubscriberCustomField,
  enrollInAutomation,
  type Lifecycle,
} from '@/lib/beehiiv';
import { sendPasswordSetupEmail } from '@/lib/email/password-setup';
import { sendReturningSubscriberEmail } from '@/lib/email/returning-subscriber';

// Escape HTML to prevent injection via Stripe-sourced strings (customer name/email)
const escapeHtml = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/**
 * Permanent errors that won't resolve on retry — return 200 so Stripe
 * stops retrying. Everything else returns 500 so Stripe retries.
 */
function isPermanentError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    msg.includes('No user profile found for Stripe customer') ||
    msg.includes('already been registered') ||
    msg.includes('already exists')
  );
}

/**
 * Read current subscription_status + cancel_at_period_end from user_profiles
 * BEFORE the webhook update overwrites them. Used to detect transitions
 * (trialing → active, canceling → reactivated, etc.) for Beehiiv routing.
 */
async function getPriorState(customerId: string): Promise<{ status: string | null; canceling: boolean }> {
  const { data } = await getSupabaseAdmin()
    .from('user_profiles')
    .select('subscription_status, cancel_at_period_end')
    .eq('stripe_customer_id', customerId)
    .maybeSingle();
  return {
    status: data?.subscription_status ?? null,
    canceling: data?.cancel_at_period_end ?? false,
  };
}

/**
 * Resolve a Stripe customer's email. Returns null if the customer was
 * deleted or the API call fails.
 */
async function getCustomerEmail(customerId: string): Promise<string | null> {
  try {
    const customer = await stripe.customers.retrieve(customerId);
    return (customer as Stripe.Customer).email ?? null;
  } catch (err) {
    console.warn(`[webhook] Failed to retrieve customer ${customerId}: ${err}`);
    return null;
  }
}

/**
 * Map each lifecycle state to the Vercel env var holding the Beehiiv
 * automation ID that should auto-enroll the subscriber on transition.
 * Missing env var = no enrollment (the automation hasn't been built yet);
 * setLifecycle still runs so segments and per-step gates work in the UI.
 */
const LIFECYCLE_AUTOMATION_ENV: Record<Lifecycle, string> = {
  lead: 'BEEHIIV_REPORT_CARD_AUTOMATION_ID',
  free_drip: 'BEEHIIV_FREE_DRIP_AUTOMATION_ID',
  trialing: 'BEEHIIV_TRIAL_AUTOMATION_ID',
  past_due: 'BEEHIIV_DUNNING_AUTOMATION_ID',
  canceling: 'BEEHIIV_CANCELING_AUTOMATION_ID',
  paid: 'BEEHIIV_PAID_AUTOMATION_ID',
  trial_canceled: 'BEEHIIV_TRIAL_CANCEL_AUTOMATION_ID',
  paid_canceled: 'BEEHIIV_PAID_CANCEL_AUTOMATION_ID',
};

/**
 * Enroll the subscriber in the Beehiiv automation matching this lifecycle
 * state, if one is configured. Non-fatal; safe to call before all the
 * downstream automations have been built (no env var = no-op).
 */
async function enrollInLifecycleAutomation(email: string, lifecycle: Lifecycle): Promise<void> {
  const automationId = process.env[LIFECYCLE_AUTOMATION_ENV[lifecycle]];
  if (!automationId) return;
  try {
    await enrollInAutomation(email, automationId);
  } catch (err) {
    console.error(`[webhook] enrollInAutomation(${lifecycle}) failed (non-fatal):`, err);
  }
}

/**
 * Set the Beehiiv lifecycle field for a customer by email AND enroll them
 * into the matching automation (if its env var is configured). Non-fatal —
 * Beehiiv errors are logged but don't fail the webhook (Stripe shouldn't
 * retry a successful state update just because an email tag failed).
 */
async function syncLifecycle(customerId: string, lifecycle: Lifecycle): Promise<void> {
  try {
    const email = await getCustomerEmail(customerId);
    if (!email) return;
    await setLifecycle(email, lifecycle);
    await enrollInLifecycleAutomation(email, lifecycle);
  } catch (err) {
    console.error(`[webhook] syncLifecycle(${lifecycle}) failed (non-fatal):`, err);
  }
}

export async function POST(req: Request) {
  const body = await req.text();
  const headersList = await headers();
  const sig = headersList.get('stripe-signature');

  if (!sig) {
    console.error('Missing stripe-signature header');
    return NextResponse.json({ error: 'Missing stripe-signature header' }, { status: 400 });
  }

  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET?.trim();
  if (!webhookSecret) {
    console.error('Missing STRIPE_WEBHOOK_SECRET environment variable');
    return NextResponse.json({ error: 'Webhook not configured' }, { status: 500 });
  }

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(body, sig, webhookSecret);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.error(`Webhook signature verification failed: ${message}`);
    return NextResponse.json({ error: 'Webhook signature verification failed' }, { status: 400 });
  }

  console.log(`[webhook] Received ${event.type} (${event.id})`);

  try {
    switch (event.type) {
      case WEBHOOK_EVENTS.CHECKOUT_COMPLETED: {
        const session = event.data.object as Stripe.Checkout.Session;
        await handleCheckoutCompleted(session);
        break;
      }

      // Async payment methods complete checkout with payment_status='unpaid';
      // fulfillment is skipped then and happens here once the payment settles
      case WEBHOOK_EVENTS.CHECKOUT_ASYNC_PAYMENT_SUCCEEDED: {
        const session = event.data.object as Stripe.Checkout.Session;
        await handleCheckoutCompleted(session);
        break;
      }

      // Terminal failure of a delayed payment. Nothing was provisioned (the
      // unpaid completed event was skipped), so no profile write is needed —
      // Stripe emails the customer; surface it for ops visibility
      case WEBHOOK_EVENTS.CHECKOUT_ASYNC_PAYMENT_FAILED: {
        const session = event.data.object as Stripe.Checkout.Session;
        console.warn(`[webhook] Async payment failed for session ${session.id} (customer ${session.customer})`);
        await notifyAdmin(
          `<b>Async payment failed</b>\nCheckout session ${escapeHtml(session.id)} — no access was granted.`
        );
        break;
      }

      case WEBHOOK_EVENTS.SUBSCRIPTION_UPDATED: {
        const subscription = event.data.object as Stripe.Subscription;
        await handleSubscriptionUpdated(subscription);
        break;
      }

      case WEBHOOK_EVENTS.SUBSCRIPTION_DELETED: {
        const subscription = event.data.object as Stripe.Subscription;
        await handleSubscriptionDeleted(subscription);
        break;
      }

      case WEBHOOK_EVENTS.INVOICE_PAID: {
        const invoice = event.data.object as Stripe.Invoice;
        await handleInvoicePaid(invoice);
        break;
      }

      case WEBHOOK_EVENTS.INVOICE_PAYMENT_FAILED: {
        const invoice = event.data.object as Stripe.Invoice;
        await handleInvoicePaymentFailed(invoice);
        break;
      }

      case WEBHOOK_EVENTS.TRIAL_WILL_END: {
        const subscription = event.data.object as Stripe.Subscription;
        await handleTrialWillEnd(subscription);
        break;
      }

      case WEBHOOK_EVENTS.CHARGE_REFUNDED: {
        const charge = event.data.object as Stripe.Charge;
        await handleChargeRefunded(charge);
        break;
      }

      default:
        console.log(`[webhook] Unhandled event type: ${event.type}`);
    }

    return NextResponse.json({ received: true });
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const errorStack = error instanceof Error ? error.stack : undefined;
    console.error(`[webhook] Handler error for ${event.type}: ${errorMessage}`);
    if (errorStack) console.error(errorStack);

    if (isPermanentError(error)) {
      // No matching user — retrying won't help. Acknowledge so Stripe stops.
      console.warn(`[webhook] Permanent error, returning 200 to stop retries`);
      return NextResponse.json({ received: true, error: 'Permanent webhook error' }, { status: 200 });
    }

    // Transient error (DB timeout, network issue) — return 500 so Stripe retries
    return NextResponse.json({ error: 'Webhook handler failed' }, { status: 500 });
  }
}

/**
 * Handle successful checkout - activate subscription.
 * Supports both authenticated checkouts (user already has a profile with
 * stripe_customer_id) and anonymous checkouts (no Supabase account yet).
 */
async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const customerId = session.customer as string;
  const subscriptionId = session.subscription as string;

  if (!customerId || !subscriptionId) {
    console.error('[webhook] Missing customer or subscription ID in checkout session');
    return;
  }

  // checkout.session.completed also fires for unpaid async payment methods;
  // only paid (or trialing, no_payment_required) sessions may activate premium
  if (!isSessionPaymentSettled(session)) {
    console.log(
      `[webhook] Checkout session ${session.id} completed with payment_status=${session.payment_status}; skipping fulfillment`
    );
    return;
  }

  // Fetch subscription details to get period end and status (may be "trialing" for free trials)
  const subscription = await stripe.subscriptions.retrieve(subscriptionId);

  const baseUpdates = {
    stripe_subscription_id: subscriptionId,
    subscription_status: subscription.status,
    plan: mapStatusToPlan(subscription.status),
    subscription_period_end: extractPeriodEnd(subscription),
    cancel_at_period_end: false,
  };

  // Check if a user profile already exists for this Stripe customer (authenticated
  // checkout). We also read subscription_status to detect webhook re-deliveries
  // (Stripe is at-least-once) and skip duplicate Beehiiv automation enrollments.
  const { data: existingProfile } = await getSupabaseAdmin()
    .from('user_profiles')
    .select('id, subscription_status')
    .eq('stripe_customer_id', customerId)
    .maybeSingle();
  const priorStatus: string | null = existingProfile?.subscription_status ?? null;

  let customer: Stripe.Customer | Stripe.DeletedCustomer;

  if (existingProfile) {
    // --- Authenticated checkout: profile exists, update it ---
    [, customer] = await Promise.all([
      updateUserProfile(getSupabaseAdmin(), customerId, baseUpdates),
      stripe.customers.retrieve(customerId),
    ]);
  } else {
    // --- Anonymous checkout: create or link Supabase account ---
    customer = await stripe.customers.retrieve(customerId);
    const email = (customer as Stripe.Customer).email;

    if (!email) {
      console.error('[webhook] Anonymous checkout but Stripe customer has no email');
      return;
    }

    const anonymousUpdates = { stripe_customer_id: customerId, ...baseUpdates };

    // Check if a user already exists with this email (signed up but checked out anonymously)
    const { data: profileByEmail } = await getSupabaseAdmin()
      .from('user_profiles')
      .select('id, stripe_customer_id, stripe_subscription_id')
      .eq('email', email)
      .maybeSingle();

    if (profileByEmail) {
      // Anonymous checkout always starts a 7-day trial (the email isn't known
      // until Stripe collects it), but trials are for first-time subscribers
      // only. Don't silently convert the promised trial into an immediate
      // charge — cancel the subscription (no invoice exists during a trial,
      // so nothing is charged), leave the profile untouched, and email them
      // to log in, where checkout offers monthly/annual without a trial.
      const hasBillingHistory = Boolean(profileByEmail.stripe_customer_id || profileByEmail.stripe_subscription_id);
      if (subscription.status === 'trialing' && hasBillingHistory) {
        await stripe.subscriptions.cancel(subscriptionId);
        console.log(
          `[webhook] Canceled anonymous trial for returning subscriber ${profileByEmail.id} (trial already used); sent re-subscribe email`
        );

        try {
          await sendReturningSubscriberEmail(email);
        } catch (emailError) {
          console.error('[webhook] Returning-subscriber email failed (non-fatal):', emailError);
        }

        await notifyAdmin(
          `<b>Returning subscriber blocked from second trial</b>\n` +
            `<b>Email:</b> ${escapeHtml(email)}\n` +
            `Anonymous trial checkout canceled (no charge); emailed log-in-and-resubscribe link.`
        );
        return;
      }

      // Existing account with no billing history (signed up but never
      // subscribed) — first trial is legitimate; link the subscription.
      await getSupabaseAdmin()
        .from('user_profiles')
        .update({ ...anonymousUpdates, updated_at: new Date().toISOString() })
        .eq('id', profileByEmail.id);

      await stripe.customers.update(customerId, {
        metadata: { supabase_user_id: profileByEmail.id },
      });

      console.log(`[webhook] Linked anonymous checkout to existing user ${profileByEmail.id}`);
    } else {
      // New user — create Supabase account
      const { data: newUser, error: createError } = await getSupabaseAdmin().auth.admin.createUser({
        email,
        email_confirm: true,
        user_metadata: { source: 'stripe_checkout' },
      });

      if (createError || !newUser?.user) {
        console.error('[webhook] Failed to create user for anonymous checkout:', createError);
        throw new Error(`Failed to create user for anonymous checkout: ${createError?.message}`);
      }

      // Update the profile created by handle_new_user trigger
      await getSupabaseAdmin()
        .from('user_profiles')
        .update({ ...anonymousUpdates, updated_at: new Date().toISOString() })
        .eq('id', newUser.user.id);

      // Link Stripe customer to the new Supabase user for future webhook lookups
      await stripe.customers.update(customerId, {
        metadata: { supabase_user_id: newUser.user.id },
      });

      console.log(`[webhook] Created new user ${newUser.user.id} for anonymous checkout`);

      // Send password-setup email. If it can't be delivered the customer has
      // no way to log in, so alert an admin to send a recovery link manually.
      // Non-fatal — the webhook still returns 200 so Stripe doesn't retry.
      const alertSetupFailed = (reason: string) =>
        notifyAdmin(
          `<b>⚠️ Set-password email FAILED</b>\n` +
            `New paid signup <b>${escapeHtml(email)}</b> could not be sent a set-password link ` +
            `(${reason}). They cannot log in — send them a recovery link manually.`
        );
      try {
        const { data: linkData } = await getSupabaseAdmin().auth.admin.generateLink({
          type: 'recovery',
          email,
          options: {
            redirectTo: `${process.env.NEXT_PUBLIC_SITE_URL}/auth/callback?next=/reset-password`,
          },
        });

        // Build the set-password link through our own callback via token_hash rather
        // than the PKCE action_link: a link opened on a different device than checkout
        // has no code_verifier cookie and would fall through to /login, stranding the
        // paying customer. The token_hash (verifyOtp) path works on any device.
        const hashedToken = linkData?.properties?.hashed_token;
        const setupUrl = hashedToken
          ? `${process.env.NEXT_PUBLIC_SITE_URL}/auth/callback?token_hash=${hashedToken}&type=recovery&next=/reset-password`
          : undefined;
        const sent = setupUrl ? await sendPasswordSetupEmail(email, setupUrl) : false;
        if (!setupUrl) {
          console.warn('[webhook] Could not generate password setup link');
        }
        if (!sent) {
          await alertSetupFailed(setupUrl ? 'email send failed' : 'no setup link generated');
        }
      } catch (emailError) {
        console.error('[webhook] Password setup email failed (non-fatal):', emailError);
        await alertSetupFailed('unexpected error');
      }
    }
  }

  console.log(`[webhook] Subscription activated for customer ${customerId}`);

  // Notify admin of new signup — escape HTML to prevent injection via Stripe customer name
  const displayName = escapeHtml((customer as Stripe.Customer).name ?? 'Unknown');
  const displayEmail = escapeHtml((customer as Stripe.Customer).email ?? 'N/A');
  const statusLabel = subscription.status === 'trialing' ? '🆓 Free Trial' : '💳 Paid';
  const interval = subscription.items.data[0]?.price?.recurring?.interval;
  const planLabel = interval === 'month' ? 'Premium Monthly' : 'Premium Annual';

  await notifyAdmin(
    `<b>New Signup!</b>\n` +
      `${statusLabel}\n` +
      `<b>Name:</b> ${displayName}\n` +
      `<b>Email:</b> ${displayEmail}\n` +
      `<b>Plan:</b> ${planLabel}\n` +
      `<b>Status:</b> ${subscription.status}`
  );

  // Sync Beehiiv: set tier to premium (gates paywall content), set lifecycle,
  // and enroll in the matching automation (Trial Onboarding for trialing,
  // Paid Drip for direct-to-paid). Each step is non-fatal.
  //
  // Idempotency: tagSubscriber + setLifecycle are upserts (same value = no
  // observable change), but enrollInAutomation creates a fresh journey on
  // every call. Skip enrollment when prior subscription_status already
  // matches the new one — that means this is a Stripe webhook re-delivery,
  // not a genuine state change.
  const rawEmail = (customer as Stripe.Customer).email;
  if (rawEmail) {
    try {
      await tagSubscriber(rawEmail);
      const lifecycle: Lifecycle = subscription.status === 'trialing' ? 'trialing' : 'paid';
      await setLifecycle(rawEmail, lifecycle);
      if (priorStatus !== subscription.status) {
        await enrollInLifecycleAutomation(rawEmail, lifecycle);
      } else {
        console.log(`[webhook] Skipping enrollment — already in status=${priorStatus} (webhook re-delivery)`);
      }
    } catch (tagError) {
      console.error('[webhook] Beehiiv sync failed (non-fatal):', tagError);
    }
  }
}

/**
 * Handle subscription updates (plan changes, renewals, cancellation intent)
 *
 * When a user cancels via Customer Portal, Stripe sets cancel_at_period_end=true
 * but keeps status as "active" until the period ends. We track this flag so the
 * dashboard can show the user as "canceling" rather than misleadingly "active".
 */
async function handleSubscriptionUpdated(subscription: Stripe.Subscription) {
  // Stripe delivers events at-least-once and out of order: a stale
  // subscription.updated (status=active) replayed after cancellation would
  // restore premium. Re-fetch so the write reflects the subscription's
  // current state, not the event payload's snapshot.
  const current = await stripe.subscriptions.retrieve(subscription.id);
  const customerId = current.customer as string;
  const status = current.status;
  const plan = mapStatusToPlan(status);
  const canceling = current.cancel_at_period_end ?? false;

  const prior = await getPriorState(customerId);

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    stripe_subscription_id: current.id,
    subscription_status: status,
    plan,
    subscription_period_end: extractPeriodEnd(current),
    cancel_at_period_end: canceling,
  });

  // Route Beehiiv on cancel-at-period-end / reactivation transitions
  if (canceling && !prior.canceling) {
    await syncLifecycle(customerId, 'canceling');
  } else if (!canceling && prior.canceling && status === 'active') {
    await syncLifecycle(customerId, 'paid');
  }

  const label = canceling ? `${status} (canceling at period end)` : status;
  console.log(`[webhook] Subscription updated for customer ${customerId}: ${label}`);
}

/**
 * Handle subscription cancellation
 */
async function handleSubscriptionDeleted(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;
  const prior = await getPriorState(customerId);

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    stripe_subscription_id: null,
    subscription_status: 'canceled',
    plan: 'free',
    subscription_period_end: null,
    cancel_at_period_end: false,
  });

  console.log(`[webhook] Subscription canceled for customer ${customerId} (prior status: ${prior.status})`);

  // Webhook re-delivery: prior.status is already 'canceled' from a previous
  // run of this handler. Skip Beehiiv writes — otherwise we'd mis-route to
  // paid_canceled (because the 'trialing' signal is gone) and re-enroll in
  // the win-back automation.
  if (prior.status === 'canceled' || prior.status === null) {
    console.log(`[webhook] Skipping Beehiiv sync — already canceled (webhook re-delivery)`);
    return;
  }

  // Remove premium tag in Beehiiv + route into Trial Cancel or Paid Win-Back
  // based on whether they were trialing or actively paying when canceled.
  try {
    const email = await getCustomerEmail(customerId);
    if (email) {
      await untagSubscriber(email);
      const lifecycle: Lifecycle = prior.status === 'trialing' ? 'trial_canceled' : 'paid_canceled';
      await setLifecycle(email, lifecycle);
      await enrollInLifecycleAutomation(email, lifecycle);
    }
  } catch (err) {
    console.warn(`[webhook] Failed to sync Beehiiv on cancel: ${err}`);
  }
}

/**
 * Handle successful invoice payment (subscription renewal)
 */
async function handleInvoicePaid(invoice: Stripe.Invoice) {
  const customerId = invoice.customer as string;
  // Get subscription ID - handle both new (dahlia+) and old (clover) API versions
  // New: invoice.parent.subscription_details.subscription
  // Old: invoice.subscription (top-level, removed in dahlia)
  const parentSub = invoice.parent?.subscription_details?.subscription;
  const legacySub = (invoice as unknown as Record<string, unknown>).subscription;
  const subscriptionId =
    (typeof parentSub === 'string'
      ? parentSub
      : typeof parentSub === 'object' && parentSub !== null
        ? (parentSub as { id: string }).id
        : null) ?? (typeof legacySub === 'string' ? legacySub : null);

  if (!subscriptionId) {
    // One-time payment, not a subscription
    return;
  }

  const prior = await getPriorState(customerId);

  // Fetch subscription to get updated period end
  const subscriptionData = await stripe.subscriptions.retrieve(subscriptionId);
  await updateUserProfile(getSupabaseAdmin(), customerId, {
    subscription_status: subscriptionData.status,
    plan: mapStatusToPlan(subscriptionData.status),
    subscription_period_end: extractPeriodEnd(subscriptionData),
    cancel_at_period_end: subscriptionData.cancel_at_period_end ?? false,
  });

  // Flip lifecycle to `paid` only on trial→paid or past_due→paid transitions.
  // Renewals (active → active) are no-ops so subscribers stay in Paid Drip
  // instead of re-entering it every billing cycle.
  if (subscriptionData.status === 'active' && (prior.status === 'trialing' || prior.status === 'past_due')) {
    await syncLifecycle(customerId, 'paid');
  }

  console.log(`[webhook] Invoice paid for customer ${customerId}`);
}

/**
 * Handle failed invoice payment
 */
async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  const customerId = invoice.customer as string;
  const prior = await getPriorState(customerId);

  console.log(`[webhook] Payment failed for customer ${customerId} (prior status: ${prior.status})`);

  // Re-delivery: prior subscription_status was already 'past_due' from an
  // earlier successful run. Skip the entire side-effect chain to avoid
  // duplicate Dunning enrollment.
  if (prior.status === 'past_due') {
    console.log(`[webhook] Skipping Dunning enrollment — already past_due (webhook re-delivery)`);
    return;
  }

  // Order matters:
  //   1. setSubscriberCustomField (last_failed_invoice_url) — must run BEFORE
  //      enrollment because Beehiiv automations triggered by enrollment
  //      render their first email at enrollment time. If the field is empty
  //      the dunning email falls back to the generic portal link.
  //   2. syncLifecycle — enrolls the subscriber in the Dunning automation.
  //   3. updateUserProfile (subscription_status='past_due') — commit LAST so
  //      it doubles as the dedup key for #797. If any earlier step fails or
  //      the request times out, the DB stays in the prior state and Stripe's
  //      retry runs the full flow again, instead of orphaning a `past_due`
  //      record that never got enrolled.
  const hostedUrl = invoice.hosted_invoice_url;
  if (hostedUrl) {
    try {
      const email = await getCustomerEmail(customerId);
      if (email) await setSubscriberCustomField(email, 'last_failed_invoice_url', hostedUrl);
    } catch (err) {
      console.error(`[webhook] Failed to set last_failed_invoice_url (non-fatal):`, err);
    }
  }

  await syncLifecycle(customerId, 'past_due');

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    subscription_status: 'past_due',
  });
}

/**
 * Backup signal fired ~3 days before a trial ends. The Beehiiv Trial
 * Onboarding automation handles day-5/6/7 reminder emails on its own
 * clock; this is observability + a future hook for engagement-based
 * routing if Beehiiv timing drifts.
 */
async function handleTrialWillEnd(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;
  console.log(`[webhook] Trial will end for customer ${customerId} (subscription ${subscription.id})`);
}

/**
 * Refund means money back to the customer — route into the Paid Win-Back
 * sequence regardless of whether the underlying subscription was also canceled.
 */
async function handleChargeRefunded(charge: Stripe.Charge) {
  const customerId = charge.customer as string;
  if (!customerId) {
    console.log('[webhook] Charge refunded without a customer (guest checkout); skipping');
    return;
  }
  // charge.refunded fires for partial refunds too, but is only true when the
  // charge is fully refunded — a partial refund leaves the subscriber active
  if (!charge.refunded) {
    console.log(`[webhook] Partial refund for customer ${customerId} (charge ${charge.id}); lifecycle unchanged`);
    return;
  }
  console.log(`[webhook] Charge refunded for customer ${customerId} (charge ${charge.id})`);
  await syncLifecycle(customerId, 'paid_canceled');
}
