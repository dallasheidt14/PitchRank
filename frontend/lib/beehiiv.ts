/**
 * Beehiiv API client for tagging subscribers.
 *
 * Used by the Stripe webhook to tag/untag subscribers as "premium"
 * so the Beehiiv welcome automation can gate pitch emails.
 */

const BEEHIIV_API_URL = 'https://api.beehiiv.com/v2';

function getConfig() {
  const apiKey = process.env.BEEHIIV_API_KEY;
  const pubId = process.env.BEEHIIV_PUBLICATION_ID;
  return { apiKey, pubId };
}

/**
 * Find a Beehiiv subscriber by email. Returns the subscriber object or null.
 */
async function findSubscriber(email: string): Promise<{ id: string } | null> {
  const { apiKey, pubId } = getConfig();
  if (!apiKey || !pubId) return null;

  const resp = await fetch(
    `${BEEHIIV_API_URL}/publications/${pubId}/subscriptions?email=${encodeURIComponent(email)}`,
    {
      headers: { Authorization: `Bearer ${apiKey}` },
    },
  );

  if (!resp.ok) {
    console.warn(`[beehiiv] Subscriber lookup failed (${resp.status}): ${await resp.text()}`);
    return null;
  }

  const data = await resp.json();
  const subs = data.data ?? [];
  return subs.length > 0 ? subs[0] : null;
}

/**
 * Add a tag to a Beehiiv subscriber by email.
 * Creates the subscriber if they don't exist (with the tag).
 */
export async function tagSubscriber(email: string, tag: string): Promise<boolean> {
  const { apiKey, pubId } = getConfig();
  if (!apiKey || !pubId) {
    console.warn('[beehiiv] API key or publication ID not configured, skipping tag');
    return false;
  }

  try {
    const subscriber = await findSubscriber(email);

    if (subscriber) {
      // Subscriber exists — add tag via PATCH
      const resp = await fetch(
        `${BEEHIIV_API_URL}/publications/${pubId}/subscriptions/${subscriber.id}`,
        {
          method: 'PATCH',
          headers: {
            Authorization: `Bearer ${apiKey}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            custom_fields: [{ name: 'plan', value: tag }],
          }),
        },
      );

      if (!resp.ok) {
        console.warn(`[beehiiv] Tag update failed (${resp.status}): ${await resp.text()}`);
        return false;
      }
    } else {
      // Subscriber doesn't exist — create with tag
      const resp = await fetch(
        `${BEEHIIV_API_URL}/publications/${pubId}/subscriptions`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${apiKey}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            email,
            custom_fields: [{ name: 'plan', value: tag }],
          }),
        },
      );

      if (!resp.ok) {
        console.warn(`[beehiiv] Subscriber creation failed (${resp.status}): ${await resp.text()}`);
        return false;
      }
    }

    console.log(`[beehiiv] Tagged ${email} as "${tag}"`);
    return true;
  } catch (err) {
    console.error(`[beehiiv] Error tagging subscriber: ${err}`);
    return false;
  }
}

/**
 * Remove the premium tag from a subscriber (set to "free").
 */
export async function untagSubscriber(email: string): Promise<boolean> {
  return tagSubscriber(email, 'free');
}
