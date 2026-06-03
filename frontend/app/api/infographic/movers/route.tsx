import { ImageResponse } from 'next/og';
import { createClient } from '@supabase/supabase-js';
import { loadBrandFonts, INFOGRAPHIC_CACHE_CONTROL } from '../_shared/assets';
import { COLORS, platformDims } from '../_shared/theme';
import { Frame, Header, RankRow, StatBlock } from '../_shared/components';

export const runtime = 'edge';

interface MoverTeam {
  team_name: string;
  club_name: string;
  state_code: string;
  rank_change: number;
  current_rank: number;
}

async function getMoversData(ageGroup?: string, gender?: string, limit = 5) {
  const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);
  const { data: climbersData } = await supabase.rpc('get_biggest_movers', {
    p_days: 7,
    p_limit: limit,
    p_direction: 'up',
    p_age_group: ageGroup || null,
    p_gender: gender || null,
  });
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

function MoverSection({
  title,
  color,
  teams,
  isStory,
  climber,
}: {
  title: string;
  color: string;
  teams: MoverTeam[];
  isStory: boolean;
  climber: boolean;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: isStory ? 10 : 7 }}>
      <div
        style={{
          display: 'flex',
          fontFamily: 'Oswald',
          fontWeight: 700,
          fontSize: isStory ? 28 : 23,
          color,
          letterSpacing: 2,
        }}
      >
        {title}
      </div>
      {teams.map((team, i) => (
        <RankRow
          key={i}
          rank={team.current_rank}
          accent={null}
          teamName={team.team_name.toUpperCase()}
          club={[team.club_name, team.state_code].filter(Boolean).join(' • ')}
          isStory={isStory}
        >
          <StatBlock
            value={`${climber ? '+' : '-'}${Math.abs(team.rank_change)}`}
            label="THIS WK"
            color={color}
            isStory={isStory}
            width={isStory ? 120 : 96}
          />
        </RankRow>
      ))}
    </div>
  );
}

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const platform = searchParams.get('platform') || 'instagram';
  const ageGroup = searchParams.get('age_group') || undefined;
  const gender = searchParams.get('gender') || undefined;
  const limit = Math.min(parseInt(searchParams.get('limit') || '5') || 5, 10);

  const isStory = platform === 'story';
  const isLandscape = platform === 'twitter';
  const d = platformDims(platform);

  const [{ climbers, fallers }, fonts] = await Promise.all([
    getMoversData(ageGroup, gender, limit),
    loadBrandFonts(origin),
  ]);

  const genderLabel = gender === 'female' ? 'GIRLS' : 'BOYS';
  const ageLabel = ageGroup?.toUpperCase() || 'ALL AGES';
  const dateStr = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

  return new ImageResponse(
    <Frame isStory={isStory}>
      <Header
        origin={origin}
        isStory={isStory}
        title="BIGGEST MOVERS"
        subtitle={`${ageLabel} ${genderLabel} • Week of ${dateStr}`}
      />
      <div
        style={{
          display: 'flex',
          flexDirection: isLandscape ? 'row' : 'column',
          flex: 1,
          gap: isLandscape ? 24 : isStory ? 28 : 20,
        }}
      >
        <MoverSection title="CLIMBERS" color={COLORS.climber} teams={climbers} isStory={isStory} climber={true} />
        <MoverSection title="FALLERS" color={COLORS.faller} teams={fallers} isStory={isStory} climber={false} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', marginTop: isStory ? 28 : 18 }}>
        <div style={{ display: 'flex', height: 2, background: COLORS.divider, marginBottom: 16 }} />
        <div style={{ display: 'flex', justifyContent: 'center', fontSize: isStory ? 20 : 17, color: COLORS.club }}>
          pitchrank.io/rankings
        </div>
      </div>
    </Frame>,
    { width: d.width, height: d.height, fonts, headers: { 'Cache-Control': INFOGRAPHIC_CACHE_CONTROL } }
  );
}
