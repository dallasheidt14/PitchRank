import { NextRequest, NextResponse } from 'next/server';
import { requirePremium } from '@/lib/api/requirePremium';
import { checkRateLimit } from '@/lib/api/rateLimit';
import { parseJsonBody } from '@/lib/api/parseJsonBody';
import { createServiceSupabase } from '@/lib/supabase/service';
import { isValidUuid } from '@/lib/validation';

export async function POST(request: NextRequest) {
  try {
    // Premium, not admin: the beacon fires from the team page, which middleware.ts
    // already gates to premium, so anyone who can reach this is a subscriber.
    const auth = await requirePremium();
    if (auth.error) return auth.error;
    const { user } = auth;

    // Keyed by user, not IP, matching scrape-missing-game: the caller is
    // authenticated by here, so the cap survives IP rotation. Set well clear of
    // real use — losing a view costs one deduped enqueue, and the daily job reads
    // distinct teams, so a dropped duplicate changes nothing at all.
    if (!checkRateLimit(`track-team-view:${user.id}`, 300, 3_600_000)) {
      return NextResponse.json({ error: 'Too many requests' }, { status: 429 });
    }

    const body = await parseJsonBody<{ teamId?: unknown }>(request);
    if (body.error) return body.error;

    // The type parameter above is an unchecked cast, so the typeof is what actually
    // holds: isValidUuid coerces, and String(['<a valid uuid>']) matches the pattern.
    const { teamId } = body.data;
    if (typeof teamId !== 'string' || !isValidUuid(teamId)) {
      return NextResponse.json({ error: 'Invalid teamId' }, { status: 400 });
    }

    // Service role, and the table grants nothing to anon or authenticated. Writing
    // through the caller's own client would have needed a browser-reachable INSERT
    // grant, and that makes this route optional: a free account could then POST
    // straight to the Data API and skip the premium check above. user_id comes from
    // the session, never from the body, so the row is still honestly attributed.
    const supabase = createServiceSupabase();
    const { error } = await supabase.from('team_page_views').insert({ team_id_master: teamId, user_id: user.id });

    if (error) {
      console.error('[track-team-view] Failed to record view:', error);
      return NextResponse.json({ error: 'Failed to record view' }, { status: 500 });
    }

    return new NextResponse(null, { status: 204 });
  } catch (error) {
    console.error('[track-team-view] Unexpected error:', error);
    return NextResponse.json({ error: 'An unexpected error occurred' }, { status: 500 });
  }
}
