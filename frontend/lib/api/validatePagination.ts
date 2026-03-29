import { NextResponse } from 'next/server';

/**
 * Validate and parse limit/offset pagination parameters from search params.
 *
 * Usage:
 *   const pagination = validatePagination(searchParams);
 *   if (pagination.error) return pagination.error;
 *   const { limit, offset } = pagination;
 */
export function validatePagination(
  searchParams: URLSearchParams,
  defaults: { limit?: number; maxLimit?: number } = {}
): { limit: number; offset: number; error: null } | { error: NextResponse } {
  const { limit: defaultLimit = 1000, maxLimit = 5000 } = defaults;

  const limit = parseInt(searchParams.get('limit') || String(defaultLimit), 10);
  const offset = parseInt(searchParams.get('offset') || '0', 10);

  if (isNaN(limit) || limit < 1 || limit > maxLimit) {
    return {
      error: NextResponse.json({ error: `limit must be between 1 and ${maxLimit}` }, { status: 400 }),
    };
  }

  if (isNaN(offset) || offset < 0) {
    return {
      error: NextResponse.json({ error: 'offset must be >= 0' }, { status: 400 }),
    };
  }

  return { limit, offset, error: null };
}
