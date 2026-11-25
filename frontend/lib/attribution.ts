/**
 * Campaign attribution a sale checkout carries into Stripe metadata. The browser keeps the session's
 * first-touch landing values in sessionStorage (a sale-banner click overwrites `campaign` and
 * `source`); the checkout route re-sanitises whatever it is sent, so the same rules apply on both sides.
 */

export const ATTRIBUTION_KEYS = [
  'campaign',
  'source',
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_content',
] as const;

export type Attribution = Partial<Record<(typeof ATTRIBUTION_KEYS)[number], string>>;

const MAX_LENGTH = 100;
const STORAGE_KEY = 'pitchrank_attribution';

function cleanValue(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const cleaned = Array.from(value.replace(/\p{Cc}/gu, ''))
    .slice(0, MAX_LENGTH)
    .join('');
  return cleaned || null;
}

/** Only the known keys, each a string capped at 100 characters with control characters removed. */
export function sanitizeAttribution(raw: unknown): Attribution {
  if (!raw || typeof raw !== 'object') return {};
  const attribution: Attribution = {};
  for (const key of ATTRIBUTION_KEYS) {
    const value = cleanValue((raw as Record<string, unknown>)[key]);
    if (value) attribution[key] = value;
  }
  return attribution;
}

export function attributionFromParams(params: URLSearchParams): Attribution {
  return sanitizeAttribution(Object.fromEntries(ATTRIBUTION_KEYS.map((key) => [key, params.get(key)])));
}

/** Per key: a value in the page's own URL wins, and the stored values fill each key it lacks. */
export function mergeAttribution(page: Attribution, stored: Attribution): Attribution {
  return { ...stored, ...page };
}

export function readAttribution(): Attribution {
  try {
    return sanitizeAttribution(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? '{}'));
  } catch {
    return {};
  }
}

function writeAttribution(attribution: Attribution): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(attribution));
  } catch {
    // Storage can be unavailable (private browsing); attribution is best-effort.
  }
}

/** Store this landing's campaign and UTM values, keeping any the session already recorded. */
export function captureLandingAttribution(search: string = window.location.search): void {
  // `source` is not a landing value: on /upgrade it names the paywall the visitor came through.
  const { source: _source, ...landing } = attributionFromParams(new URLSearchParams(search));
  if (Object.keys(landing).length === 0) return;
  writeAttribution({ ...landing, ...readAttribution() });
}

/** Overwrite just these keys, as a click on the sale banner does for `campaign` and `source`. */
export function recordClickAttribution(values: Attribution): void {
  writeAttribution({ ...readAttribution(), ...sanitizeAttribution(values) });
}
