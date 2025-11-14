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
