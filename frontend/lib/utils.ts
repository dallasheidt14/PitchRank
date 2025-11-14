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
