/**
 * Constants used throughout the PitchRank frontend
 */

export const US_STATES = [
  { code: 'al', name: 'Alabama' },
  { code: 'ak', name: 'Alaska' },
  { code: 'az', name: 'Arizona' },
  { code: 'ar', name: 'Arkansas' },
  { code: 'ca', name: 'California' },
  { code: 'co', name: 'Colorado' },
  { code: 'ct', name: 'Connecticut' },
  { code: 'de', name: 'Delaware' },
  { code: 'fl', name: 'Florida' },
  { code: 'ga', name: 'Georgia' },
  { code: 'hi', name: 'Hawaii' },
  { code: 'id', name: 'Idaho' },
  { code: 'il', name: 'Illinois' },
  { code: 'in', name: 'Indiana' },
  { code: 'ia', name: 'Iowa' },
  { code: 'ks', name: 'Kansas' },
  { code: 'ky', name: 'Kentucky' },
  { code: 'la', name: 'Louisiana' },
  { code: 'me', name: 'Maine' },
  { code: 'md', name: 'Maryland' },
  { code: 'ma', name: 'Massachusetts' },
  { code: 'mi', name: 'Michigan' },
  { code: 'mn', name: 'Minnesota' },
  { code: 'ms', name: 'Mississippi' },
  { code: 'mo', name: 'Missouri' },
  { code: 'mt', name: 'Montana' },
  { code: 'ne', name: 'Nebraska' },
  { code: 'nv', name: 'Nevada' },
  { code: 'nh', name: 'New Hampshire' },
  { code: 'nj', name: 'New Jersey' },
  { code: 'nm', name: 'New Mexico' },
  { code: 'ny', name: 'New York' },
  { code: 'nc', name: 'North Carolina' },
  { code: 'nd', name: 'North Dakota' },
  { code: 'oh', name: 'Ohio' },
  { code: 'ok', name: 'Oklahoma' },
  { code: 'or', name: 'Oregon' },
  { code: 'pa', name: 'Pennsylvania' },
  { code: 'ri', name: 'Rhode Island' },
  { code: 'sc', name: 'South Carolina' },
  { code: 'sd', name: 'South Dakota' },
  { code: 'tn', name: 'Tennessee' },
  { code: 'tx', name: 'Texas' },
  { code: 'ut', name: 'Utah' },
  { code: 'vt', name: 'Vermont' },
  { code: 'va', name: 'Virginia' },
  { code: 'wa', name: 'Washington' },
  { code: 'wv', name: 'West Virginia' },
  { code: 'wi', name: 'Wisconsin' },
  { code: 'wy', name: 'Wyoming' },
] as const;

// --- Site URL ---

/** Base URL without www prefix, used by most pages for canonical URLs and OG metadata. */
export const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

/**
 * Base URL with www prefix, used by root layout metadataBase and sitemap.
 * Derived from BASE_URL to ensure the www variant stays in sync.
 */
export const BASE_URL_WWW = BASE_URL.includes('://www.') ? BASE_URL : BASE_URL.replace('https://', 'https://www.');

// --- Age Groups ---

/** Standard ranked age groups (excludes u18 which has no rankings cohort). */
export const AGE_GROUPS = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u19'] as const;

/** Extended age groups including u8, u9, u18 — used for validation and team creation forms. */
export const AGE_GROUPS_ALL = [
  'u8',
  'u9',
  'u10',
  'u11',
  'u12',
  'u13',
  'u14',
  'u15',
  'u16',
  'u17',
  'u18',
  'u19',
] as const;

/** Age groups as value/label pairs for select dropdowns. */
export const AGE_GROUP_OPTIONS = AGE_GROUPS.map((ag) => ({
  value: ag,
  label: ag.toUpperCase(),
}));

// --- Gender ---

/** Map single-letter gender codes to display labels. */
export const GENDER_LABELS: Record<string, string> = {
  M: 'Boys',
  F: 'Girls',
  B: 'Boys',
  G: 'Girls',
};

/** Map URL-slug gender strings to display labels. */
export const GENDER_SLUG_LABELS: Record<string, string> = {
  male: 'Boys',
  female: 'Girls',
  boys: 'Boys',
  girls: 'Girls',
};

/**
 * Format a gender code or slug to a display label.
 * Handles M/F/B/G, male/female, Male/Female, boys/girls.
 */
export function formatGender(gender: string): string {
  return GENDER_LABELS[gender] ?? GENDER_SLUG_LABELS[gender.toLowerCase()] ?? 'Unknown';
}

/** Gender options for select dropdowns. */
export const GENDER_OPTIONS = [
  { value: 'M' as const, label: 'Boys' },
  { value: 'F' as const, label: 'Girls' },
];
