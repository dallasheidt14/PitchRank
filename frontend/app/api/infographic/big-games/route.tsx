import { ImageResponse } from 'next/og';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { loadBrandFonts, INFOGRAPHIC_CACHE_CONTROL } from '../_shared/assets';
import { COLORS, platformDims } from '../_shared/theme';
import { Frame, Header, Footer } from '../_shared/components';

export const runtime = 'edge';

interface MatchupTeam {
  name: string;
  club: string;
  rank: number;
}

interface Matchup {
  cohort: string;
  day: string;
  home: MatchupTeam;
  away: MatchupTeam;
  state: string;
}

interface BigGamesPayload {
  v: number;
  range: string;
  games: Matchup[];
}

// The pipeline builds the payload with base64.urlsafe_b64encode, whose -/_
// alphabet atob rejects, and club names can carry non-ASCII bytes that atob's
// Latin-1 strings would mangle — translate to standard base64, re-pad, then
// decode the bytes through TextDecoder.
// A real payload (≤5 matchups) encodes to ~1.5KB; cap well above that but far
// below any abuse blob so the decode+parse work on this public CPU-heavy route
// stays bounded.
const MAX_PAYLOAD_CHARS = 8192;

function decodePayload(m: string): BigGamesPayload | null {
  if (m.length > MAX_PAYLOAD_CHARS) return null;
  try {
    const b64 = m.replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const bytes = Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
    const payload = JSON.parse(new TextDecoder().decode(bytes)) as BigGamesPayload;
    if (payload.v !== 1 || !Array.isArray(payload.games) || payload.games.length === 0) return null;
    return payload;
  } catch {
    return null;
  }
}

function TeamBlock({
  team,
  state,
  align,
  isStory,
}: {
  team: MatchupTeam;
  state: string;
  align: 'left' | 'right';
  isStory: boolean;
}) {
  const alignItems = align === 'left' ? 'flex-start' : 'flex-end';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, alignItems, overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex',
          fontFamily: 'Oswald',
          fontWeight: 600,
          fontSize: isStory ? 26 : 22,
          color: COLORS.brightWhite,
          textAlign: align,
        }}
      >
        {team.name.toUpperCase()}
      </div>
      <div style={{ display: 'flex', fontSize: isStory ? 16 : 13, color: COLORS.club, marginTop: 3, textAlign: align }}>
        {team.club}
      </div>
      <div
        style={{
          display: 'flex',
          fontSize: isStory ? 17 : 14,
          fontWeight: 700,
          color: COLORS.electricYellow,
          marginTop: 4,
        }}
      >
        {`#${team.rank} in ${state}`}
      </div>
    </div>
  );
}

function MatchupRow({ matchup, isStory }: { matchup: Matchup; isStory: boolean }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        flex: 1,
        background: COLORS.rowDim,
        borderLeft: `5px solid ${COLORS.rowBorderDim}`,
        borderRadius: 10,
        padding: isStory ? '14px 26px' : '12px 22px',
      }}
    >
      <div
        style={{
          display: 'flex',
          fontFamily: 'Oswald',
          fontWeight: 700,
          fontSize: isStory ? 18 : 15,
          color: COLORS.electricYellow,
          letterSpacing: 2,
        }}
      >
        {`${matchup.cohort} · ${matchup.day}`}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', flex: 1, marginTop: 6 }}>
        <TeamBlock team={matchup.home} state={matchup.state} align="left" isStory={isStory} />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: isStory ? 70 : 60,
            height: isStory ? 70 : 60,
            borderRadius: '50%',
            background: COLORS.electricYellow,
            margin: '0 16px',
            flexShrink: 0,
          }}
        >
          <span
            style={{
              fontFamily: 'Oswald',
              fontSize: isStory ? 26 : 22,
              fontWeight: 700,
              color: COLORS.darkGreen,
            }}
          >
            VS
          </span>
        </div>
        <TeamBlock team={matchup.away} state={matchup.state} align="right" isStory={isStory} />
      </div>
    </div>
  );
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

  const payload = decodePayload(searchParams.get('m') || '');
  if (!payload) return new Response('No matchup data available', { status: 404 });

  const fonts = await loadBrandFonts(origin);
  const games = payload.games.slice(0, 5);

  return new ImageResponse(
    <Frame isStory={isStory}>
      <Header origin={origin} isStory={isStory} title="BIG GAMES THIS WEEKEND" subtitle={payload.range} />
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: isStory ? 14 : 10 }}>
        {games.map((matchup, i) => (
          <MatchupRow key={i} matchup={matchup} isStory={isStory} />
        ))}
      </div>
      <Footer isStory={isStory} />
    </Frame>,
    { width: d.width, height: d.height, fonts, headers: { 'Cache-Control': INFOGRAPHIC_CACHE_CONTROL } }
  );
}
