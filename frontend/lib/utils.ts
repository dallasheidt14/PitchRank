import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Format PowerScore (ML-adjusted) for display
 * Converts from 0.0-1.0 range to 0-100 scale with 2 decimal places
 * @param ps - PowerScore value (0.0-1.0) or null/undefined
 * @returns Formatted string (e.g., "41.50") or "—" if null/undefined
 */
export function formatPowerScore(ps?: number | null): string {
  if (ps == null) return "—";
  return (ps * 100).toFixed(2);
}

/**
 * Format SOS Index for display
 * Converts from 0.0-1.0 range to 0-100 scale with 1 decimal place
 * @param sosNorm - SOS normalized value (0.0-1.0) or null/undefined
 * @returns Formatted string (e.g., "73.1") or "—" if null/undefined
 */
export function formatSOSIndex(sosNorm?: number | null): string {
  if (sosNorm == null) return "—";
  return (sosNorm * 100).toFixed(1);
}

/**
 * Extract age GROUP from team name (fallback when age field is missing/wrong)
 *
 * IMPORTANT: In youth soccer, "14B" means BIRTH YEAR 2014, NOT age 14!
 * Age GROUP = age player turns this year + 1 (U12 means "Under 12" = 11-year-olds)
 *
 * - "14B Engilman" → birth year 2014 → turns 11 in 2025 → U12
 * - "08G Excel" → birth year 2008 → turns 17 in 2025 → U18
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

  // Pattern 2: "14B", "14G" format - this is BIRTH YEAR, not age!
  // Valid birth years: 08-19 (2008-2019) for youth soccer
  const birthYearPattern = /\b(0[89]|1[0-9])[BG]\b/i;
  const birthYearMatch = teamName.match(birthYearPattern);
  if (birthYearMatch) {
    const birthYearSuffix = parseInt(birthYearMatch[1], 10);
    const birthYear = 2000 + birthYearSuffix;
    const currentYear = new Date().getFullYear();
    // Calculate age player turns this year, then +1 for age GROUP
    // e.g., 2014 birth in 2025 = turns 11 = U12 (under 12)
    const ageTurning = currentYear - birthYear;
    const ageGroup = ageTurning + 1; // U-age is always +1 from actual age
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
    const currentYear = new Date().getFullYear();
    const ageTurning = currentYear - birthYear;
    const ageGroup = ageTurning + 1;
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
  
  // If already a number, return it
  if (typeof ageGroup === 'number') {
    return ageGroup > 0 && ageGroup < 100 ? ageGroup : null;
  }
  
  // Handle "u11" format
  if (ageGroup.startsWith('u') || ageGroup.startsWith('U')) {
    const age = parseInt(ageGroup.slice(1), 10);
    return age > 0 && age < 100 ? age : null;
  }
  
  // Handle birth year (e.g., "2014")
  const birthYear = parseInt(ageGroup, 10);
  if (birthYear > 1900 && birthYear <= new Date().getFullYear()) {
    const currentYear = new Date().getFullYear();
    const age = currentYear - birthYear;
    return age > 0 && age < 100 ? age : null;
  }
  
  // Try parsing as direct number
  const directAge = parseInt(ageGroup, 10);
  if (directAge > 0 && directAge < 100) {
    return directAge;
  }
  
  return null;
}
