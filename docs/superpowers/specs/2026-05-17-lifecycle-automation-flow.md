# PitchRank Email Lifecycle Automation Spec

**Date:** 2026-05-17
**Owner:** Dallas Heidt
**Status:** Design — not yet implemented

## 1. Goal

Replace the single `/report-card` Beehiiv automation with a full lifecycle funnel that routes subscribers through state-appropriate nurture, conversion, retention, and win-back sequences. Source of truth for state is the Stripe webhook; Beehiiv is the delivery surface.

## 2. Entry points (only two)

All subscribers enter the funnel via one of:

1. **Report Card form** (`POST /api/reports/team-card`) → enters Report-Card Nurture
2. **Stripe checkout completed with `status = trialing`** → enters Trial Onboarding

Every other automation is downstream — no other entry triggers.

## 3. Data model

Add a single Beehiiv custom field on subscribers:

| Field | Values | Set by |
|---|---|---|
| `lifecycle` | `lead`, `free_drip`, `trialing`, `past_due`, `canceling`, `paid`, `trial_canceled`, `paid_canceled` | Stripe webhook + report-card API |

Keep the existing `tier` field (Free / Premium) — it's used by Beehiiv's native paywall on newsletter content. `lifecycle` is the routing key for automations.

### State transitions

| From → To | Trigger |
|---|---|
| `(none)` → `lead` | report-card form submit |
| `lead` → `free_drip` | Report-Card Nurture completes (last step) |
| `lead | free_drip | trial_canceled | paid_canceled` → `trialing` | `checkout.session.completed` with `subscription.status = trialing` |
| `(none)` → `paid` | `checkout.session.completed` with `subscription.status = active` (direct-to-paid, no trial) |
| `trialing` → `paid` | First `invoice.paid` after trial conversion (status flips trialing → active) |
| `paid` → `past_due` | `invoice.payment_failed` |
| `past_due` → `paid` | `invoice.paid` after retry success |
| `paid` → `canceling` | `customer.subscription.updated` with `cancel_at_period_end = true` |
| `canceling` → `paid` | `customer.subscription.updated` with `cancel_at_period_end = false` (reactivation) |
| `trialing` → `trial_canceled` | `customer.subscription.deleted` while prior status was `trialing` |
| `paid | canceling | past_due` → `paid_canceled` | `customer.subscription.deleted` while prior status was `active/past_due` |
| `paid | trialing` → `paid_canceled` | `charge.refunded` |

## 4. Automation graph

```
ENTRY 1: /report-card             ENTRY 2: Stripe checkout (trialing)
  │                                 │
  ▼                                 ▼
┌────────────────────┐         ┌──────────────────────┐
│ Report-Card        │         │ Trial Onboarding     │
│ Nurture (7 emails) │         │ (7 emails, 7 days)   │
│ trigger: API       │         │ trigger:             │
│ per-step gate:     │         │   lifecycle becomes  │
│   lifecycle=lead   │         │   trialing           │
│ last step:         │         │ per-step gate:       │
│   set lifecycle=   │         │   lifecycle=trialing │
│   free_drip        │         │                      │
└──────────┬─────────┘         └────┬───────────────┬─┘
           │                        │               │
           │ converts to trial      │ converts      │ cancels
           │ (re-enters via         │ to paid       │ during trial
           │  trialing trigger)     │               │
           │                        ▼               ▼
           ▼               ┌────────────────┐  ┌──────────────┐
┌────────────────────┐     │ Paid Drip      │  │ Trial Cancel │
│ Non-Premium Drip   │     │ trigger:       │  │ Drip         │
│ trigger:           │     │   lifecycle    │  │ trigger:     │
│   completes        │     │   becomes paid │  │   lifecycle  │
│   Report-Card +    │     │ per-step gate: │  │   becomes    │
│   lifecycle=       │     │   lifecycle in │  │   trial_     │
│   free_drip        │     │   (paid,       │  │   canceled   │
│ ongoing nurture    │     │   canceling)   │  │ 3-5 emails   │
└──────────┬─────────┘     └───────┬────────┘  └──────┬───────┘
           │                       │                  │ last step:
           │                       │ cancels          │   set lifecycle
           │                       ▼                  │   = free_drip
           │              ┌──────────────────┐        │   (re-enters
           │              │ Paid Win-Back    │        │    Non-Premium
           │              │ trigger:         │        │    Drip via
           │              │   lifecycle      │        │    its trigger)
           │              │   becomes        │        │
           │              │   paid_canceled  │        │
           │              │ 5 emails over    │        │
           │              │   30 days        │        │
           │              └────────┬─────────┘        │
           │                       │                  │
           └───────────────────────┴──────────────────┘
                                resub anywhere
                                → Trial Onboarding
```

Plus two utility automations not on the main graph:

- **Dunning / Update Card** — trigger: `lifecycle becomes past_due`. 3 emails over Stripe's ~21-day retry window. Exits on `lifecycle becomes paid`.
- **Cancellation Save** — trigger: `lifecycle becomes canceling`. 1-2 emails before period ends. Exits on `lifecycle becomes paid`.

### How triggers actually fire (implementation note)

Beehiiv on Scale plan does NOT recalculate dynamic segments in real time
(refreshes once daily). Segment-based triggers would delay Trial Onboarding's
Email 1 by up to 24h — unacceptable for a 7-day trial. Instead, every
lifecycle automation uses the **`Added by API`** trigger, and the Stripe
webhook calls Beehiiv's automation-enrollment endpoint directly the moment
state transitions, giving sub-second routing latency.

Each lifecycle state maps to a Vercel env var holding the automation ID:

| lifecycle | env var | required? |
|---|---|---|
| `lead` | `BEEHIIV_REPORT_CARD_AUTOMATION_ID` | already set |
| `free_drip` | `BEEHIIV_FREE_DRIP_AUTOMATION_ID` | set when Non-Premium Drip is built |
| `trialing` | `BEEHIIV_TRIAL_AUTOMATION_ID` | set when Trial Onboarding is built |
| `past_due` | `BEEHIIV_DUNNING_AUTOMATION_ID` | set when Dunning is built |
| `canceling` | `BEEHIIV_CANCELING_AUTOMATION_ID` | set when Cancellation Save is built |
| `paid` | `BEEHIIV_PAID_AUTOMATION_ID` | set when Paid Drip is built |
| `trial_canceled` | `BEEHIIV_TRIAL_CANCEL_AUTOMATION_ID` | set when Trial Cancel Drip is built |
| `paid_canceled` | `BEEHIIV_PAID_CANCEL_AUTOMATION_ID` | set when Paid Win-Back is built |

The webhook's `enrollInLifecycleAutomation()` helper reads `LIFECYCLE_AUTOMATION_ENV[lifecycle]` and no-ops when the env var is unset — so new automations come online by setting an env var, no code change required.

Per-step `Conditions` on every Send Email node (filter: `lifecycle is <state>`)
remain the in-flight gate that skips subscribers whose state changes mid-sequence.

## 5. Gaps from prior sketch — addressed here

| # | Gap | Solution |
|---|---|---|
| 1 | Payment failure (past_due) silently loses money | Dunning automation triggered by `lifecycle becomes past_due` |
| 2 | Cancel-at-period-end save window | `canceling` state + Cancellation Save automation |
| 3 | `invoice.paid` fires on every renewal | Webhook only flips `lifecycle` to `paid` if prior was `trialing` or `past_due`; no-op otherwise |
| 4 | Refunds not handled | New `charge.refunded` webhook handler → `lifecycle = paid_canceled` |
| 5 | Returning customers | Deferred — let them re-enter Trial Onboarding; revisit if data shows it's hurting conversion |
| 6 | Direct-to-paid (no trial) | Webhook distinguishes `status = active` vs `trialing` on checkout completion |
| 7 | Long-dormant free_drip users | Add Beehiiv engagement-based exit: `last_opened > 90 days` → unsubscribe |
| 8 | Tier vs lifecycle drift | Documented: only Stripe webhook + report-card API write `lifecycle`. No manual Beehiiv UI edits. |
| 9 | Multiple subs per customer | Out of scope until team plans exist |
| 10 | Report-card drop-off (stuck in `lead`) | Report-Card Nurture's final step unconditionally sets `lifecycle = free_drip`, so even unfinished sequences land somewhere |

## 6. Code changes

### 6.1 `frontend/lib/beehiiv.ts` — add `setLifecycle`

```typescript
export type Lifecycle =
  | 'lead'
  | 'free_drip'
  | 'trialing'
  | 'past_due'
  | 'canceling'
  | 'paid'
  | 'trial_canceled'
  | 'paid_canceled';

/**
 * Set the `lifecycle` custom field on a Beehiiv subscriber.
 * Used by the Stripe webhook + report-card API to route subscribers
 * into the right automation funnel. No-op if subscriber doesn't exist.
 */
export async function setLifecycle(email: string, lifecycle: Lifecycle): Promise<boolean> {
  const { apiKey, pubId } = getConfig();
  if (!apiKey || !pubId) return false;

  const subscriberId = await findSubscriberId(email);
  if (!subscriberId) {
    console.warn(`[beehiiv] setLifecycle: no subscriber for ${email}`);
    return false;
  }

  const resp = await fetch(`${BEEHIIV_API_URL}/publications/${pubId}/subscriptions/${subscriberId}`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      custom_fields: [{ name: 'lifecycle', value: lifecycle }],
    }),
  });

  if (!resp.ok) {
    console.warn(`[beehiiv] setLifecycle failed (${resp.status}): ${await resp.text()}`);
    return false;
  }

  console.log(`[beehiiv] Set lifecycle=${lifecycle} for ${email}`);
  return true;
}
```

Also extend `subscribeFreeLead` to write `lifecycle = lead` in its custom_fields array.

### 6.2 `frontend/app/api/stripe/webhook/route.ts` — wire lifecycle into handlers

**Add a helper** to read prior status before update:

```typescript
async function getPriorStatus(customerId: string): Promise<string | null> {
  const { data } = await getSupabaseAdmin()
    .from('user_profiles')
    .select('subscription_status')
    .eq('stripe_customer_id', customerId)
    .maybeSingle();
  return data?.subscription_status ?? null;
}
```

**Update `handleCheckoutCompleted`** (after the existing `tagSubscriber` call):

```typescript
const rawEmail = (customer as Stripe.Customer).email;
if (rawEmail) {
  try {
    await tagSubscriber(rawEmail);
    // NEW: route to Trial Onboarding or Paid Drip based on subscription status
    await setLifecycle(rawEmail, subscription.status === 'trialing' ? 'trialing' : 'paid');
  } catch (tagError) {
    console.error('[webhook] Beehiiv update failed (non-fatal):', tagError);
  }
}
```

**Update `handleInvoicePaid`** (after `updateUserProfile`):

```typescript
// NEW: detect first paid invoice after trial (trialing → active transition)
// Only flip lifecycle on this specific transition; renewals are no-ops.
const priorStatus = await getPriorStatus(customerId);
if (priorStatus === 'trialing' && subscriptionData.status === 'active') {
  const customer = await stripe.customers.retrieve(customerId);
  const email = (customer as Stripe.Customer).email;
  if (email) await setLifecycle(email, 'paid');
} else if (priorStatus === 'past_due' && subscriptionData.status === 'active') {
  // Dunning recovery
  const customer = await stripe.customers.retrieve(customerId);
  const email = (customer as Stripe.Customer).email;
  if (email) await setLifecycle(email, 'paid');
}
```

**Update `handleInvoicePaymentFailed`**:

```typescript
await updateUserProfile(getSupabaseAdmin(), customerId, {
  subscription_status: 'past_due',
});
// NEW: trigger Dunning automation
try {
  const customer = await stripe.customers.retrieve(customerId);
  const email = (customer as Stripe.Customer).email;
  if (email) await setLifecycle(email, 'past_due');
} catch (err) {
  console.warn(`[webhook] Failed to set past_due lifecycle: ${err}`);
}
```

**Update `handleSubscriptionUpdated`** (detect cancel-at-period-end):

```typescript
const wasNotCanceling = !(await getPriorCancelAtPeriodEnd(customerId));
// ...existing updateUserProfile call...

// NEW: detect the canceling transition
if (canceling && wasNotCanceling) {
  const customer = await stripe.customers.retrieve(customerId);
  const email = (customer as Stripe.Customer).email;
  if (email) await setLifecycle(email, 'canceling');
} else if (!canceling && !wasNotCanceling) {
  // Reactivation — back to paid
  const customer = await stripe.customers.retrieve(customerId);
  const email = (customer as Stripe.Customer).email;
  if (email) await setLifecycle(email, 'paid');
}
```

(Requires a `getPriorCancelAtPeriodEnd` helper analogous to `getPriorStatus`.)

**Update `handleSubscriptionDeleted`** to distinguish trial-cancel vs paid-cancel:

```typescript
const priorStatus = await getPriorStatus(customerId);
// ...existing updateUserProfile call...

try {
  const customer = await stripe.customers.retrieve(customerId);
  const email = (customer as Stripe.Customer).email;
  if (email) {
    await untagSubscriber(email);
    const next = priorStatus === 'trialing' ? 'trial_canceled' : 'paid_canceled';
    await setLifecycle(email, next);
  }
} catch (err) {
  console.warn(`[webhook] Failed to untag/lifecycle: ${err}`);
}
```

**Add a new `charge.refunded` handler**:

```typescript
case 'charge.refunded': {
  const charge = event.data.object as Stripe.Charge;
  const customerId = charge.customer as string;
  if (customerId) {
    const customer = await stripe.customers.retrieve(customerId);
    const email = (customer as Stripe.Customer).email;
    if (email) await setLifecycle(email, 'paid_canceled');
  }
  break;
}
```

Also add `CHARGE_REFUNDED: 'charge.refunded'` to `WEBHOOK_EVENTS` in `lib/stripe/server.ts`.

### 6.3 `frontend/app/api/reports/team-card/route.ts`

In the `subscribeFreeLead` call, add `lifecycle: 'lead'` to the custom fields (or just call `setLifecycle` after). One line.

### 6.4 Tests

Add to `frontend/app/api/stripe/webhook/__tests__/route.test.ts`:
- `lifecycle = trialing` set on trialing checkout
- `lifecycle = paid` set on direct-to-paid checkout
- `lifecycle = paid` set only on first invoice.paid after trial (not on renewals)
- `lifecycle = past_due` set on payment failed
- `lifecycle = canceling` set on cancel-at-period-end
- `lifecycle = trial_canceled` vs `paid_canceled` set on subscription.deleted based on prior status
- `lifecycle = paid_canceled` set on charge.refunded

## 7. Beehiiv backfill (one-time)

For existing subscribers, write `lifecycle` based on current state:

| Current state | Lifecycle |
|---|---|
| Tier = Premium AND user_profile.subscription_status = `trialing` | `trialing` |
| Tier = Premium AND subscription_status = `active` | `paid` |
| Tier = Premium AND subscription_status = `past_due` | `past_due` |
| Tier = Free AND has report-card custom fields | `free_drip` (assume nurture finished) |
| Tier = Free AND no other signals | `free_drip` |

Script lives in `scripts/backfill_beehiiv_lifecycle.py` — joins Supabase `user_profiles` to Beehiiv emails via API and writes `lifecycle` in batches.

## 8. Trial Onboarding email cadence (Automation #3)

Trigger: `lifecycle becomes trialing`. Per-step gate: `lifecycle = trialing` (so converters stop receiving trial-specific emails the moment they convert to `paid`).

| # | Day | Subject | Job |
|---|-----|---------|-----|
| 1 | 0 (immediate) | "You're in — here's where to start" | Welcome, set expectation (7-day trial), CTA to favorite first team |
| 2 | Day 1 | "The 3 features most people miss in their first week" | Activation — drive feature adoption (Compare, Watchlist, Schedule view) |
| 3 | Day 2 | "How [example club] uses PitchRank on game day" | Social proof — concrete use case, screenshots |
| 4 | Day 3 | "Your team's biggest rivals, ranked" | Personalized — pulls watchlist data, drives re-engagement |
| 5 | Day 5 | "2 days left on your trial — quick check-in" | Soft conversion nudge; explain what they'll lose; surface value used so far |
| 6 | Day 6 | "Tomorrow your trial ends. Here's what changes" | Hard conversion CTA; price reminder; FAQ link |
| 7 | Day 7 | "Last call — keep your access" | Final CTA before billing; includes "lock in annual for 20% off" if applicable |

Notes:
- Emails 5-7 should reference the day count dynamically using Beehiiv's custom-field merge tags or be hard-coded to absolute days.
- Email 7 fires hours before the actual conversion. Anyone who's converted by then is filtered out by the per-step `lifecycle = trialing` gate.
- After Day 7, the automation ends. Stripe handles the conversion. If they converted → `lifecycle becomes paid` triggers the Paid Drip automation. If they didn't (and didn't cancel) → they auto-converted, same path. If they canceled → Trial Cancel Drip.

## 9. Rollout plan

1. **Add `lifecycle` custom field in Beehiiv** (manual, UI). 2 min.
2. **Backfill existing subscribers** (one-time script). 30 min including verification.
3. **Ship code changes** (lib/beehiiv.ts + webhook handlers + tests) — single PR. ~1 hour with tests.
4. **Build Trial Onboarding automation** in Beehiiv with the 7 emails. ~3 hours including copywriting.
5. **Build Paid Drip automation** (lower priority; can launch later). ~2 hours.
6. **Build Trial Cancel + Paid Win-Back + Non-Premium Drip + Dunning + Cancellation Save** — incremental, in priority order.

Total to MVP (entries 1-4): ~4-5 hours of focused work.

## 10. Risks / open questions

- **Beehiiv API rate limits on backfill.** Batch with delays; expected to take 10-15 min for current subscriber count.
- **Custom-field name collision.** Beehiiv lower-cases / normalizes custom field names — verify `lifecycle` lands as-expected before backfill.
- **Stripe event ordering races.** Stripe fires `checkout.session.completed` then `customer.subscription.updated` back-to-back; our existing webhook already has a known race on user-profile reads (see Vercel logs May 16 18:21:22). Lifecycle writes will inherit this — non-fatal because lifecycle uses email lookup (works as soon as profile exists) but worth retest after fix.
- **Tier vs lifecycle.** Some emails might want to gate on `tier = Premium` (paywall content) AND `lifecycle = paid` (not trialing). Document this in the brand voice guide.
