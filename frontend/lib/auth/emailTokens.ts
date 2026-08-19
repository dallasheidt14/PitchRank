import type { EmailOtpType } from '@supabase/supabase-js';

const VERIFIABLE_OTP_TYPES: readonly EmailOtpType[] = [
  'email',
  'recovery',
  'invite',
  'email_change',
  'signup',
  'magiclink',
];

export function isVerifiableOtpType(value: string): value is EmailOtpType {
  return (VERIFIABLE_OTP_TYPES as readonly string[]).includes(value);
}

// Unresolvable sentinel host: must never match a real origin.
const SAME_ORIGIN_BASE = 'https://pitchrank.invalid';

/**
 * Reduce a caller-supplied `next` to a same-origin path.
 *
 * Resolves through the URL parser rather than matching on a `//` prefix:
 * browsers read a backslash as a slash in the authority position, so
 * "/(backslash)evil.example" reads as relative but resolves off-origin.
 */
export function safeNextPath(raw: string | null | undefined, fallback = '/rankings'): string {
  if (!raw || !raw.startsWith('/')) {
    return fallback;
  }

  try {
    const resolved = new URL(raw, SAME_ORIGIN_BASE);
    if (resolved.origin !== SAME_ORIGIN_BASE) {
      return fallback;
    }

    // Re-check the serialized path, not just the parsed origin: dot segments
    // normalize away, so `/..//evil.example` resolves same-origin here yet
    // serializes to `//evil.example`, which the caller's redirect() or
    // router.push() parses again as a network-path reference and follows
    // off-site. Callers validate once and hand the output to a parser twice.
    const path = `${resolved.pathname}${resolved.search}${resolved.hash}`;
    return path.startsWith('//') ? fallback : path;
  } catch {
    return fallback;
  }
}
