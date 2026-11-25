import {
  stripe,
  WEBHOOK_EVENTS,
  extractPeriodEnd,
  mapStatusToPlan,
  isCancellationScheduled,
  updateUserProfile,
  isSessionPaymentSettled,
} from '@/lib/stripe/server';
import { safeTeamPath } from '@/lib/auth/emailTokens';
import { getSupabaseAdmin } from '@/lib/supabase/service';
import { sanitizeAttribution } from '@/lib/attribution';
import { LIVE_SUBSCRIPTION_STATUSES, hasPremiumPlan, isStandardRefusedStatus } from '@/lib/plan';
import { findPromotionById, promotionEventName, type Promotion } from '@/lib/promotions';
import { headers } from 'next/headers';
import { NextResponse } from 'next/server';
import Stripe from 'stripe';
import { notifyAdmin } from '@/lib/notifications/admin';
import { sendServerEvent, sendSubscriptionCompleted } from '@/lib/analyticsServer';
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
import { sendDuplicateSubscriptionEmail } from '@/lib/email/duplicate-subscription';
import { sendDuplicatePurchaseEmail } from '@/lib/email/duplicate-purchase';

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

/**
 * Every live subscription on a customer, for the owner's refund decision. One page of 100 per status
 * holds them all; `limit: 1` would answer only the sale itself.
 */
async function listLiveSubscriptions(customerId: string): Promise<Stripe.Subscription[]> {
  const lists = await Promise.all(
    LIVE_SUBSCRIPTION_STATUSES.map((status) => stripe.subscriptions.list({ customer: customerId, status, limit: 100 }))
  );
  return lists.flatMap((list) => list.data);
}

interface MatchedProfile {
  id: string;
  plan: string | null;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
}

const MATCHED_PROFILE_COLUMNS = 'id, plan, stripe_customer_id, stripe_subscription_id, subscription_status';

type UnlinkedReason = 'duplicate' | 'no_email' | 'account_exists_unlinked';

const UNLINKED_REASON_TEXT: Record<UnlinkedReason, string> = {
  duplicate: 'This buyer already holds Premium.',
  no_email: 'The Stripe customer has no email, so no account could be found or created.',
  account_exists_unlinked: 'A PitchRank login already uses this email, but no profile with it holds this subscription.',
};

const SAME_CUSTOMER_BEEHIIV_STEPS =
  "After refunding, set this subscriber's newsletter lifecycle back to paid, re-add the premium tag and remove " +
  'them from the win-back automation; reconcile restores premium within 6 hours.';

function formatMoney(cents: number | null | undefined, currency: string | null | undefined): string {
  return cents == null ? 'amount unknown' : `${(cents / 100).toFixed(2)} ${(currency ?? '').toUpperCase()}`.trim();
}

function describeSubscription(subscription: Stripe.Subscription, matchedProfile: MatchedProfile | null): string {
  const customerId = typeof subscription.customer === 'string' ? subscription.customer : subscription.customer.id;
  const price = subscription.items.data[0]?.price;
  const interval = price?.recurring?.interval ? `/${price.recurring.interval}` : '';
  const pointedAt =
    matchedProfile?.stripe_subscription_id === subscription.id
      ? `profile ${matchedProfile.id} points here`
      : 'no profile points here';
  return (
    `• ${escapeHtml(subscription.id)} (${subscription.status}) on ${escapeHtml(customerId)}, created ` +
    `${new Date(subscription.created * 1000).toISOString()}, ${formatMoney(price?.unit_amount, price?.currency)}${interval}, ${pointedAt}`
  );
}

/**
 * A paid sale checkout this handler leaves unlinked. The owner links or refunds it by hand, so the
 * alert lists every live subscription involved and names none to refund: when two sit on one
 * customer, the sync route may already have pointed the profile at either.
 *
 * The error line backs up the Telegram alert, which is best-effort.
 */
async function alertUnlinkedPaidCheckout({
  reason,
  session,
  subscriptions,
  matchedProfile,
  email,
  sameCustomer = false,
  buyerNotice,
}: {
  reason: UnlinkedReason;
  session: Stripe.Checkout.Session;
  subscriptions: Stripe.Subscription[];
  matchedProfile: MatchedProfile | null;
  email: string | null;
  sameCustomer?: boolean;
  buyerNotice?: string;
}): Promise<void> {
  console.error('[webhook] PAID_CHECKOUT_NOT_LINKED', {
    reason,
    subscriptionId: session.subscription,
    customerId: session.customer,
  });
  const profileLine = matchedProfile
    ? `profile ${escapeHtml(matchedProfile.id)} (plan ${escapeHtml(matchedProfile.plan ?? 'none')}, customer ${escapeHtml(matchedProfile.stripe_customer_id ?? 'none')})`
    : 'none';
  await notifyAdmin(
    `<b>⚠️ Paid checkout not linked: ${reason}</b>\n` +
      `${UNLINKED_REASON_TEXT[reason]}\n` +
      `<b>Email:</b> ${escapeHtml(email ?? 'none')}\n` +
      `<b>Matched:</b> ${profileLine}\n` +
      `<b>Checkout total:</b> ${formatMoney(session.amount_total, session.currency)}\n` +
      `<b>Live subscriptions involved:</b>\n` +
      subscriptions.map((subscription) => describeSubscription(subscription, matchedProfile)).join('\n') +
      `\nNothing was changed. Decide in Stripe which, if any, to refund.` +
      (buyerNotice ? `\n${buyerNotice}` : '') +
      (sameCustomer ? `\n${SAME_CUSTOMER_BEEHIIV_STEPS}` : '')
  );
}

type LinkState = Pick<MatchedProfile, 'stripe_customer_id' | 'stripe_subscription_id'>;

/**
 * Writes only while the row still holds the Stripe customer and subscription the caller read, and
 * reports whether it did, so a writer that linked the row first keeps it. A failed update throws, so
 * Stripe retries.
 */
async function writeProfileById(
  profileId: string,
  updates: Record<string, unknown>,
  read: LinkState
): Promise<boolean> {
  let write = getSupabaseAdmin()
    .from('user_profiles')
    .update({ ...updates, updated_at: new Date().toISOString() })
    .eq('id', profileId);
  for (const column of ['stripe_customer_id', 'stripe_subscription_id'] as const) {
    const value = read[column];
    // `.eq(column, null)` never matches a NULL in PostgREST; `.is` does.
    write = value === null ? write.is(column, null) : write.eq(column, value);
  }
  const { data, error } = await write.select('id');
  if (error) throw new Error(`profile write failed: ${error.message}`);
  return Boolean(data && data.length > 0);
}

const WRITE_MATCHED_NO_ROW = 'profile write matched no row';

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

      case WEBHOOK_EVENTS.CHECKOUT_SESSION_EXPIRED: {
        const session = event.data.object as Stripe.Checkout.Session;
        await handleCheckoutExpired(session);
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

  // A sale always charges, so every sale checkout either links its subscription or reaches the owner.
  // A cancelled one is almost always a re-delivery after the owner refunded a duplicate: it is still
  // refused, since linking it would demote the account it duplicated, but it alerts no one again.
  const saleSession = Boolean(session.metadata?.promotion);
  const alertable = saleSession && subscription.status !== 'canceled';
  const ignoredDuplicate = `[webhook] Ignored re-delivered duplicate sale ${subscriptionId} (already cancelled)`;

  const baseUpdates = {
    stripe_subscription_id: subscriptionId,
    subscription_status: subscription.status,
    plan: mapStatusToPlan(subscription.status),
    subscription_period_end: extractPeriodEnd(subscription),
    cancel_at_period_end: isCancellationScheduled(subscription),
  };

  // Check if a user profile already exists for this Stripe customer (authenticated
  // checkout). We also read subscription_status to detect webhook re-deliveries
  // (Stripe is at-least-once) and skip duplicate Beehiiv automation enrollments.
  const { data: existingProfile, error: existingProfileError } = await getSupabaseAdmin()
    .from('user_profiles')
    .select(MATCHED_PROFILE_COLUMNS)
    .eq('stripe_customer_id', customerId)
    .maybeSingle();
  // Read as "no profile", a failed lookup would send a linked buyer down the signed-out path, where
  // their own premium row looks like a duplicate. Throwing makes Stripe retry instead.
  if (existingProfileError) throw new Error(`profile lookup failed: ${existingProfileError.message}`);
  const priorStatus: string | null = existingProfile?.subscription_status ?? null;

  let customer: Stripe.Customer | Stripe.DeletedCustomer;

  if (existingProfile) {
    if (saleSession) {
      const others = (await listLiveSubscriptions(customerId)).filter((s) => s.id !== subscriptionId);
      if (others.length > 0) {
        if (alertable) {
          const buyer = await stripe.customers.retrieve(customerId);
          await rejectDuplicatePurchase({
            session,
            email: normalizeEmail((buyer as Stripe.Customer).email),
            subscriptions: [subscription, ...others],
            matchedProfile: existingProfile,
            sameCustomer: true,
          });
        } else {
          console.log(ignoredDuplicate);
        }
        return;
      }
    }

    // --- Authenticated checkout: profile exists, update it ---
    [, customer] = await Promise.all([
      updateUserProfile(getSupabaseAdmin(), customerId, baseUpdates),
      stripe.customers.retrieve(customerId),
    ]);
  } else {
    // --- Anonymous checkout: create or link Supabase account ---
    customer = await stripe.customers.retrieve(customerId);
    const email = normalizeEmail((customer as Stripe.Customer).email);

    if (!email) {
      console.error('[webhook] Anonymous checkout but Stripe customer has no email');
      if (alertable) {
        await alertUnlinkedPaidCheckout({
          reason: 'no_email',
          session,
          subscriptions: [subscription],
          matchedProfile: null,
          email: null,
        });
      }
      return;
    }

    const anonymousUpdates = { stripe_customer_id: customerId, ...baseUpdates };

    // Check if a user already exists with this email (signed up but checked out anonymously)
    const { data: profileByEmail, error: profileByEmailError } = await getSupabaseAdmin()
      .from('user_profiles')
      .select(MATCHED_PROFILE_COLUMNS)
      .eq('email', email)
      .maybeSingle();
    if (profileByEmailError) throw new Error(`profile lookup failed: ${profileByEmailError.message}`);
    // A concurrent delivery of this checkout linked the profile between the two lookups. Judged as a
    // returning subscriber, it would have its own trial cancelled.
    if (profileByEmail?.stripe_subscription_id === subscriptionId) {
      console.log(`[webhook] Checkout ${subscriptionId} already linked by a concurrent delivery`);
      return;
    }

    if (saleSession) {
      const otherCustomerId =
        profileByEmail?.stripe_customer_id && profileByEmail.stripe_customer_id !== customerId
          ? profileByEmail.stripe_customer_id
          : null;
      const [onThisCustomer, onOtherCustomer] = await Promise.all([
        listLiveSubscriptions(customerId),
        otherCustomerId ? listLiveSubscriptions(otherCustomerId) : Promise.resolve([]),
      ]);
      const othersOnThisCustomer = onThisCustomer.filter((s) => s.id !== subscriptionId);
      // Comped and admin accounts hold Premium with no live Stripe subscription. An admin row must
      // never be overwritten to premium by the owner buying while signed out.
      const premiumPlanElsewhere =
        profileByEmail !== null &&
        hasPremiumPlan(profileByEmail.plan) &&
        profileByEmail.stripe_customer_id !== customerId;
      if (othersOnThisCustomer.length > 0 || onOtherCustomer.length > 0 || premiumPlanElsewhere) {
        if (alertable) {
          await rejectDuplicatePurchase({
            session,
            email,
            subscriptions: [subscription, ...othersOnThisCustomer, ...onOtherCustomer],
            matchedProfile: profileByEmail,
            sameCustomer: othersOnThisCustomer.length > 0,
          });
        } else {
          console.log(ignoredDuplicate);
        }
        return;
      }
    }

    if (profileByEmail) {
      // A standard signed-out checkout always trials, since the email is unknown until Stripe collects
      // it (a sale never trials), but trials are for first-time subscribers. Rather than turn the
      // trial into a charge, cancel it (its $0 invoice charged nothing), leave the profile untouched,
      // and email the buyer.
      const hasBillingHistory = Boolean(profileByEmail.stripe_customer_id || profileByEmail.stripe_subscription_id);
      // A comped or admin account holds Premium with no Stripe billing at all. Anyone can type its
      // email into a signed-out checkout, so linking that checkout would hand the account to a
      // stranger's trial, and to free when the trial lapses.
      const compedAccount = !hasBillingHistory && hasPremiumPlan(profileByEmail.plan);
      if (subscription.status === 'trialing' && (hasBillingHistory || compedAccount)) {
        // Telling a comped account, or one whose subscription the checkout route would refuse, to log
        // in and re-subscribe dead-ends. past_due is not refused — mapStatusToPlan calls it premium to
        // hold access open during payment retries, but /upgrade still accepts it, so an unrecovered
        // account keeps the re-subscribe path that can actually fix its billing.
        const alreadySubscribed = compedAccount || isStandardRefusedStatus(profileByEmail.subscription_status);

        const blocked = alreadySubscribed
          ? {
              send: sendDuplicateSubscriptionEmail,
              log: `Canceled duplicate anonymous trial for ${profileByEmail.id} (account already holds Premium); set-password email`,
              title: 'Duplicate checkout blocked',
              detail: 'Second anonymous trial canceled (no charge); the account already holds Premium',
              link: 'set-password link',
            }
          : {
              send: sendReturningSubscriberEmail,
              log: `Canceled anonymous trial for returning subscriber ${profileByEmail.id} (trial already used); re-subscribe email`,
              title: 'Returning subscriber blocked from second trial',
              detail: 'Anonymous trial checkout canceled (no charge)',
              link: 'log-in-and-resubscribe link',
            };

        await stripe.subscriptions.cancel(subscriptionId);

        let emailed = false;
        try {
          emailed = await blocked.send(email);
        } catch (emailError) {
          console.error('[webhook] Blocked-checkout email failed (non-fatal):', emailError);
        }
        console.log(`[webhook] ${blocked.log} ${emailed ? 'sent' : 'not sent'}`);

        await notifyAdmin(
          `<b>${blocked.title}</b>\n` +
            `<b>Email:</b> ${escapeHtml(email)}\n` +
            `${blocked.detail}; ` +
            (emailed ? `emailed ${blocked.link}.` : '<b>the email to the buyer did not send</b>: tell them yourself.')
        );
        return;
      }

      // A re-delivered checkout that was blocked above now reads as canceled. Linking it
      // would overwrite the subscription this account already has, or demote a comped one.
      if ((hasBillingHistory && baseUpdates.plan !== 'premium') || compedAccount) {
        console.warn(
          `[webhook] Ignored ${subscription.status} checkout for ${compedAccount ? 'comped' : 'billed'} account ${profileByEmail.id}`
        );
        return;
      }

      // A never-billed account, or a past subscriber whose checkout started
      // with no trial: link the subscription.
      // A miss means another writer got there first: Stripe's retry is judged against the row it left.
      if (!(await writeProfileById(profileByEmail.id, anonymousUpdates, profileByEmail))) {
        throw new Error(WRITE_MATCHED_NO_ROW);
      }

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
        // Written at creation, so an account whose webhook fails partway still gets the set-password
        // reminders that scripts/check_stuck_signups.py sends.
        app_metadata: { anonymous_checkout: true },
      });

      if (createError || !newUser?.user) {
        // The login exists but no profile carries this email (its profile has another one), or a
        // concurrent delivery won the race. Either way a paid sale must not end silently.
        if (saleSession && createError?.code === 'email_exists') {
          const { data: reread, error: rereadError } = await getSupabaseAdmin()
            .from('user_profiles')
            .select(MATCHED_PROFILE_COLUMNS)
            .eq('email', email)
            .maybeSingle();
          if (rereadError) throw new Error(`profile lookup failed: ${rereadError.message}`);
          if (reread?.stripe_subscription_id === subscriptionId) {
            console.log(`[webhook] Checkout ${subscriptionId} already linked by a concurrent delivery`);
            return;
          }
          // A concurrent delivery created this login moments ago and has not linked it yet. The retry
          // finds it linked, or a free profile to link, instead of alerting over a purchase in progress.
          if (reread && !reread.stripe_subscription_id) {
            throw new Error(`profile for checkout ${subscriptionId} is being linked by a concurrent delivery`);
          }
          if (alertable) {
            await alertUnlinkedPaidCheckout({
              reason: 'account_exists_unlinked',
              session,
              subscriptions: [subscription],
              matchedProfile: reread,
              email,
            });
          }
          return;
        }
        console.error('[webhook] Failed to create user for anonymous checkout:', createError);
        throw new Error(`Failed to create user for anonymous checkout: ${createError?.message}`);
      }

      // Update the profile created by handle_new_user trigger, which holds no Stripe ids yet. A twin
      // delivery of this checkout can find that empty profile by email and link it first. The
      // set-password email and sign-in marker below are sent only from here, so this delivery still
      // goes on to send them; any other writer makes it retry.
      const linked = await writeProfileById(newUser.user.id, anonymousUpdates, {
        stripe_customer_id: null,
        stripe_subscription_id: null,
      });
      if (!linked) {
        const { data: current, error: currentError } = await getSupabaseAdmin()
          .from('user_profiles')
          .select('stripe_subscription_id')
          .eq('id', newUser.user.id)
          .maybeSingle();
        if (currentError) throw new Error(`profile lookup failed: ${currentError.message}`);
        if (current?.stripe_subscription_id !== subscriptionId) throw new Error(WRITE_MATCHED_NO_ROW);
      }

      // Link Stripe customer to the new Supabase user for future webhook lookups
      await stripe.customers.update(customerId, {
        metadata: { supabase_user_id: newUser.user.id },
      });

      console.log(`[webhook] Created new user ${newUser.user.id} for anonymous checkout`);

      // Send password-setup email. If it can't be delivered, a buyer who isn't
      // signed in on return has no link to log in with, so alert an admin to
      // send a recovery link manually.
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
            redirectTo: `${process.env.NEXT_PUBLIC_SITE_URL}/auth/confirm?next=/reset-password`,
          },
        });

        // Build the set-password link through our own token_hash flow rather than the
        // PKCE action_link: a link opened on a different device than checkout has no
        // code_verifier cookie and would fall through to /login, stranding the paying
        // customer. The token_hash (verifyOtp) path works on any device. Point it at
        // /auth/confirm, which redeems only on a button press — a mail scanner's GET
        // of this link must not spend the token.
        const hashedToken = linkData?.properties?.hashed_token;
        const setupUrl = hashedToken
          ? `${process.env.NEXT_PUBLIC_SITE_URL}/auth/confirm?token_hash=${hashedToken}&type=recovery&next=/reset-password`
          : undefined;
        const sent = setupUrl ? await sendPasswordSetupEmail(email, setupUrl) : false;
        if (!setupUrl) {
          console.error('[webhook] Could not generate password setup link');
        }
        if (!sent) {
          await alertSetupFailed(setupUrl ? 'email send failed' : 'no setup link generated');
        }
      } catch (emailError) {
        console.error('[webhook] Password setup email failed (non-fatal):', emailError);
        await alertSetupFailed('unexpected error');
      }

      // This marker is what lets /api/stripe/checkout-login sign the buyer in. It comes after the
      // email because both links share one token slot: a sign-in minted first would be overwritten.
      const returnTo = safeTeamPath(session.metadata?.return_to);
      const { error: markError } = await getSupabaseAdmin().auth.admin.updateUserById(newUser.user.id, {
        app_metadata: { checkout_session_id: session.id, ...(returnTo ? { return_to: returnTo } : {}) },
      });
      if (markError) {
        console.error('[webhook] Could not mark the new account for sign-in on return:', markError.code);
      }

      // The twin that linked this checkout sends the signup notice, the newsletter steps and the purchase
      // event below; only the set-password email and the marker fall to this delivery.
      if (!linked) return;
    }
  }

  console.log(`[webhook] Subscription activated for customer ${customerId}`);

  if (baseUpdates.plan === 'premium') {
    await sendSubscriptionCompleted(session.metadata?.ga_client_id);
  }

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
      // A late checkout event can find the paid subscription already set to
      // cancel; it stores that flag, so it must also route the matching lifecycle.
      const lifecycle: Lifecycle =
        subscription.status === 'trialing' ? 'trialing' : baseUpdates.cancel_at_period_end ? 'canceling' : 'paid';
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

  // Last, after every write: a throw anywhere above makes Stripe retry before this was ever sent.
  // There is no dedupe beyond that, so transaction_id lets a count be made distinct.
  const promotion = salePromotion(session);
  if (promotion && baseUpdates.plan === 'premium') {
    const charged =
      session.amount_total != null && session.currency
        ? { value: session.amount_total / 100, currency: session.currency.toUpperCase() }
        : {};
    await sendServerEvent(session.metadata?.ga_client_id, promotionEventName(promotion, 'purchase_completed'), {
      transaction_id: subscriptionId,
      ...charged,
      ...saleEventParams(session, promotion),
      ...sanitizeAttribution(session.metadata),
    });
  }
}

function salePromotion(session: Stripe.Checkout.Session): Promotion | null {
  return session.metadata?.promotion ? findPromotionById(session.metadata.promotion) : null;
}

function saleEventParams(session: Stripe.Checkout.Session, promotion: Promotion): Record<string, string> {
  return {
    promotion_id: promotion.id,
    ...(session.metadata?.segment ? { segment: session.metadata.segment } : {}),
  };
}

/** Stripe keeps the case the buyer typed; stored profile emails, and auth logins, are lowercase. */
function normalizeEmail(email: string | null | undefined): string | null {
  return email?.trim().toLowerCase() || null;
}

/**
 * A paid sale purchase by someone who already holds Premium. Nothing about their account changes;
 * the owner refunds the purchase by hand, and the buyer is told so.
 */
async function rejectDuplicatePurchase({
  email,
  ...alert
}: {
  session: Stripe.Checkout.Session;
  email: string | null;
  subscriptions: Stripe.Subscription[];
  matchedProfile: MatchedProfile | null;
  sameCustomer: boolean;
}): Promise<void> {
  // Sent first, so the owner's alert can say whether the buyer was told.
  const buyerEmailed = email ? await sendDuplicatePurchaseEmail(email) : false;
  await alertUnlinkedPaidCheckout({
    reason: 'duplicate',
    email,
    buyerNotice: buyerEmailed
      ? 'The buyer was emailed that this purchase will be refunded within one business day.'
      : '<b>The refund email to the buyer did not send</b>: tell them yourself.',
    ...alert,
  });
}

/** A sale checkout left unpaid until Stripe closed it, counted beside the sale's other funnel steps. */
async function handleCheckoutExpired(session: Stripe.Checkout.Session) {
  const promotion = salePromotion(session);
  if (!promotion) return;
  await sendServerEvent(
    session.metadata?.ga_client_id,
    promotionEventName(promotion, 'checkout_expired'),
    saleEventParams(session, promotion)
  );
}

/**
 * Handle subscription updates (plan changes, renewals, cancellation intent)
 *
 * A scheduled cancellation keeps the subscription live until it ends; the stored
 * flag lets the admin dashboard and Beehiiv routing tell a canceling subscriber
 * from an active one.
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
  const canceling = isCancellationScheduled(current);

  const prior = await getPriorState(customerId);

  await updateUserProfile(getSupabaseAdmin(), customerId, {
    stripe_subscription_id: current.id,
    subscription_status: status,
    plan,
    subscription_period_end: extractPeriodEnd(current),
    cancel_at_period_end: canceling,
  });

  // Route Beehiiv on canceling / reactivation transitions. The canceling
  // sequence is for active subscribers only (not trials or past_due); a
  // canceled trial is routed to trial_canceled when it ends.
  if (canceling && !prior.canceling && status === 'active') {
    await syncLifecycle(customerId, 'canceling');
  } else if (!canceling && prior.canceling && status === 'active') {
    await syncLifecycle(customerId, 'paid');
  }

  const label = canceling ? `${status} (canceling)` : status;
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
  // A refund on a customer no profile holds (a duplicate bought signed out) is skipped: routing it
  // would put a paying subscriber's email into the win-back sequence. A same-customer duplicate is
  // still routed; its alert tells the owner how to undo that.
  const { data: linkedProfile, error: linkedProfileError } = await getSupabaseAdmin()
    .from('user_profiles')
    .select('id')
    .eq('stripe_customer_id', customerId)
    .maybeSingle();
  if (linkedProfileError) throw new Error(`profile lookup failed: ${linkedProfileError.message}`);
  if (!linkedProfile) {
    console.log(
      `[webhook] Refund for customer ${customerId} no profile holds (charge ${charge.id}); lifecycle unchanged`
    );
    return;
  }
  console.log(`[webhook] Charge refunded for customer ${customerId} (charge ${charge.id})`);
  await syncLifecycle(customerId, 'paid_canceled');
}
