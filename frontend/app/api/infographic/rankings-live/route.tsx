import { ImageResponse } from 'next/og';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { createClient } from '@supabase/supabase-js';
import { loadBrandFonts, INFOGRAPHIC_CACHE_CONTROL } from '../_shared/assets';
import { COLORS, platformDims } from '../_shared/theme';
import { Frame, Header, Footer } from '../_shared/components';

export const runtime = 'edge';

async function getActiveTeamCount(): Promise<number> {
  const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);

  // Same RPC the pipeline uses for the Monday caption, so caption and graphic
  // always show the same number.
  const { data, error } = await supabase.rpc('get_national_active_count');
  if (error || typeof data !== 'number') return 0;
  return data;
}

export async function GET(request: Request) {
  // CPU-heavy public image rendering - throttle to limit denial-of-wallet
  if (!checkRateLimit(`infographic:${getClientIp(request)}`, 10, 60_000)) {
    return new Response('Too many requests', { status: 429 });
  }

  const { searchParams, origin } = new URL(request.url);
  const platform = searchParams.get('platform') || 'instagram';
  const isStory = platform === 'story';
  const d = platformDims(platform);

  const [count, fonts] = await Promise.all([getActiveTeamCount(), loadBrandFonts(origin)]);
  const dateStr = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

  return new ImageResponse(
    <Frame isStory={isStory}>
      <Header origin={origin} isStory={isStory} title="NEW RANKINGS ARE LIVE" subtitle={`Week of ${dateStr}`} />
      <div
        style={{ display: 'flex', flexDirection: 'column', flex: 1, alignItems: 'center', justifyContent: 'center' }}
      >
        {count > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div
              style={{
                display: 'flex',
                fontFamily: 'Oswald',
                fontWeight: 700,
                fontSize: isStory ? 160 : 130,
                color: COLORS.electricYellow,
              }}
            >
              {count.toLocaleString('en-US')}
            </div>
            <div
              style={{
                display: 'flex',
                fontFamily: 'Oswald',
                fontWeight: 700,
                fontSize: isStory ? 44 : 36,
                color: COLORS.brightWhite,
                letterSpacing: 4,
                marginTop: 8,
              }}
            >
              TEAMS RANKED
            </div>
          </div>
        ) : (
          <div
            style={{
              display: 'flex',
              fontFamily: 'Oswald',
              fontWeight: 700,
              fontSize: isStory ? 64 : 52,
              color: COLORS.brightWhite,
              letterSpacing: 3,
            }}
          >
            WHERE DOES YOUR TEAM STAND?
          </div>
        )}
        <div style={{ display: 'flex', fontSize: isStory ? 24 : 20, color: COLORS.date, marginTop: 36 }}>
          Updated every Monday from real game data
        </div>
      </div>
      <Footer isStory={isStory} />
    </Frame>,
    { width: d.width, height: d.height, fonts, headers: { 'Cache-Control': INFOGRAPHIC_CACHE_CONTROL } }
  );
}
