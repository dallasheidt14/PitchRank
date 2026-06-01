import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format PowerScore (ML-adjusted) for display
 * Converts from 0.0-1.0 range to 0-100 scale with 2 decimal places
 * @param ps - PowerScore value (0.0-1.0) or null/undefined
 * @returns Formatted string (e.g., "41.50") or "—" if null/undefined
 */
export function formatPowerScore(ps?: number | null): string {
  if (ps == null) return '—';
  return (ps * 100).toFixed(2);
}

/**
 * Format SOS Index for display
 * Converts from 0.0-1.0 range to 0-100 scale with 1 decimal place
 * @param sosNorm - SOS normalized value (0.0-1.0) or null/undefined
 * @returns Formatted string (e.g., "73.1") or "—" if null/undefined
 */
export function formatSOSIndex(sosNorm?: number | null): string {
  if (sosNorm == null) return '—';
  return (sosNorm * 100).toFixed(1);
}

const LEAGUE_DISPLAY: Record<string, string> = {
  ECNL: 'ECNL',
  ECNL_RL: 'ECNL RL',
  MLS_NEXT: 'MLS Next',
  MLS_NEXT_HD: 'MLS Next',
  MLS_NEXT_AD: 'MLS Next AD',
  GA: 'GA',
  DPL: 'DPL',
  NPL: 'NPL',
  EA: 'EA',
  NL: 'NL',
  ASPIRE: 'Aspire',
};

export function formatLeague(league?: string | null): string | null {
  if (!league) return null;
  return LEAGUE_DISPLAY[league] ?? league.replace(/_/g, ' ');
}

const NUMERIC_RE = /^[0-9]+$/;
const ROMAN_RE = /^[ivxlcdm]+$/i;
const ROMAN_VALUES: Record<string, number> = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 };

function romanToArabic(token: string): string {
  const lower = token.toLowerCase();
  let total = 0;
  for (let i = 0; i < lower.length; i++) {
    const cur = ROMAN_VALUES[lower[i]];
    const next = ROMAN_VALUES[lower[i + 1]];
    if (cur === undefined) return token;
    total += next && cur < next ? -cur : cur;
  }
  return total > 0 ? String(total) : token;
}

const UPPERCASE_HINTS = new Set(['hd', 'ad', 'rl', 'mls', 'ecnl', 'ga', 'npl', 'nl', 'dpl', 'ea', 'us', 'fc', 'sc']);

/**
 * Format a distinction value (lowercase pipe-delimited squad distinguisher) for display.
 * Stored format: tokens joined with "|" and ordered by category priority (most-specific first).
 * Display: Title Case (known abbreviations stay uppercase), roman numerals → arabic,
 * word tokens reversed (priority order → natural reading order), numerals always last.
 *
 * Examples:
 *   "i|elite|pre"      → "Pre Elite 1"
 *   "ii|central|select"→ "Select Central 2"
 *   "white|2"          → "White 2"
 *   "red|hd"           → "Red HD"
 *   "smith"            → "Smith"
 */
export function formatDistinction(distinction?: string | null): string | null {
  if (!distinction) return null;
  const tokens = distinction.split('|').filter(Boolean);
  if (tokens.length === 0) return null;
  const isTrailing = (t: string) => NUMERIC_RE.test(t) || ROMAN_RE.test(t);
  const words = tokens.filter((t) => !isTrailing(t));
  const numerals = tokens.filter(isTrailing);
  const reordered = [...words.reverse(), ...numerals];
  return reordered
    .map((t) => {
      if (NUMERIC_RE.test(t)) return t;
      if (ROMAN_RE.test(t)) return romanToArabic(t);
      if (UPPERCASE_HINTS.has(t.toLowerCase())) return t.toUpperCase();
      return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
    })
    .join(' ');
}

const CLUB_ABBREVIATIONS: Array<[RegExp, string]> = [
  [/\bSoccer Club\b/i, 'SC'],
  [/\bFootball Club\b/i, 'FC'],
  [/\bSports Club\b/i, 'SC'],
  [/\bAthletic Club\b/i, 'AC'],
];

export function abbreviateClubName(clubName: string | null | undefined): string {
  if (!clubName) return '';
  let result = clubName;
  for (const [pattern, replacement] of CLUB_ABBREVIATIONS) {
    result = result.replace(pattern, replacement);
  }
  return result;
}

/**
 * Detects a `distinction` that still carries league/tier leakage the resolver
 * did not strip. These designators belong in the `league` column, not the squad
 * distinction; when one leaks in (e.g. "Pre-ECNL" leaves an orphaned "pre", or a
 * smushed "preecnl"/"premls"/"b08ecnl"), the composed name reads badly, so we
 * fall back to the raw team_name.
 *
 * Two layers, because the leakage appears in many affixed forms:
 *  - exact tokens for short/ambiguous designators — substring-matching these
 *    would wrongly flag legitimate squad words ("pre" → "premier", "nl" →
 *    "national", "ga" → a surname).
 *  - substring stems for longer, unambiguous league names that also show up with
 *    age/gender/numeric affixes ("preecnl", "ecnlrl", "mls2", "g08dpl", "edpl").
 *
 * "ad"/"hd" are intentionally excluded: they are load-bearing for MLS NEXT teams,
 * which are already short-circuited upstream via has_modular11_alias. A false
 * positive here is harmless (it just shows the raw team_name), so we err toward
 * catching leakage.
 */
const DISTINCTION_LEAK_EXACT = new Set(['pre', 'rl', 'nl', 'ga', 'ea', 'ea2', 'nal', 'next']);
const DISTINCTION_LEAK_STEMS = ['ecnl', 'ecrl', 'npl', 'mls', 'dpl', 'aspire', 'scdsl'];

function distinctionHasLeakage(distinction?: string | null): boolean {
  if (!distinction) return false;
  return distinction.split('|').some((raw) => {
    const token = raw.trim().toLowerCase();
    if (!token) return false;
    if (DISTINCTION_LEAK_EXACT.has(token)) return true;
    return DISTINCTION_LEAK_STEMS.some((stem) => token.includes(stem));
  });
}

/**
 * Compose a clean display name from structured team fields.
 * Format: "{club_name (abbreviated)} {league} {distinction}" — age is intentionally
 * dropped because it's already in the page's URL filter. Pieces are skipped when null.
 *
 * MLS Next / Modular 11 teams already have well-formatted, recognizable team_name
 * values (e.g. "Cedar Stars Academy Bergen U14 HD") so we leave them untouched
 * regardless of how their distinction tokens decompose.
 *
 * Falls back to team_name when club_name is missing.
 */
export function composeTeamDisplay(team: {
  team_name: string;
  club_name: string | null;
  league?: string | null;
  distinction?: string | null;
  age?: number | null;
  has_modular11_alias?: boolean | null;
}): string {
  if (!team.club_name) return team.team_name;
  if (team.has_modular11_alias) return team.team_name;
  // Dirty-data safety net: if the distinction still carries league/tier leakage
  // (e.g. an orphaned "pre" from "Pre-ECNL"), the composed name reads badly, so
  // show the raw team_name instead until the underlying data is cleaned.
  if (distinctionHasLeakage(team.distinction)) return team.team_name;
  const parts: string[] = [abbreviateClubName(team.club_name)];
  const league = formatLeague(team.league);
  if (league) parts.push(league);
  const distinction = formatDistinction(team.distinction);
  if (distinction) parts.push(distinction);
  return parts.join(' ');
}

/**
 * Soccer season year: rolls over on Aug 1.
 * Before Aug 1, season year = previous calendar year.
 * On/after Aug 1, season year = current calendar year.
 */
function soccerSeasonYear(): number {
  const now = new Date();
  return now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1;
}

/**
 * Extract age GROUP from team name (fallback when age field is missing/wrong)
 *
 * IMPORTANT: In youth soccer, "14B" means BIRTH YEAR 2014, NOT age 14!
 * Formula: seasonYear - birthYear + 1 (season rolls over Aug 1)
 *
 * - "14B Engilman" → birth year 2014 → U12 (2025-26 season)
 * - "08G Excel" → birth year 2008 → U18 (2025-26 season)
 * - "U14 Phoenix" → directly specified as U14 → 14
 *
 * Birth year format: 2-digit year (08-19) followed by B (boys) or G (girls)
 * Direct age format: "U" followed by age (U10, U14, etc.)
 *
 * @param teamName - Team name string
 * @returns Integer age GROUP (e.g., 12 for U12) or null if not found
 */
export function extractAgeFromTeamName(teamName: string | null | undefined): number | null {
  if (!teamName) return null;

  // Pattern 1: "U14", "u14" format - direct age specification (check first)
  const uPattern = /\bU(\d{1,2})\b/i;
  const uMatch = teamName.match(uPattern);
  if (uMatch) {
    const age = parseInt(uMatch[1], 10);
    if (age >= 8 && age <= 19) {
      return age;
    }
  }

  const seasonYear = soccerSeasonYear();

  // Pattern 2: "14B", "14G" format - this is BIRTH YEAR, not age!
  // Valid birth years: 08-19 (2008-2019) for youth soccer
  const birthYearPattern = /\b(0[89]|1[0-9])[BG]\b/i;
  const birthYearMatch = teamName.match(birthYearPattern);
  if (birthYearMatch) {
    const birthYearSuffix = parseInt(birthYearMatch[1], 10);
    const birthYear = 2000 + birthYearSuffix;
    const ageGroup = seasonYear - birthYear + 1;
    if (ageGroup >= 6 && ageGroup <= 19) {
      return ageGroup;
    }
  }

  // Pattern 3: Standalone 2-digit number that could be birth year (without B/G suffix)
  // Be more conservative - only match if it looks like a birth year (08-19)
  const standaloneYearPattern = /\b(0[89]|1[0-9])\b/;
  const standaloneMatch = teamName.match(standaloneYearPattern);
  if (standaloneMatch) {
    const birthYearSuffix = parseInt(standaloneMatch[1], 10);
    const birthYear = 2000 + birthYearSuffix;
    const ageGroup = seasonYear - birthYear + 1;
    if (ageGroup >= 6 && ageGroup <= 19) {
      return ageGroup;
    }
  }

  return null;
}

/**
 * Normalize age group string to integer age
 * Handles formats like "u11" → 11, "2014" → calculate age from birth year
 * @param ageGroup - Age group string (e.g., "u11", "2014") or number
 * @returns Integer age (e.g., 11) or null if invalid
 */
export function normalizeAgeGroup(ageGroup: string | number | null | undefined): number | null {
  if (ageGroup == null) return null;

  let age: number | null = null;

  // If already a number, use it directly
  if (typeof ageGroup === 'number') {
    age = ageGroup > 0 && ageGroup < 100 ? ageGroup : null;
  }
  // Handle "u11" format
  else if (ageGroup.startsWith('u') || ageGroup.startsWith('U')) {
    const parsed = parseInt(ageGroup.slice(1), 10);
    age = parsed > 0 && parsed < 100 ? parsed : null;
  }
  // Handle birth year (e.g., "2014")
  else {
    const birthYear = parseInt(ageGroup, 10);
    if (birthYear > 1900 && birthYear <= new Date().getFullYear()) {
      const seasonYear = soccerSeasonYear();
      const computed = seasonYear - birthYear + 1;
      age = computed > 0 && computed < 100 ? computed : null;
    } else {
      // Try parsing as direct number
      const directAge = parseInt(ageGroup, 10);
      age = directAge > 0 && directAge < 100 ? directAge : null;
    }
  }

  // U18 → U19 remap: U19 encompasses both birth years 2007 and 2008
  if (age === 18) age = 19;

  return age;
}
