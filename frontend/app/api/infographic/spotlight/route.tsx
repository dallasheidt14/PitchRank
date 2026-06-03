import { ImageResponse } from 'next/og';
import { createClient } from '@supabase/supabase-js';
import { loadBrandFonts, INFOGRAPHIC_CACHE_CONTROL } from '../_shared/assets';
import { COLORS, platformDims, formatScore, formatRecord } from '../_shared/theme';
import { Frame, Header, StatBlock } from '../_shared/components';

export const runtime = 'edge';

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
  const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);
  const { data } = await supabase.rpc('get_biggest_movers', {
    p_days: 7,
    p_limit: 1,
    p_direction: 'up',
    p_age_group: null,
    p_gender: null,
  });
  if (!data || data.length === 0) return null;
  const top = data[0] as Pick<
    SpotlightTeam,
    'team_name' | 'club_name' | 'state_code' | 'rank_change' | 'current_rank'
  > & {
    team_id: string;
  };

  // get_biggest_movers returns only rank fields — enrich record / score / win% from the
  // view by team_id. win_percentage arrives as a 0-100 numeric string (PostgREST).
  const { data: statsRows } = await supabase
    .from('state_rankings_view')
    .select('power_score_final, total_wins, total_losses, total_draws, win_percentage')
    .eq('team_id_master', top.team_id)
    .limit(1);
  const s = (statsRows?.[0] as Record<string, unknown> | undefined) ?? undefined;

  return {
    team_name: top.team_name,
    club_name: top.club_name,
    state_code: top.state_code,
    rank_change: top.rank_change,
    current_rank: top.current_rank,
    power_score: (s?.power_score_final as number | undefined) ?? undefined,
    wins: (s?.total_wins as number | undefined) ?? undefined,
    losses: (s?.total_losses as number | undefined) ?? undefined,
    draws: (s?.total_draws as number | undefined) ?? undefined,
    win_pct: s?.win_percentage != null ? Number(s.win_percentage) : undefined, // 0-100
  };
}

export async function GET(request: Request) {
  const { origin, searchParams } = new URL(request.url);
  const platform = searchParams.get('platform') || 'instagram';
  const isStory = platform === 'story';
  const d = platformDims(platform);

  const [team, fonts] = await Promise.all([getSpotlightTeam(), loadBrandFonts(origin)]);
  if (!team) return new Response('No team data available', { status: 404 });

  const dateStr = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
  const clubLine = [team.club_name, team.state_code].filter(Boolean).join(' • ');
  const record = team.wins != null ? formatRecord(team.wins, team.losses, team.draws) : '--';
  const winPct = team.win_pct != null ? `${Math.round(team.win_pct)}%` : '--';

  return new ImageResponse(
    <Frame isStory={isStory}>
      <Header origin={origin} isStory={isStory} title="TEAM OF THE WEEK" subtitle={`Week of ${dateStr}`} />

      <div
        style={{ display: 'flex', flexDirection: 'column', flex: 1, alignItems: 'center', justifyContent: 'center' }}
      >
        {/* Rank badge */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: isStory ? 180 : 150,
            height: isStory ? 180 : 150,
            borderRadius: '50%',
            background: COLORS.electricYellow,
            marginBottom: 28,
          }}
        >
          <div
            style={{
              display: 'flex',
              fontFamily: 'Oswald',
              fontWeight: 700,
              fontSize: isStory ? 76 : 64,
              color: COLORS.darkGreen,
            }}
          >
            {`#${team.current_rank}`}
          </div>
        </div>

        {/* Team name */}
        <div
          style={{
            display: 'flex',
            fontFamily: 'Oswald',
            fontWeight: 700,
            fontSize: isStory ? 54 : 44,
            color: COLORS.brightWhite,
            textAlign: 'center',
            maxWidth: '92%',
          }}
        >
          {team.team_name.toUpperCase()}
        </div>
        <div style={{ display: 'flex', fontSize: isStory ? 26 : 22, color: COLORS.club, marginTop: 8 }}>{clubLine}</div>

        {/* Change pill */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            background: 'rgba(123,227,139,0.18)',
            borderRadius: 999,
            padding: '10px 26px',
            marginTop: 26,
          }}
        >
          <div
            style={{
              display: 'flex',
              fontWeight: 700,
              fontSize: isStory ? 26 : 22,
              color: COLORS.climber,
              letterSpacing: 1,
            }}
          >
            {`+${Math.abs(team.rank_change)} SPOTS THIS WEEK`}
          </div>
        </div>

        {/* Stats */}
        <div style={{ display: 'flex', gap: isStory ? 56 : 44, marginTop: 40 }}>
          <StatBlock
            value={record}
            label="RECORD"
            color={COLORS.brightWhite}
            isStory={isStory}
            width={isStory ? 150 : 130}
          />
          <StatBlock
            value={formatScore(team.power_score)}
            label="SCORE"
            color={COLORS.electricYellow}
            isStory={isStory}
            width={isStory ? 150 : 130}
          />
          <StatBlock
            value={winPct}
            label="WIN %"
            color={COLORS.brightWhite}
            isStory={isStory}
            width={isStory ? 150 : 130}
          />
        </div>
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
