# PitchRank Email Lifecycle Automation Spec

**Date:** 2026-05-17 (last updated 2026-05-18)
**Owner:** Dallas Heidt
**Status:** Built — code shipped (#794, #796, #797), 9 Beehiiv automation shells live, email copy in progress

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

All 7 lifecycle automations use the **`Added by API`** trigger; the Stripe webhook (or `/api/reports/team-card` form for `lead`) calls Beehiiv's enrollment endpoint directly. Per-step gates use `lifecycle is <state>` to skip in-flight subscribers whose state changes mid-sequence.

```
ENTRY 1: /report-card form        ENTRY 2: Stripe checkout (trialing)
  ↓                                 ↓
┌──────────────────────┐          ┌──────────────────────┐
│ Report-Card Lead     │          │ Trial Onboarding     │
│ Nurture              │          │ 2 emails (Day 1, 3)  │
│ trigger: Added by API│          │ trigger: Added by API│
│ per-step gate:       │          │ per-step gate:       │
│   lifecycle = lead   │          │   lifecycle=trialing │
└──────────┬───────────┘          └─────────┬────────────┘
           │                                │
   completes nurture                 (Day 8 — Stripe acts)
   (manual handoff today —           ┌──────┴────────────────────────────┐
    see §10 #11)                     ▼          ▼            ▼           ▼
           │                  invoice.paid  sub.deleted  sub.updated  invoice.
           ▼                  (trialing→     (was        cancel_at_   payment_
┌──────────────────────┐       active)       trialing)   period_end   failed
│ Non-Premium Drip     │      ↓              ↓           =true        ↓
│ 4 emails             │ ┌──────────┐ ┌────────────┐  ↓          ┌──────────┐
│ trigger: Added by API│ │Paid Drip │ │Trial Cancel│ ┌──────────┐│ Dunning  │
│ per-step gate:       │ │ 2 emails │ │   Drip     │ │Cancel-   ││ 3 emails │
│   lifecycle=free_drip│ │ (Day 7,  │ │ 2 emails   │ │lation    ││ (Day 0,  │
└──────────────────────┘ │  Day 21) │ │ (Day 1,7)  │ │ Save     ││  5, 14)  │
                         └────┬─────┘ └────────────┘ │ 2 emails ││ recovers │
                              │                      │ (Day 0,5)││ to paid  │
                       sub.deleted /                 └──────────┘│ if       │
                       charge.refunded                           │ invoice. │
                              ↓                                  │ paid     │
                         ┌──────────────┐                        └──────────┘
                         │ Paid Win-Back│
                         │ 3 emails     │
                         │ (Day 3, 14,  │
                         │  30)         │
                         └──────────────┘

  resubscribe anywhere → Stripe fires checkout.session.completed
                      → webhook flips lifecycle=trialing
                      → enrolls in Trial Onboarding again
```

Email counts shown reflect current build decisions (2026-05-18). They can scale up as data justifies — the per-step gate makes mid-sequence churn safe.

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

## 8. Email cadence per automation

Full email copy lives alongside this spec — Trial Onboarding copy is at `docs/marketing/trial-onboarding-emails.md`. Other automations have copy briefs (no body text yet) in §11.

### 8.1 Report Card Lead Nurture (live, pre-existing)

Already built before this spec. Original 7-email sequence. No changes required.

### 8.2 Trial Onboarding (shell live, copy in progress)

Trigger: `Added by API` (webhook on `checkout.session.completed` with status=trialing). Per-step gate: `lifecycle is trialing`.

| # | Day | Job |
|---|-----|-----|
| 1 | Day 1 | Activation — drive into Compare, Watchlist, AI Insights |
| 2 | Day 3 | Personalized — "Who actually beats {{team_name}}?" using merge tags |

Trial converts/cancels around Day 8 — Stripe events fire the appropriate downstream automation (Paid Drip, Trial Cancel Drip, or Dunning) automatically.

### 8.3 Paid Drip

Trigger: `Added by API` (webhook on `invoice.paid` after trial→active or past_due→active). Per-step gate: `lifecycle is paid`.

| # | Day | Job |
|---|-----|-----|
| 1 | Day 7 | AI Insights deep dive — most paying users never opened Season Truth/consistency/persona during trial |
| 2 | Day 21 | Pre-renewal feedback check-in — hit-reply ask, ~9 days before first monthly renewal |

### 8.4 Dunning / Update Card

Trigger: `Added by API` (webhook on `invoice.payment_failed`). Per-step gate: `lifecycle is past_due`. Subscribers exit automatically when invoice succeeds on retry (lifecycle flips to `paid`).

| # | Day | Job |
|---|-----|-----|
| 1 | Day 0 (immediate) | Heads-up + 1-click update payment method link |
| 2 | Day 5 | Reminder; concrete deadline if Stripe's retry window is ~21 days |
| 3 | Day 14 | Last call before Stripe gives up and cancels the subscription |

### 8.5 Cancellation Save

Trigger: `Added by API` (webhook on `customer.subscription.updated` with cancel_at_period_end=true). Per-step gate: `lifecycle is canceling`. Subscribers exit if they reactivate (lifecycle flips back to `paid`).

| # | Day | Job |
|---|-----|-----|
| 1 | Day 0 (immediate) | "Heard you're leaving — here's what you'll lose. Reactivate in one click." |
| 2 | Day 5 | "Last chance" — soft, not pushy |

### 8.6 Trial Cancel Drip

Trigger: `Added by API` (webhook on `customer.subscription.deleted` with prior status=trialing). Per-step gate: `lifecycle is trial_canceled`.

| # | Day | Job |
|---|-----|-----|
| 1 | Day 1 | "What stopped you?" — hit-reply ask, no CTA |
| 2 | Day 7 | "Come back when you're ready" — soft re-trial invite |

### 8.7 Paid Win-Back

Trigger: `Added by API` (webhook on `customer.subscription.deleted` with prior status=active, OR `charge.refunded`). Per-step gate: `lifecycle is paid_canceled`.

| # | Day | Job |
|---|-----|-----|
| 1 | Day 3 | "Sorry to see you go — what would've kept you?" |
| 2 | Day 14 | Reminder of what's changed in the product since they left |
| 3 | Day 30 | Direct re-trial offer (consider a discount on annual) |

### 8.8 Non-Premium Drip

Trigger: `Added by API` (manual or batch enroll — see §10 #11). Per-step gate: `lifecycle is free_drip`.

| # | Day | Job |
|---|-----|-----|
| 1 | Day 7 | Reintroduce the product with a fresh angle |
| 2 | Day 14 | Concrete use case ("here's how to use it before tryouts") |
| 3 | Day 28 | Soft trial nudge ("free 7-day look at Premium") |
| 4 | Day 49 | Last reminder; after this they're on the regular newsletter only |

## 9. Rollout plan & current status

| Step | Status | Notes |
|---|---|---|
| 1. `lifecycle` custom field in Beehiiv | ✅ done | Text type |
| 2. Stripe webhook subscribes to `charge.refunded` + `customer.subscription.trial_will_end` | ✅ done | |
| 3. Code: `setLifecycle` + webhook routing | ✅ done | PR #794 merged |
| 4. Code: `enrollInLifecycleAutomation` + env-var dispatch | ✅ done | PR #796 merged |
| 5. Code: idempotency guards on Stripe re-delivery | ✅ done | PR #797 merged |
| 6. Backfill existing subscribers | ✅ done | 30 writes (3 trialing, 14 paid, 16 free_drip via 2 passes) |
| 7. Build all 9 automation shells in Beehiiv | ✅ done | 7 lifecycle + Report Card Lead + Trial Onboarding |
| 8. Set 7 lifecycle env vars in Vercel | ✅ done | All `BEEHIIV_*_AUTOMATION_ID` vars live |
| 9. Trial Onboarding copy + activate | 🛠️ in progress | 2 emails being written |
| 10. Other 6 automations copy + activate | ⏳ pending | Copy briefs in §8; copywriter handoff in progress |
| 11. Manual cleanup: 3 paying users not in Beehiiv | ⏳ pending | `ruddy_b@msn.com`, `roberto.ar456@yahoo.com`, `peacockpainters@gmail.com` |

**Activate order matters:** automations are currently in **Draft**. Activating before copy is in means subscribers get placeholder emails. Activate each one only as its copy ships.

## 10. Risks / open questions

- **Beehiiv API rate limits on backfill.** Mitigated — backfill ran successfully with 0.25s sleeps between writes.
- **Stripe event ordering races.** Stripe fires `checkout.session.completed` then `customer.subscription.updated` back-to-back; the existing webhook has a known race on user-profile reads (see Vercel logs May 16 18:21:22). Lifecycle writes inherit this but are non-fatal (email lookup is idempotent). Idempotency guards in PR #797 prevent duplicate enrollment on re-delivery.
- **Tier vs lifecycle.** Some emails might want to gate on `tier = Premium` (paywall content) AND `lifecycle = paid` (not trialing). Document in the brand voice guide if/when relevant.
- **#11 Trial Cancel → Non-Premium Drip handoff is no longer automatic.** Original design assumed `lifecycle becomes free_drip` would trigger Non-Premium Drip via segment. With `Added by API` triggers, that doesn't fire automatically. Trial-canceled subscribers complete the 2-email Trial Cancel Drip and then sit in `lifecycle=trial_canceled` indefinitely until they re-trial. Options when this becomes a problem:
  - Add a Beehiiv "Add to Automation" node at end of Trial Cancel Drip to chain into Non-Premium Drip directly (if that node type exists on Scale plan)
  - Add a "Beehiiv completion webhook" handler in our backend
  - Accept the gap and re-enroll the segment manually on a quarterly cadence
- **#12 charge.refunded idempotency weakness.** Refund webhooks don't update `subscription_status`, so re-delivery can't be detected via the standard prior-state check. Rare event; if it becomes a problem, add a Supabase table for processed Stripe event IDs.
- **#13 Direct-to-paid checkouts** would skip Trial Onboarding and route directly to Paid Drip. Current Paid Drip copy assumes the subscriber went through a trial. If a "skip trial" or annual-upfront option is ever added, Paid Drip needs a `came_from_trial` gate or a separate "direct-to-paid welcome" automation. Per Dallas 2026-05-18, all current checkouts include a trial — not a problem today.
