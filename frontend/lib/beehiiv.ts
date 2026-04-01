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

    console.log(`[beehiiv] Set ${email} tier to "${tier}"`);
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
