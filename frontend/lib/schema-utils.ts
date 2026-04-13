/**
 * Safely serialize data as JSON-LD for use in <script type="application/ld+json">.
 * Escapes `<` to prevent XSS via </script> injection.
 */
export function safeJsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, '\\u003c');
}
