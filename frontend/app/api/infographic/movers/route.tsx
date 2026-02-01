import { ImageResponse } from 'next/og';
import { createClient } from '@supabase/supabase-js';

export const runtime = 'edge';

const BRAND_COLORS = {
  forestGreen: '#1B4D3E',
  darkGreen: '#0D2818',
  brightWhite: '#FFFFFF',
  gold: '#FFD700',
  climberGreen: '#4CAF50',
  fallerRed: '#F44336',
};

interface MoverTeam {
  team_name: string;
  club_name: string;
  state_code: string;
  rank_change: number;
  current_rank: number;
}

async function getMoversData(ageGroup?: string, gender?: string, limit: number = 5) {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;
  
  const supabase = createClient(supabaseUrl, supabaseKey);

  // Get climbers
  const { data: climbersData } = await supabase.rpc('get_biggest_movers', {
    p_days: 7,
    p_limit: limit,
    p_direction: 'up',
    p_age_group: ageGroup || null,
    p_gender: gender || null,
  });

  // Get fallers
  const { data: fallersData } = await supabase.rpc('get_biggest_movers', {
    p_days: 7,
    p_limit: limit,
    p_direction: 'down',
    p_age_group: ageGroup || null,
    p_gender: gender || null,
  });

  return {
    climbers: (climbersData || []) as MoverTeam[],
    fallers: (fallersData || []) as MoverTeam[],
  };
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const platform = searchParams.get('platform') || 'instagram'; // instagram, twitter, story
  const ageGroup = searchParams.get('age_group') || undefined;
  const gender = searchParams.get('gender') || undefined;
  const limit = parseInt(searchParams.get('limit') || '5');

  // Platform dimensions
  const dimensions = {
    instagram: { width: 1080, height: 1080 },
    twitter: { width: 1200, height: 675 },
    story: { width: 1080, height: 1920 },
  }[platform] || { width: 1080, height: 1080 };

  // Mock data for now (will use real data once RPC is set up)
  const climbers: MoverTeam[] = [
    { team_name: 'Lockhart United SC 2014', club_name: 'Lockhart YSA', state_code: 'TX', rank_change: 2255, current_rank: 1038 },
    { team_name: 'Premier ECNL RL 2013', club_name: 'NCFC Youth', state_code: 'NC', rank_change: 2111, current_rank: 957 },
    { team_name: 'Corte Madera FC White', club_name: 'Corte Madera FC', state_code: 'CA', rank_change: 2102, current_rank: 1309 },
    { team_name: 'North Marin United 2014', club_name: 'North Marin United', state_code: 'CA', rank_change: 2094, current_rank: 1273 },
    { team_name: 'CF 2012 South Black', club_name: 'Concorde Fire', state_code: 'GA', rank_change: 2093, current_rank: 1217 },
  ].slice(0, limit);

  const fallers: MoverTeam[] = [
    { team_name: 'Premier 2014', club_name: 'Keystone FC', state_code: 'PA', rank_change: -2255, current_rank: 3972 },
    { team_name: 'PA Classic Academy', club_name: 'PA Classics', state_code: 'PA', rank_change: -2185, current_rank: 3274 },
    { team_name: 'LVU Rush PRE-ECNL', club_name: 'Lehigh Valley United', state_code: 'PA', rank_change: -2179, current_rank: 3247 },
    { team_name: 'PRE-ECNL 2014', club_name: 'PSA Monmouth', state_code: 'NJ', rank_change: -2160, current_rank: 3934 },
    { team_name: 'Philadelphia SC Surf', club_name: 'Philadelphia SC', state_code: 'PA', rank_change: -2124, current_rank: 2834 },
  ].slice(0, limit);

  const genderLabel = gender === 'female' ? 'GIRLS' : 'BOYS';
  const ageLabel = ageGroup?.toUpperCase() || 'ALL AGES';
  const dateStr = new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  const isSquare = platform === 'instagram';
  const isStory = platform === 'story';

  return new ImageResponse(
    (
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
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 30 }}>
          <div style={{ fontSize: isStory ? 28 : 24, color: BRAND_COLORS.gold, fontWeight: 'bold', letterSpacing: 4 }}>
            PITCHRANK
          </div>
          <div style={{ fontSize: isStory ? 48 : isSquare ? 42 : 36, color: BRAND_COLORS.brightWhite, fontWeight: 'bold', marginTop: 10 }}>
            BIGGEST MOVERS
          </div>
          <div style={{ fontSize: isStory ? 22 : 18, color: 'rgba(255,255,255,0.8)', marginTop: 8 }}>
            {ageLabel} {genderLabel} • Week of {dateStr}
          </div>
        </div>

        {/* Content */}
        <div style={{ display: 'flex', flexDirection: isStory ? 'column' : 'row', flex: 1, gap: 30 }}>
          {/* Climbers */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div style={{ fontSize: isStory ? 26 : 22, color: BRAND_COLORS.climberGreen, fontWeight: 'bold', marginBottom: 16, display: 'flex', alignItems: 'center' }}>
              🚀 CLIMBERS
            </div>
            {climbers.map((team, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  background: 'rgba(76, 175, 80, 0.15)',
                  borderLeft: `4px solid ${BRAND_COLORS.climberGreen}`,
                  borderRadius: 8,
                  padding: '12px 16px',
                  marginBottom: 10,
                }}
              >
                <div style={{ fontSize: isStory ? 28 : 24, fontWeight: 'bold', color: BRAND_COLORS.climberGreen, marginRight: 16, minWidth: 70 }}>
                  +{team.rank_change}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <div style={{ fontSize: isStory ? 18 : 16, color: BRAND_COLORS.brightWhite, fontWeight: 'bold' }}>
                    {team.team_name}
                  </div>
                  <div style={{ fontSize: isStory ? 14 : 12, color: 'rgba(255,255,255,0.7)' }}>
                    {team.club_name} • {team.state_code} • #{team.current_rank}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Fallers */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div style={{ fontSize: isStory ? 26 : 22, color: BRAND_COLORS.fallerRed, fontWeight: 'bold', marginBottom: 16, display: 'flex', alignItems: 'center' }}>
              📉 FALLERS
            </div>
            {fallers.map((team, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  background: 'rgba(244, 67, 54, 0.15)',
                  borderLeft: `4px solid ${BRAND_COLORS.fallerRed}`,
                  borderRadius: 8,
                  padding: '12px 16px',
                  marginBottom: 10,
                }}
              >
                <div style={{ fontSize: isStory ? 28 : 24, fontWeight: 'bold', color: BRAND_COLORS.fallerRed, marginRight: 16, minWidth: 70 }}>
                  {team.rank_change}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <div style={{ fontSize: isStory ? 18 : 16, color: BRAND_COLORS.brightWhite, fontWeight: 'bold' }}>
                    {team.team_name}
                  </div>
                  <div style={{ fontSize: isStory ? 14 : 12, color: 'rgba(255,255,255,0.7)' }}>
                    {team.club_name} • {team.state_code} • #{team.current_rank}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 20 }}>
          <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.6)' }}>
            pitchrank.io • #YouthSoccer #Rankings
          </div>
        </div>
      </div>
    ),
    {
      width: dimensions.width,
      height: dimensions.height,
    }
  );
}
