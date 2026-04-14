import { NextResponse } from 'next/server';
import { revalidateTag } from 'next/cache';
import { requireAdmin } from '@/lib/supabase/admin';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST() {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  revalidateTag('analytics:ga4', 'max');
  revalidateTag('analytics:gsc', 'max');
  return NextResponse.json({ ok: true, refreshed_at: new Date().toISOString() });
}
