/** UUID format check (case-insensitive 8-4-4-4-12 hex). */
export const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidUuid(value: string): boolean {
  return UUID_REGEX.test(value);
}

/** Loose email shape check — local@domain.tld, no whitespace. */
export const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(value: string): boolean {
  return EMAIL_REGEX.test(value);
}

/**
 * Misspelled provider domains mapped to what the person meant. Matched on the
 * whole domain so an unusual-but-real domain (school districts, employers) can
 * never be flagged — only an exact hit here suggests anything.
 */
const EMAIL_DOMAIN_TYPOS: Record<string, string> = {
  'gmai.com': 'gmail.com',
  'gmial.com': 'gmail.com',
  'gmaill.com': 'gmail.com',
  'gnail.com': 'gmail.com',
  'gmail.co': 'gmail.com',
  'gmail.con': 'gmail.com',
  'gmail.cm': 'gmail.com',
  'yaho.com': 'yahoo.com',
  'yahooo.com': 'yahoo.com',
  'yhaoo.com': 'yahoo.com',
  'yahoo.co': 'yahoo.com',
  'yahoo.con': 'yahoo.com',
  'hotmai.com': 'hotmail.com',
  'hotmial.com': 'hotmail.com',
  'hotmal.com': 'hotmail.com',
  'hotmail.con': 'hotmail.com',
  'outlok.com': 'outlook.com',
  'outloo.com': 'outlook.com',
  'outlook.con': 'outlook.com',
  'iclou.com': 'icloud.com',
  'icloud.con': 'icloud.com',
  'iclould.com': 'icloud.com',
  'aol.con': 'aol.com',
};

/** Corrected address when the domain is a known typo, else null. */
export function suggestEmailCorrection(value: string): string | null {
  const parts = value.trim().toLowerCase().split('@');
  if (parts.length !== 2) return null;

  const [local, domain] = parts;
  if (!local || !Object.hasOwn(EMAIL_DOMAIN_TYPOS, domain)) return null;

  return `${local}@${EMAIL_DOMAIN_TYPOS[domain]}`;
}
