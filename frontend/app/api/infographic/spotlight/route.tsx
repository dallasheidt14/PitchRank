import { ImageResponse } from 'next/og';
import { createClient } from '@supabase/supabase-js';
import { loadBrandFonts, LOGO_URL, LOGO_WIDTH, LOGO_HEIGHT, INFOGRAPHIC_CACHE_CONTROL } from '../_shared/assets';

export const runtime = 'edge';

const BRAND_COLORS = {
  forestGreen: '#1B4D3E',
  darkGreen: '#0D2818',
  brightWhite: '#FFFFFF',
  gold: '#FFD700',
  climberGreen: '#4CAF50',
};

interface SpotlightTeam {
  team_name: string;
  club_name: string;
  state_code: string;
  rank_change: number;
  current_rank: number;
  power_score?: number;
  wins?: number;
  losses?: number;
  draws?: number;
  win_pct?: number;
}

async function getSpotlightTeam(): Promise<SpotlightTeam | null> {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

  const supabase = createClient(supabaseUrl, supabaseKey);

  const { data } = await supabase.rpc('get_biggest_movers', {
    p_days: 7,
    p_limit: 1,
    p_direction: 'up',
    p_age_group: null,
    p_gender: null,
  });

  if (!data || data.length === 0) return null;
  return data[0] as SpotlightTeam;
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const platform = searchParams.get('platform') || 'instagram';

  const dimensions = {
    instagram: { width: 1080, height: 1080 },
    twitter: { width: 1200, height: 675 },
    story: { width: 1080, height: 1920 },
  }[platform] || { width: 1080, height: 1080 };

  const team = await getSpotlightTeam();

  if (!team) {
    return new Response('No team data available', { status: 404 });
  }

  const dateStr = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  const isStory = platform === 'story';
  const isSquare = platform === 'instagram';
  const record = `${team.wins ?? 0}-${team.losses ?? 0}-${team.draws ?? 0}`;
  const powerScore = team.power_score ? team.power_score.toFixed(1) : '--';
  const winPct = team.win_pct ? `${(team.win_pct * 100).toFixed(0)}%` : '--';

  return new ImageResponse(
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: `linear-gradient(135deg, ${BRAND_COLORS.forestGreen} 0%, ${BRAND_COLORS.darkGreen} 100%)`,
        padding: isStory ? 60 : 50,
        fontFamily: 'DM Sans, sans-serif',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: isStory ? 50 : 30 }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={LOGO_URL}
          width={isStory ? LOGO_WIDTH.story : LOGO_WIDTH.default}
          height={isStory ? LOGO_HEIGHT.story : LOGO_HEIGHT.default}
          alt=""
        />
        <div
          style={{
            fontSize: isStory ? 36 : isSquare ? 30 : 26,
            color: 'rgba(255,255,255,0.8)',
            fontWeight: 'bold',
            fontFamily: 'Oswald',
            marginTop: 8,
            letterSpacing: 2,
          }}
        >
          TEAM OF THE WEEK
        </div>
      </div>

      {/* Rank Badge */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: isStory ? 160 : 140,
          height: isStory ? 160 : 140,
          borderRadius: '50%',
          background: BRAND_COLORS.gold,
          marginBottom: 30,
        }}
      >
        <div style={{ fontSize: isStory ? 64 : 56, fontWeight: 'bold', color: BRAND_COLORS.darkGreen }}>
          {`#${team.current_rank}`}
        </div>
      </div>

      {/* Team Name */}
      <div
        style={{
          fontSize: isStory ? 44 : isSquare ? 40 : 34,
          fontWeight: 'bold',
          color: BRAND_COLORS.brightWhite,
          textAlign: 'center',
          marginBottom: 8,
        }}
      >
        {team.team_name}
      </div>
      <div style={{ fontSize: isStory ? 24 : 20, color: 'rgba(255,255,255,0.7)', marginBottom: 10 }}>
        {[team.club_name, team.state_code].filter(Boolean).join(' • ')}
      </div>

      {/* Change Badge */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          background: 'rgba(76, 175, 80, 0.2)',
          borderRadius: 20,
          padding: '8px 24px',
          marginBottom: isStory ? 50 : 30,
        }}
      >
        <div style={{ fontSize: isStory ? 28 : 24, fontWeight: 'bold', color: BRAND_COLORS.climberGreen }}>
          {`↑ ${Math.abs(team.rank_change)} spots this week`}
        </div>
      </div>

      {/* Stats Row */}
      <div style={{ display: 'flex', gap: isStory ? 40 : 30 }}>
        {[
          { label: 'RECORD', value: record },
          { label: 'POWERSCORE', value: powerScore, highlight: true },
          { label: 'WIN %', value: winPct },
        ].map((stat, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              background: stat.highlight ? 'rgba(255, 215, 0, 0.15)' : 'rgba(255,255,255,0.1)',
              borderRadius: 12,
              padding: isStory ? '20px 30px' : '16px 24px',
              minWidth: isStory ? 140 : 120,
            }}
          >
            <div
              style={{
                fontSize: isStory ? 32 : 28,
                fontWeight: 'bold',
                color: stat.highlight ? BRAND_COLORS.gold : BRAND_COLORS.brightWhite,
              }}
            >
              {stat.value}
            </div>
            <div
              style={{ fontSize: isStory ? 14 : 12, color: 'rgba(255,255,255,0.6)', marginTop: 4, letterSpacing: 1 }}
            >
              {stat.label}
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: isStory ? 50 : 30 }}>
        <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.6)' }}>{`pitchrank.io • Week of ${dateStr}`}</div>
      </div>
    </div>,
    {
      width: dimensions.width,
      height: dimensions.height,
      fonts: await loadBrandFonts(),
      headers: {
        'Cache-Control': INFOGRAPHIC_CACHE_CONTROL,
      },
    }
  );
}
