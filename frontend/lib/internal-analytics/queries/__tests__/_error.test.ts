import { describe, it, expect } from 'vitest';
import { toTaxonomyError } from '../_error';

describe('toTaxonomyError', () => {
  it('maps 429 to RATE_LIMIT (retryable)', () => {
    const err = { code: 429, message: 'Too many', response: { headers: { 'retry-after': '30' } } };
    const t = toTaxonomyError(err);
    expect(t.type).toBe('RATE_LIMIT');
    expect(t.retryable).toBe(true);
    expect(t.retry_after_ms).toBe(30_000);
  });

  it('maps 403 to AUTH (not retryable)', () => {
    const t = toTaxonomyError({ code: 403, message: 'Forbidden' });
    expect(t.type).toBe('AUTH');
    expect(t.retryable).toBe(false);
  });

  it('maps 401 to AUTH (not retryable)', () => {
    const t = toTaxonomyError({ code: 401, message: 'Unauthenticated' });
    expect(t.type).toBe('AUTH');
    expect(t.retryable).toBe(false);
  });

  it('maps 400 to VALIDATION with the original message', () => {
    const t = toTaxonomyError({ code: 400, message: 'Invalid metric' });
    expect(t.type).toBe('VALIDATION');
    expect(t.message).toContain('Invalid metric');
    expect(t.retryable).toBe(false);
  });

  it('maps unknown errors to API_ERROR (retryable)', () => {
    const t = toTaxonomyError({ code: 500, message: 'boom' });
    expect(t.type).toBe('API_ERROR');
    expect(t.retryable).toBe(true);
  });

  it('handles non-object errors as API_ERROR (not retryable)', () => {
    const t = toTaxonomyError('string error');
    expect(t.type).toBe('API_ERROR');
    expect(t.retryable).toBe(false);
  });
});
