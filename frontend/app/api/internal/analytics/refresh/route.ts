import { NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/supabase/admin';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  // Cache invalidation handled by client-side refetch or dedicated cache layer
  return NextResponse.json({ ok: true, refreshed_at: new Date().toISOString() });
}
