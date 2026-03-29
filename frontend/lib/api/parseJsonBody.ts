import { NextResponse } from 'next/server';

/**
 * Safely parse JSON from a request body.
 *
 * Usage:
 *   const result = await parseJsonBody(request);
 *   if (result.error) return result.error;
 *   const { deprecatedTeamId } = result.data;
 */
export async function parseJsonBody<T = Record<string, unknown>>(
  request: Request
): Promise<{ data: T; error: null } | { data: null; error: NextResponse }> {
  try {
    const data = (await request.json()) as T;
    return { data, error: null };
  } catch {
    return {
      data: null,
      error: NextResponse.json({ error: 'Invalid request body' }, { status: 400 }),
    };
  }
}
