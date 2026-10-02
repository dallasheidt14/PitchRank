import { ImageResponse } from 'next/og';
import { checkRateLimit, getClientIp } from '@/lib/api/rateLimit';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { isValidUuid } from '@/lib/validation';
import { loadBrandFonts, wordmarkUrl, INFOGRAPHIC_CACHE_CONTROL } from '../_shared/assets';
import { COLORS } from '../_shared/theme';
import {
  buildTeamCard,
  tallyRecord,
  type TeamCard,
  type TeamCardRanking,
  type TeamGame,
  type TeamCardRow,
} from './card';

export const runtime = 'edge';

// Open Graph's standard canvas. Not in DIMENSIONS: that map is the social posting
// sizes, and this image is only ever a link preview.
const SIZE = { width: 1200, height: 630 };

async function getTeamCard(id: string): Promise<TeamCard | null> {
  const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);

  // rankings_full leaves state_rank NULL — the views compute display ranks — so the
  // state rank comes from the RPC that lib/api.getTeam falls back to, which counts on
  // rankings_full instead of scanning state_rankings_view's ROW_NUMBER window.
  const [teamResult, rankingResult, stateRankResult] = await Promise.all([
    supabase
      .from('teams')
      .select('team_name, club_name, league, distinction, state_code, age_group, gender')
      .eq('team_id_master', id)
      .maybeSingle(),
    supabase
      .from('rankings_full')
      .select('rank_in_cohort_final, power_score_final, total_wins, total_losses, total_draws')
      .eq('team_id', id)
      .maybeSingle(),
    supabase.rpc('get_team_state_rank', { p_team_id: id }).maybeSingle(),
  ]);

  if (!teamResult.data) return null;

  const stateRank = (stateRankResult.data as { state_rank: number } | null)?.state_rank ?? null;
  const ranking = (rankingResult.data as TeamCardRanking | null) ?? (await recordFromGames(supabase, id));
  return buildTeamCard(teamResult.data as TeamCardRow, ranking, stateRank);
}

/**
 * The W-L-D of a team the ranking pipeline has no row for.
 *
 * The team page renders for any team with a non-excluded game, while rankings_full holds only
 * teams that completed the pipeline, so a quarter of playable teams reach this. Mirrors what
 * lib/api.getTeam computes for the page itself, merged team ids included, so the card and the
 * page it previews cannot disagree. One team's fixtures sit far below the PostgREST row cap.
 */
async function recordFromGames(supabase: SupabaseClient, id: string): Promise<TeamCardRanking> {
  const { data: mergeRows } = await supabase
    .from('team_merge_map')
    .select('deprecated_team_id')
    .eq('canonical_team_id', id);

  const merged = ((mergeRows ?? []) as { deprecated_team_id: string | null }[]).flatMap(
    (row) => row.deprecated_team_id ?? []
  );
  const teamIds = [id, ...merged];

  const { data: games } = await supabase
    .from('games')
    .select('home_team_master_id, home_score, away_score')
    .or(teamIds.map((teamId) => `home_team_master_id.eq.${teamId},away_team_master_id.eq.${teamId}`).join(','))
    .eq('is_excluded', false)
    .not('home_score', 'is', null)
    .not('away_score', 'is', null);

  return tallyRecord((games ?? []) as TeamGame[], teamIds);
}

export async function GET(request: Request) {
  // CPU-heavy public image rendering - throttle to limit denial-of-wallet. This route is a
  // far wider target than the other infographics: they have a handful of fixed URLs, while
  // every team is a valid address here, and the CDN cache only absorbs repeats of the same
  // one. A real unfurler fetches a couple of teams a minute, so this bounds a scripted walk
  // without ever throttling a share.
  if (!checkRateLimit(`infographic:${getClientIp(request)}`, 20, 60_000)) {
    return new Response('Too many requests', { status: 429 });
  }

  const { origin, searchParams } = new URL(request.url);
  const id = searchParams.get('id');
  if (!id || !isValidUuid(id)) return new Response('Missing or malformed id', { status: 400 });

  const [card, fonts] = await Promise.all([getTeamCard(id), loadBrandFonts(origin)]);
  if (!card) return new Response('Team not found', { status: 404 });

  return new ImageResponse(
    <div
      style={{
        position: 'relative',
        display: 'flex',
        width: '100%',
        height: '100%',
        background: `linear-gradient(135deg, ${COLORS.forestGreen} 0%, ${COLORS.darkGreen} 100%)`,
        fontFamily: 'DM Sans, sans-serif',
      }}
    >
      {/* Pitch arcs, echoing the centre circle on the rankings OG image. */}
      <div
        style={{
          position: 'absolute',
          top: -186,
          right: -164,
          display: 'flex',
          width: 640,
          height: 640,
          borderRadius: '50%',
          border: '3px solid rgba(244, 208, 63, 0.09)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          top: 232,
          right: -320,
          display: 'flex',
          width: 420,
          height: 420,
          borderRadius: '50%',
          border: '3px solid rgba(244, 208, 63, 0.06)',
        }}
      />

      {/* The slab's skewed edge is the slash from the logo mark. */}
      <div
        style={{
          position: 'absolute',
          top: -46,
          left: -78,
          display: 'flex',
          width: 490,
          height: 722,
          background: COLORS.electricYellow,
          transform: 'skewX(-6deg)',
        }}
      />

      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          backgroundImage:
            'repeating-linear-gradient(0deg, rgba(255,255,255,0.022) 0px, rgba(255,255,255,0.022) 1px, rgba(0,0,0,0) 1px, rgba(0,0,0,0) 3px)',
        }}
      />

      <div
        style={{
          position: 'relative',
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          width: 424,
          height: 630,
        }}
      >
        {/* A rank ("#4") fits the 424px slab at full size; the record fallback ("14-2-1") does not. */}
        <div
          style={{
            display: 'flex',
            fontFamily: 'Oswald',
            fontWeight: 700,
            fontSize: card.hero.length > 4 ? 148 : 228,
            lineHeight: 1,
            letterSpacing: card.hero.length > 4 ? -6 : -12,
            color: COLORS.darkGreen,
          }}
        >
          {card.hero}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', marginTop: 10 }}>
          <div
            style={{
              flexShrink: 0,
              display: 'flex',
              width: 26,
              height: 5,
              background: COLORS.forestGreen,
              marginRight: 14,
              transform: 'skewX(-14deg)',
            }}
          />
          <div
            style={{
              display: 'flex',
              fontFamily: 'Oswald',
              fontWeight: 700,
              fontSize: 44,
              letterSpacing: 4,
              color: COLORS.forestGreen,
            }}
          >
            {card.heroLabel}
          </div>
          <div
            style={{
              flexShrink: 0,
              display: 'flex',
              width: 26,
              height: 5,
              background: COLORS.forestGreen,
              marginLeft: 14,
              transform: 'skewX(-14deg)',
            }}
          />
        </div>
      </div>

      <div
        style={{
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          // flexBasis auto would size this column to its widest line, and Yoga has no
          // min-width:auto floor to pull it back — the name, the chip and the URL all
          // overflow off the right edge. Basis 0 takes exactly what the slab leaves.
          flexGrow: 1,
          flexBasis: 0,
          minWidth: 0,
          padding: '50px 60px 44px 68px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={wordmarkUrl(origin)} width={214} height={38} alt="" />
          {card.cohort ? (
            <div
              style={{
                flexShrink: 0,
                display: 'flex',
                alignItems: 'center',
                padding: '9px 20px',
                border: '2px solid rgba(244, 208, 63, 0.42)',
                borderRadius: 999,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  fontFamily: 'Oswald',
                  fontWeight: 600,
                  fontSize: 27,
                  letterSpacing: 3,
                  color: COLORS.electricYellow,
                }}
              >
                {card.cohort}
              </div>
            </div>
          ) : null}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div
            style={{
              display: 'flex',
              fontFamily: 'Oswald',
              fontWeight: 700,
              fontSize: card.nameSize,
              lineHeight: 1.04,
              letterSpacing: -1,
              color: COLORS.brightWhite,
              // fitNameSize estimates from a mean glyph advance; clip rather than let a
              // miss push the cohort chip and the stat rail off the canvas.
              maxHeight: 250,
              overflow: 'hidden',
            }}
          >
            {card.displayName}
          </div>
          <div style={{ display: 'flex', fontSize: 33, fontWeight: 500, color: COLORS.club, marginTop: 16 }}>
            {card.subtitle}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 10 }}>
            <div
              style={{
                display: 'flex',
                fontFamily: 'Oswald',
                fontWeight: 600,
                fontSize: 28,
                letterSpacing: 2,
                color: COLORS.club,
              }}
            >
              PITCHRANK.IO
            </div>
          </div>
          <div style={{ display: 'flex', height: 3, background: COLORS.divider, marginBottom: 22 }} />
          {card.ranked ? (
            <div style={{ display: 'flex', alignItems: 'flex-end' }}>
              <StatColumn value={card.record} label="RECORD" color={COLORS.brightWhite} width={226} />
              <StatColumn value={card.nationalRank} label="NATIONAL" color={COLORS.brightWhite} width={210} />
              <StatColumn value={card.powerScore} label="POWERSCORE" color={COLORS.electricYellow} />
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <div
                  style={{
                    flexShrink: 0,
                    display: 'flex',
                    width: 16,
                    height: 16,
                    borderRadius: '50%',
                    background: COLORS.electricYellow,
                    marginRight: 18,
                  }}
                />
                <div
                  style={{
                    display: 'flex',
                    fontFamily: 'Oswald',
                    fontWeight: 700,
                    fontSize: 48,
                    letterSpacing: 2,
                    color: COLORS.brightWhite,
                    whiteSpace: 'nowrap',
                  }}
                >
                  RANKING SOON
                </div>
              </div>
              <div
                style={{
                  display: 'flex',
                  fontSize: 27,
                  fontWeight: 500,
                  color: COLORS.club,
                  marginTop: 8,
                  marginLeft: 34,
                }}
              >
                Boards update Mondays
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    { ...SIZE, fonts, headers: { 'Cache-Control': INFOGRAPHIC_CACHE_CONTROL } }
  );
}

// The trailing column takes the remaining width. Satori throws on a style key whose value
// is undefined, so an absent width is omitted rather than passed through.
function StatColumn({ value, label, color, width }: { value: string; label: string; color: string; width?: number }) {
  return (
    <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', ...(width ? { width } : {}) }}>
      <div style={{ display: 'flex', fontFamily: 'Oswald', fontWeight: 700, fontSize: 58, lineHeight: 1, color }}>
        {value}
      </div>
      <div
        style={{ display: 'flex', fontSize: 25, fontWeight: 700, letterSpacing: 3, color: COLORS.club, marginTop: 6 }}
      >
        {label}
      </div>
    </div>
  );
}
