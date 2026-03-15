import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * Instagram Handle Review Queue API
 *
 * GET:  Returns needs_review club-level handles grouped by handle (one row per club).
 * POST: Approve or reject a handle — updates all team rows sharing that handle.
 */

function getServiceClient() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_KEY;

  if (!supabaseUrl || !serviceKey) {
    throw new Error('Missing Supabase environment variables');
  }

  return createClient(supabaseUrl, serviceKey);
}

function extractClubName(queryUsed: string | null): string {
  if (!queryUsed) return 'Unknown';
  const match = queryUsed.match(/^[^"]*"([^"]+)"/);
  return match?.[1] ?? 'Unknown';
}

export async function GET() {
  try {
    const supabase = getServiceClient();

    const allRows: Array<{
      handle: string;
      confidence_score: number;
      query_used: string | null;
      profile_url: string | null;
    }> = [];

    let offset = 0;
    const PAGE_SIZE = 1000;

    while (true) {
      const { data, error } = await supabase
        .from('team_social_profiles')
        .select('handle, confidence_score, query_used, profile_url')
        .eq('platform', 'instagram')
        .eq('profile_level', 'club')
        .eq('review_status', 'needs_review')
        .range(offset, offset + PAGE_SIZE - 1);

      if (error) {
        console.error('[instagram-review] GET error:', error.message);
        return NextResponse.json({ error: error.message }, { status: 500 });
      }

      if (!data || data.length === 0) break;
      allRows.push(...data);
      if (data.length < PAGE_SIZE) break;
      offset += PAGE_SIZE;
    }

    const grouped = new Map<
      string,
      { handle: string; club_name: string; confidence: number; team_count: number; profile_url: string | null }
    >();

    for (const row of allRows) {
      if (!row.handle) continue;
      const existing = grouped.get(row.handle);
      if (existing) {
        existing.team_count++;
      } else {
        grouped.set(row.handle, {
          handle: row.handle,
          club_name: extractClubName(row.query_used),
          confidence: Number(row.confidence_score) || 0,
          team_count: 1,
          profile_url: row.profile_url,
        });
      }
    }

    const items = Array.from(grouped.values()).sort(
      (a, b) => b.team_count - a.team_count || b.confidence - a.confidence,
    );

    return NextResponse.json({ items, total: items.length });
  } catch (error) {
    console.error('[instagram-review] Unexpected error:', error);
    return NextResponse.json({ error: 'An unexpected error occurred' }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const supabase = getServiceClient();

    let body: { handle?: string; action?: string };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ error: 'Invalid request body' }, { status: 400 });
    }

    const { handle, action } = body;

    if (!handle || !action || !['approve', 'reject'].includes(action)) {
      return NextResponse.json(
        { error: 'Required: { handle: string, action: "approve" | "reject" }' },
        { status: 400 },
      );
    }

    const newStatus = action === 'approve' ? 'auto_approved' : 'rejected';

    const { data, error } = await supabase
      .from('team_social_profiles')
      .update({ review_status: newStatus, last_checked_at: new Date().toISOString() })
      .eq('handle', handle)
      .eq('platform', 'instagram')
      .eq('profile_level', 'club')
      .eq('review_status', 'needs_review')
      .select('id');

    if (error) {
      console.error('[instagram-review] POST error:', error.message);
      return NextResponse.json({ error: error.message }, { status: 500 });
    }

    return NextResponse.json({
      success: true,
      handle,
      action,
      updated: data?.length ?? 0,
    });
  } catch (error) {
    console.error('[instagram-review] Unexpected error:', error);
    return NextResponse.json({ error: 'An unexpected error occurred' }, { status: 500 });
  }
}
