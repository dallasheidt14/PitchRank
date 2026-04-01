import { ImageResponse } from 'next/og';
import { createClient } from '@supabase/supabase-js';

export const runtime = 'edge';

const BRAND_COLORS = {
  forestGreen: '#1B4D3E',
  darkGreen: '#0D2818',
  brightWhite: '#FFFFFF',
  gold: '#FFD700',
};

const MEDAL_COLORS = ['#FFD700', '#C0C0C0', '#CD7F32'];

interface StateTeam {
  team_name: string;
  club_name: string;
  power_score: number;
  current_rank: number;
}

async function getStateTopTeams(state: string, limit: number = 5): Promise<StateTeam[]> {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

  const supabase = createClient(supabaseUrl, supabaseKey);

  const { data } = await supabase
    .from('rankings_full')
    .select('team_name, club_name, power_score, current_rank')
    .eq('state_code', state)
    .neq('status', 'Not Enough Ranked Games')
    .order('power_score', { ascending: false })
    .limit(limit);

  return (data || []) as StateTeam[];
}

// Map state codes to full names
const STATE_NAMES: Record<string, string> = {
  TX: 'TEXAS',
  CA: 'CALIFORNIA',
  FL: 'FLORIDA',
  NJ: 'NEW JERSEY',
  GA: 'GEORGIA',
  CO: 'COLORADO',
  NY: 'NEW YORK',
  IL: 'ILLINOIS',
  MD: 'MARYLAND',
  VA: 'VIRGINIA',
  PA: 'PENNSYLVANIA',
  OH: 'OHIO',
  NC: 'NORTH CAROLINA',
  MI: 'MICHIGAN',
  AZ: 'ARIZONA',
  WA: 'WASHINGTON',
  MA: 'MASSACHUSETTS',
  MN: 'MINNESOTA',
  CT: 'CONNECTICUT',
  SC: 'SOUTH CAROLINA',
  TN: 'TENNESSEE',
  MO: 'MISSOURI',
  IN: 'INDIANA',
  WI: 'WISCONSIN',
};

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const state = searchParams.get('state') || 'TX';
  const platform = searchParams.get('platform') || 'instagram';

  const dimensions = {
    instagram: { width: 1080, height: 1080 },
    twitter: { width: 1200, height: 675 },
    story: { width: 1080, height: 1920 },
  }[platform] || { width: 1080, height: 1080 };

  const teams = await getStateTopTeams(state);
  const stateName = STATE_NAMES[state] || state;
  const dateStr = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  const isStory = platform === 'story';
  const isSquare = platform === 'instagram';

  return new ImageResponse(
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: `linear-gradient(135deg, ${BRAND_COLORS.forestGreen} 0%, ${BRAND_COLORS.darkGreen} 100%)`,
        padding: isStory ? 60 : 50,
        fontFamily: 'Arial, sans-serif',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: isStory ? 50 : 30 }}>
        <div style={{ fontSize: isStory ? 28 : 24, color: BRAND_COLORS.gold, fontWeight: 'bold', letterSpacing: 4 }}>
          PITCHRANK
        </div>
        <div
          style={{
            fontSize: isStory ? 52 : isSquare ? 46 : 38,
            fontWeight: 'bold',
            color: BRAND_COLORS.brightWhite,
            marginTop: 10,
          }}
        >
          {stateName} RANKINGS
        </div>
        <div style={{ fontSize: isStory ? 24 : 20, color: 'rgba(255,255,255,0.8)', marginTop: 8 }}>
          Top 5 Teams • Week of {dateStr}
        </div>
      </div>

      {/* Team List */}
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: isStory ? 16 : 12 }}>
        {teams.map((team, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              background: i < 3 ? `rgba(255, 215, 0, ${0.15 - i * 0.04})` : 'rgba(255,255,255,0.08)',
              borderLeft: `4px solid ${i < 3 ? MEDAL_COLORS[i] : 'rgba(255,255,255,0.3)'}`,
              borderRadius: 12,
              padding: isStory ? '20px 24px' : '16px 20px',
            }}
          >
            {/* Rank Number */}
            <div
              style={{
                fontSize: isStory ? 36 : 30,
                fontWeight: 'bold',
                color: i < 3 ? MEDAL_COLORS[i] : 'rgba(255,255,255,0.5)',
                minWidth: isStory ? 60 : 50,
              }}
            >
              {i + 1}
            </div>

            {/* Team Info */}
            <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
              <div style={{ fontSize: isStory ? 22 : 18, fontWeight: 'bold', color: BRAND_COLORS.brightWhite }}>
                {team.team_name}
              </div>
              <div style={{ fontSize: isStory ? 16 : 14, color: 'rgba(255,255,255,0.6)' }}>
                {team.club_name} • National #{team.current_rank}
              </div>
            </div>

            {/* PowerScore Badge */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                background: 'rgba(255, 215, 0, 0.15)',
                borderRadius: 10,
                padding: isStory ? '12px 16px' : '8px 14px',
              }}
            >
              <div style={{ fontSize: isStory ? 24 : 20, fontWeight: 'bold', color: BRAND_COLORS.gold }}>
                {team.power_score?.toFixed(1) ?? '--'}
              </div>
              <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', letterSpacing: 1 }}>PS</div>
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: isStory ? 40 : 20 }}>
        <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.6)' }}>
          pitchrank.io/rankings • #{stateName.toLowerCase().replace(' ', '')}soccer
        </div>
      </div>
    </div>,
    {
      width: dimensions.width,
      height: dimensions.height,
    }
  );
}
