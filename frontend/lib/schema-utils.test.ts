import { describe, expect, it } from 'vitest';
import { safeJsonLd } from './schema-utils';

describe('safeJsonLd', () => {
  it('serializes a plain object', () => {
    expect(safeJsonLd({ name: 'PitchRank' })).toBe('{"name":"PitchRank"}');
  });

  it('escapes < to prevent </script> XSS injection', () => {
    const result = safeJsonLd({ text: '</script><img onerror=alert(1)>' });
    expect(result).not.toContain('<');
    expect(result).toContain('\\u003c');
  });

  it('handles empty object', () => {
    expect(safeJsonLd({})).toBe('{}');
  });

  it('handles nested objects with special characters', () => {
    const data = { '@context': 'https://schema.org', description: 'A < B' };
    const result = safeJsonLd(data);
    expect(result).not.toContain('<');
    expect(JSON.parse(result.replace(/\\u003c/g, '<'))).toEqual(data);
  });
});
