import { ImageResponse } from 'next/og';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { createClient } from '@supabase/supabase-js';
import { loadBrandFonts, INFOGRAPHIC_CACHE_CONTROL } from '../_shared/assets';
import { COLORS, MEDAL, platformDims, formatScore, formatRecord } from '../_shared/theme';
import { Frame, Header, RankRow, StatBlock } from '../_shared/components';

export const runtime = 'edge';

interface StateTeam {
  team_name: string;
  club_name: string;
  power_score: number;
  rank: number;
  wins: number;
  losses: number;
  draws: number;
}

async function getStateTopTeams(state: string, age: string, gender: string, limit = 10): Promise<StateTeam[]> {
  const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);

  // get_state_rankings filters to the (state, age, gender) cohort and computes a clean
  // per-cohort rank (rank_in_state_final) before limiting — the same RPC the rankings
  // pages use. It also returns provisional 'Not Enough Ranked Games' teams (rank null)
  // interleaved by power; over-fetch and keep only ranked ('Active') teams so a
  // provisional/unmatched team never appears in a public Top 10 with a fabricated rank.
  const { data } = await supabase.rpc('get_state_rankings', {
    p_state: state.toUpperCase(),
    p_age: age,
    p_gender: gender,
    p_limit: limit + 45,
    p_offset: 0,
  });

  return ((data || []) as Array<Record<string, unknown>>)
    .filter((row) => row.status === 'Active' && row.rank_in_state_final != null)
    .slice(0, limit)
    .map((row) => ({
      team_name: (row.team_name as string) ?? '',
      club_name: (row.club_name as string) ?? '',
      power_score: (row.power_score_final as number) ?? 0,
      rank: row.rank_in_state_final as number,
      wins: (row.total_wins as number) ?? (row.wins as number) ?? 0,
      losses: (row.total_losses as number) ?? (row.losses as number) ?? 0,
      draws: (row.total_draws as number) ?? (row.draws as number) ?? 0,
    }));
}

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
  OK: 'OKLAHOMA',
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
  // CPU-heavy public image rendering - throttle to limit denial-of-wallet
  if (!checkRateLimit(getClientIp(request), 10, 60_000)) {
    return new Response('Too many requests', { status: 429 });
  }

  const { searchParams, origin } = new URL(request.url);
  const state = searchParams.get('state') || 'TX';
  const ageParam = searchParams.get('age') || 'u14';
  const genderParam = searchParams.get('gender') || 'male';
  const platform = searchParams.get('platform') || 'instagram';

  const age = ageParam.replace(/[^0-9]/g, '');
  const isGirls = /^(f|g)/i.test(genderParam);
  const gender = isGirls ? 'F' : 'M';
  const isStory = platform === 'story';
  const d = platformDims(platform);

  const [teams, fonts] = await Promise.all([getStateTopTeams(state, age, gender), loadBrandFonts(origin)]);
  const stateName = STATE_NAMES[state] || state;
  const genderLabel = isGirls ? 'GIRLS' : 'BOYS';
  const dateStr = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

  return new ImageResponse(
    <Frame isStory={isStory}>
      <Header
        origin={origin}
        isStory={isStory}
        title={`TOP 10 U${age} ${genderLabel} IN ${stateName}`}
        subtitle={`Rankings as of ${dateStr}`}
      />
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: isStory ? 12 : 8 }}>
        {teams.map((team, i) => (
          <RankRow
            key={i}
            rank={team.rank}
            accent={i < 3 ? MEDAL[i] : null}
            teamName={team.team_name.toUpperCase()}
            club={team.club_name}
            isStory={isStory}
          >
            <StatBlock
              value={formatRecord(team.wins, team.losses, team.draws)}
              label="W-L-D"
              color={COLORS.brightWhite}
              isStory={isStory}
              width={isStory ? 130 : 110}
            />
            <StatBlock
              value={formatScore(team.power_score)}
              label="SCORE"
              color={COLORS.electricYellow}
              isStory={isStory}
              width={isStory ? 110 : 92}
            />
          </RankRow>
        ))}
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
