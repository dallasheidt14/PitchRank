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
  // Raw upstream error text stays in server logs; clients get the taxonomy
  // label and a fixed description only
  if (!isGoogleLikeError(err)) {
    console.error('[internal-analytics] Upstream error:', err);
    return {
      type: 'API_ERROR',
      message: 'Upstream analytics request failed',
      retryable: false,
    };
  }

  console.error(`[internal-analytics] Google API error ${err.code}:`, err.message);
  switch (err.code) {
    case 429: {
      const retryAfter = err.response?.headers?.['retry-after'];
      const ms = retryAfter ? Number(retryAfter) * 1000 : undefined;
      return { type: 'RATE_LIMIT', message: 'Google API rate limit reached', retryable: true, retry_after_ms: ms };
    }
    case 401:
    case 403:
      return { type: 'AUTH', message: 'Google API authorization failed', retryable: false };
    case 400:
      return { type: 'VALIDATION', message: 'Google API rejected the request', retryable: false };
    default:
      return { type: 'API_ERROR', message: 'Google API request failed', retryable: true };
  }
}

export class TaxonomyAwareError extends Error {
  constructor(public readonly taxonomy: TaxonomyError) {
    super(taxonomy.message);
    this.name = 'TaxonomyAwareError';
  }
}
