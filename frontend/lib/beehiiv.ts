/**
 * Beehiiv API client for managing subscriber tiers.
 *
 * Used by the Stripe webhook to set subscribers as "premium" or "free"
 * so the Beehiiv welcome automation can gate pitch emails.
 *
 * Uses Beehiiv's native `tier` field (not tags or custom fields).
 * Docs: https://developers.beehiiv.com/api-reference/subscriptions/put
 */

const BEEHIIV_API_URL = 'https://api.beehiiv.com/v2';

function getConfig() {
  const apiKey = process.env.BEEHIIV_API_KEY;
  const pubId = process.env.BEEHIIV_PUBLICATION_ID;
  return { apiKey, pubId };
}

/**
 * Find a Beehiiv subscriber by email. Returns subscriber id or null.
 */
async function findSubscriberId(email: string): Promise<string | null> {
  const { apiKey, pubId } = getConfig();
  if (!apiKey || !pubId) return null;

  const resp = await fetch(
    `${BEEHIIV_API_URL}/publications/${pubId}/subscriptions/by_email/${encodeURIComponent(email)}`,
    {
      headers: { Authorization: `Bearer ${apiKey}` },
    }
  );

  if (!resp.ok) {
    console.warn(`[beehiiv] Subscriber lookup failed (${resp.status})`);
    return null;
  }

  const data = await resp.json();
  return data.data?.id ?? null;
}

/**
 * Set a subscriber's tier in Beehiiv ("premium" or "free").
 * If the subscriber doesn't exist, creates them with the given tier.
 */
export async function setSubscriberTier(email: string, tier: 'premium' | 'free'): Promise<boolean> {
  const { apiKey, pubId } = getConfig();
  if (!apiKey || !pubId) {
    console.warn('[beehiiv] API key or publication ID not configured, skipping');
    return false;
  }

  try {
    const subscriberId = await findSubscriberId(email);

    if (subscriberId) {
      // Subscriber exists — update tier
      const resp = await fetch(`${BEEHIIV_API_URL}/publications/${pubId}/subscriptions/${subscriberId}`, {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ tier }),
      });

      if (!resp.ok) {
        const body = await resp.text();
        console.warn(`[beehiiv] Tier update failed (${resp.status}): ${body}`);
        return false;
      }
    } else {
      // Subscriber doesn't exist — create with tier
      const resp = await fetch(`${BEEHIIV_API_URL}/publications/${pubId}/subscriptions`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, tier }),
      });

      if (!resp.ok) {
        const body = await resp.text();
        console.warn(`[beehiiv] Subscriber creation failed (${resp.status}): ${body}`);
        return false;
      }
    }

    console.log(`[beehiiv] Set subscriber tier to "${tier}"`);
    return true;
  } catch (err) {
    console.error(`[beehiiv] Error setting subscriber tier: ${err}`);
    return false;
  }
}

/**
 * Tag subscriber as premium in Beehiiv.
 */
export async function tagSubscriber(email: string): Promise<boolean> {
  return setSubscriberTier(email, 'premium');
}

/**
 * Remove premium status from subscriber in Beehiiv.
 */
export async function untagSubscriber(email: string): Promise<boolean> {
  return setSubscriberTier(email, 'free');
}

/**
 * Funnel stage. Source of truth is the Stripe webhook (+ report-card API
 * for `lead`). Beehiiv automations route on this field; do not edit in
 * the Beehiiv UI. Spec: docs/superpowers/specs/2026-05-17-lifecycle-automation-flow.md
 */
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
 * Set the `lifecycle` custom field on an existing Beehiiv subscriber.
 * No-op if the subscriber doesn't exist yet — the caller is responsible
 * for ensuring subscription (via tagSubscriber or subscribeFreeLead) first.
 */
export async function setLifecycle(email: string, lifecycle: Lifecycle): Promise<boolean> {
  const { apiKey, pubId } = getConfig();
  if (!apiKey || !pubId) {
    console.warn('[beehiiv] API key or publication ID not configured, skipping setLifecycle');
    return false;
  }

  try {
    const subscriberId = await findSubscriberId(email);
    if (!subscriberId) {
      console.warn(`[beehiiv] setLifecycle: no subscriber found for ${email}`);
      return false;
    }

    const resp = await fetch(`${BEEHIIV_API_URL}/publications/${pubId}/subscriptions/${subscriberId}`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        custom_fields: [{ name: 'lifecycle', value: lifecycle }],
      }),
    });

    if (!resp.ok) {
      const body = await resp.text();
      console.warn(`[beehiiv] setLifecycle failed (${resp.status}): ${body}`);
      return false;
    }

    console.log(`[beehiiv] Set lifecycle="${lifecycle}"`);
    return true;
  } catch (err) {
    console.error(`[beehiiv] Error setting lifecycle: ${err}`);
    return false;
  }
}

export interface ReportCardLeadAttrs {
  teamName?: string | null;
  clubName?: string | null;
  state?: string | null;
  ageGroup?: string | null;
  gender?: string | null;
  role?: string | null;
}

/**
 * Subscribe a report-card lead to Beehiiv as a free-tier subscriber.
 *
 * Sets utm_source=report-card and custom fields so the welcome automation
 * can branch on source and personalize Day 2+ emails with team details.
 * Creates the subscriber if missing; updates their custom fields if they
 * already exist (returning visitor).
 */
export async function subscribeFreeLead(email: string, attrs: ReportCardLeadAttrs = {}): Promise<boolean> {
  const { apiKey, pubId } = getConfig();
  if (!apiKey || !pubId) {
    console.warn('[beehiiv] API key or publication ID not configured, skipping report-card sync');
    return false;
  }

  const customFields = [
    { name: 'source', value: 'report-card' },
    { name: 'lifecycle', value: 'lead' },
    { name: 'team_name', value: attrs.teamName ?? '' },
    { name: 'club_name', value: attrs.clubName ?? '' },
    { name: 'state', value: attrs.state ?? '' },
    { name: 'age_group', value: attrs.ageGroup ?? '' },
    { name: 'gender', value: attrs.gender ?? '' },
    { name: 'role', value: attrs.role ?? '' },
  ].filter((f) => f.value !== '');

  try {
    const subscriberId = await findSubscriberId(email);

    if (subscriberId) {
      const resp = await fetch(`${BEEHIIV_API_URL}/publications/${pubId}/subscriptions/${subscriberId}`, {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ custom_fields: customFields }),
      });

      if (!resp.ok) {
        const body = await resp.text();
        console.warn(`[beehiiv] Report-card custom fields update failed (${resp.status}): ${body}`);
        return false;
      }
    } else {
      const resp = await fetch(`${BEEHIIV_API_URL}/publications/${pubId}/subscriptions`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email,
          tier: 'free',
          utm_source: 'report-card',
          reactivate_existing: false,
          send_welcome_email: false,
          custom_fields: customFields,
        }),
      });

      if (!resp.ok) {
        const body = await resp.text();
        console.warn(`[beehiiv] Report-card subscribe failed (${resp.status}): ${body}`);
        return false;
      }
    }

    console.log(`[beehiiv] Synced report-card lead (${attrs.teamName ?? 'unknown team'})`);
    return true;
  } catch (err) {
    console.error(`[beehiiv] Error syncing report-card lead: ${err}`);
    return false;
  }
}

/**
 * Enroll an email in a Beehiiv automation via the automation-journey API.
 *
 * Works for both new and existing subscribers (a returning newsletter
 * subscriber filling out the report-card form gets enrolled even though
 * the create-subscription branch never fires for them).
 *
 * The target automation must have an "Add by API" trigger enabled in
 * Beehiiv. Silently no-ops if API credentials or the automation ID are
 * not configured.
 */
export async function enrollInAutomation(email: string, automationId: string): Promise<boolean> {
  const { apiKey, pubId } = getConfig();
  if (!apiKey || !pubId || !automationId) return false;

  try {
    const resp = await fetch(`${BEEHIIV_API_URL}/publications/${pubId}/automations/${automationId}/journeys`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email }),
    });

    if (!resp.ok) {
      const body = await resp.text();
      console.warn(`[beehiiv] Automation enrollment failed (${resp.status}): ${body}`);
      return false;
    }

    console.log(`[beehiiv] Enrolled email in automation ${automationId}`);
    return true;
  } catch (err) {
    console.error(`[beehiiv] Error enrolling in automation: ${err}`);
    return false;
  }
}
