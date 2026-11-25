import { NextResponse } from 'next/server';
import { getPromotionStatus } from '@/lib/promotions.server';

// A build-time render would freeze serverNow, which the browser's countdown and boundaries run on.
export const dynamic = 'force-dynamic';

/**
 * GET is intentionally public: the sale is marketing copy, and the coupon id never leaves the
 * server. The browser corrects its clock with `serverNow` plus the response's `Age`, so the 30s
 * CDN cache does not run a countdown late.
 */
export async function GET() {
  const { state, promotion } = getPromotionStatus();
  return NextResponse.json(
    { state, promotion, serverNow: Date.now() },
    { headers: { 'Cache-Control': 'public, s-maxage=30' } }
  );
}
