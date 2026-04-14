import type { TaxonomyError } from '../types';

type GoogleLikeError = {
  code?: number;
  message?: string;
  response?: { headers?: Record<string, string> };
};

function isGoogleLikeError(e: unknown): e is GoogleLikeError {
  return typeof e === 'object' && e !== null && 'code' in e;
}

export function toTaxonomyError(err: unknown): TaxonomyError {
  if (!isGoogleLikeError(err)) {
    return {
      type: 'API_ERROR',
      message: typeof err === 'string' ? err : 'Unknown error',
      retryable: false,
    };
  }

  const message = err.message ?? 'Unknown error';
  switch (err.code) {
    case 429: {
      const retryAfter = err.response?.headers?.['retry-after'];
      const ms = retryAfter ? Number(retryAfter) * 1000 : undefined;
      return { type: 'RATE_LIMIT', message, retryable: true, retry_after_ms: ms };
    }
    case 401:
    case 403:
      return { type: 'AUTH', message, retryable: false };
    case 400:
      return { type: 'VALIDATION', message, retryable: false };
    default:
      return { type: 'API_ERROR', message, retryable: true };
  }
}

export class TaxonomyAwareError extends Error {
  constructor(public readonly taxonomy: TaxonomyError) {
    super(taxonomy.message);
    this.name = 'TaxonomyAwareError';
  }
}
