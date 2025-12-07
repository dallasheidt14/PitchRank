/**
 * Date utility functions for timezone-safe date handling.
 *
 * Problem: When JavaScript parses a date-only string like "2025-11-02" with new Date(),
 * it interprets it as UTC midnight. When displayed in a local timezone (e.g., Mountain Time),
 * this can shift the date by a day (Nov 2 UTC midnight = Nov 1 5PM MT).
 *
 * Solution: Parse date-only strings as local dates for display purposes.
 */

/**
 * Parse a date-only string (YYYY-MM-DD) as a local date.
 *
 * Use this instead of `new Date(dateString)` when you have a date-only string
 * and want to display it in the user's local timezone without day shifting.
 *
 * @param dateString - Date string in YYYY-MM-DD format (e.g., "2025-11-02")
 * @returns Date object representing local midnight on that date
 *
 * @example
 * // Instead of: new Date("2025-11-02") // UTC midnight, may show wrong day
 * // Use: parseLocalDate("2025-11-02") // Local midnight, correct day
 */
export function parseLocalDate(dateString: string): Date {
  const [year, month, day] = dateString.split('-').map(Number);
  return new Date(year, month - 1, day); // month is 0-indexed in JS
}

/**
 * Format a date-only string for display.
 *
 * Safely formats a YYYY-MM-DD date string without timezone shifting.
 *
 * @param dateString - Date string in YYYY-MM-DD format
 * @param options - Intl.DateTimeFormat options (defaults to short month, day, year)
 * @returns Formatted date string (e.g., "Nov 2, 2025")
 *
 * @example
 * formatGameDate("2025-11-02") // "Nov 2, 2025"
 * formatGameDate("2025-11-02", { month: 'long' }) // "November 2, 2025"
 */
export function formatGameDate(
  dateString: string,
  options: Intl.DateTimeFormatOptions = {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }
): string {
  const date = parseLocalDate(dateString);
  return date.toLocaleDateString('en-US', options);
}

/**
 * Format a date for chart axis labels (short format).
 *
 * @param dateString - Date string in YYYY-MM-DD format
 * @returns Short formatted date (e.g., "Nov 2")
 */
export function formatChartDate(dateString: string): string {
  return formatGameDate(dateString, {
    month: 'short',
    day: 'numeric',
  });
}
