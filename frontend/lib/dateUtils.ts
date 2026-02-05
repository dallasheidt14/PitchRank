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
 * Parse a date string as a local date.
 *
 * Handles both formats:
 * - Date-only: "2025-11-02" (YYYY-MM-DD)
 * - ISO timestamp: "2025-11-02T00:00:00.000Z"
 *
 * Use this instead of `new Date(dateString)` when you want to display
 * the date in the user's local timezone without day shifting.
 *
 * @param dateString - Date string in YYYY-MM-DD or ISO format
 * @returns Date object representing local midnight on that date
 *
 * @example
 * parseLocalDate("2025-11-02") // Local midnight, Nov 2
 * parseLocalDate("2025-11-02T00:00:00.000Z") // Local midnight, Nov 2
 */
export function parseLocalDate(dateString: string): Date {
  // Handle both YYYY-MM-DD and full ISO timestamps
  // Extract just the date portion (first 10 characters)
  const datePart = dateString.substring(0, 10);
  const [year, month, day] = datePart.split('-').map(Number);

  // Validate the parsed values
  if (isNaN(year) || isNaN(month) || isNaN(day)) {
    console.warn(`Invalid date string: ${dateString}`);
    return new Date(NaN); // Return Invalid Date
  }

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
