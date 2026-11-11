import path from 'path';
import React from 'react';
import { Document, Page, View, Text, Link, StyleSheet, Font, Svg, Polygon } from '@react-pdf/renderer';
import { BASE_URL, US_STATES, formatGender } from '@/lib/constants';
import { backToRankingsPath, formatPowerScore } from '@/lib/utils';
import {
  PREMIUM_BENEFITS,
  LAST_GAMES_SHOWN,
  TRIAL_TERMS,
  formatRankMovement,
  formatRecentRecord,
  reportCardUpgradeUrl,
  reportFooter,
  stateDisplayName,
  topPercent,
} from '@/lib/reports/report-card';

// Register fonts from local files in public/fonts/. Files originate from
// @fontsource/oswald and @fontsource/dm-sans (pinned npm deps); they were
// copied into public/fonts/ so Vercel function bundles ship them directly,
// without relying on a runtime fetch from fonts.gstatic.com.
const fontDir = path.join(process.cwd(), 'public/fonts');

Font.register({
  family: 'Oswald',
  fonts: [
    { src: path.join(fontDir, 'Oswald-Regular.woff'), fontWeight: 400 },
    { src: path.join(fontDir, 'Oswald-Bold.woff'), fontWeight: 700 },
  ],
});

Font.register({
  family: 'DM Sans',
  fonts: [
    { src: path.join(fontDir, 'DMSans-Regular.woff'), fontWeight: 400 },
    { src: path.join(fontDir, 'DMSans-Bold.woff'), fontWeight: 700 },
  ],
});

// --- Colors (brand green and yellow from brand/creative-kit.md) ---
const C = {
  forestGreen: '#0B5345',
  electricYellow: '#F4D03F',
  white: '#FFFFFF',
  nearBlack: '#1a1a1a',
  lightGray: '#F3F4F6',
  mediumGray: '#6B7280',
  borderGray: '#E5E7EB',
  paleGreen: '#cfe3dc',
  winGreen: '#10B981',
  lossRed: '#EF4444',
  drawGray: '#9CA3AF',
};

const s = StyleSheet.create({
  page: {
    fontFamily: 'DM Sans',
    fontSize: 10,
    color: C.nearBlack,
    backgroundColor: C.white,
    paddingTop: 0,
    paddingBottom: 16,
    paddingHorizontal: 32,
  },
  // Brand bar
  brandBar: {
    backgroundColor: C.forestGreen,
    paddingVertical: 10,
    paddingHorizontal: 24,
    marginHorizontal: -32,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  brandName: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 16,
    color: C.electricYellow,
    letterSpacing: 2,
  },
  brandTag: {
    fontFamily: 'Oswald',
    fontWeight: 400,
    fontSize: 9,
    color: C.white,
    letterSpacing: 2,
  },
  // Team identity
  teamBlock: {
    marginTop: 12,
    marginBottom: 10,
  },
  teamName: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 22,
    color: C.forestGreen,
    letterSpacing: 0.5,
    lineHeight: 1.15,
  },
  teamMeta: {
    fontSize: 9,
    color: C.mediumGray,
    marginTop: 3,
  },
  // Stat boxes (ranks, PowerScore, record)
  statRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 8,
  },
  statBox: {
    flex: 1,
    backgroundColor: C.lightGray,
    borderRadius: 6,
    padding: 10,
  },
  statLabel: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 8,
    color: C.mediumGray,
    letterSpacing: 1.5,
    marginBottom: 2,
  },
  statValue: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 28,
    color: C.forestGreen,
    lineHeight: 1.15,
  },
  recordValue: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 24,
    color: C.nearBlack,
    lineHeight: 1.15,
  },
  statSub: {
    fontSize: 9,
    color: C.mediumGray,
    marginTop: 3,
  },
  movementRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 4,
  },
  movementText: {
    flex: 1,
    fontSize: 9,
    fontWeight: 700,
  },
  // Last 5 games
  sectionTitle: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 10,
    color: C.forestGreen,
    letterSpacing: 1.5,
    marginBottom: 6,
    textTransform: 'uppercase' as const,
  },
  gameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    borderBottomWidth: 1,
    borderBottomColor: C.borderGray,
  },
  gameDate: {
    width: 50,
    fontSize: 9,
    color: C.mediumGray,
  },
  gameOpponent: {
    flex: 1,
    fontSize: 9.5,
    maxLines: 1,
    textOverflow: 'ellipsis',
  },
  gameScore: {
    width: 40,
    fontSize: 9.5,
    fontWeight: 700,
    textAlign: 'right',
    marginRight: 10,
  },
  resultBadge: {
    width: 18,
    height: 18,
    borderRadius: 9,
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 9,
    color: C.white,
    textAlign: 'center',
    paddingTop: 3,
  },
  noGames: {
    fontSize: 9,
    color: C.mediumGray,
  },
  // Premium CTA
  ctaBox: {
    backgroundColor: C.forestGreen,
    borderRadius: 6,
    paddingVertical: 12,
    paddingHorizontal: 18,
    marginTop: 8,
  },
  ctaKicker: {
    fontFamily: 'Oswald',
    fontWeight: 400,
    fontSize: 8,
    color: C.electricYellow,
    letterSpacing: 1.5,
    marginBottom: 3,
    maxLines: 1,
    textOverflow: 'ellipsis',
  },
  ctaTitle: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 14,
    color: C.white,
    marginBottom: 8,
  },
  ctaBenefit: {
    fontSize: 9.5,
    color: C.white,
    marginBottom: 3,
  },
  ctaButton: {
    backgroundColor: C.electricYellow,
    borderRadius: 4,
    paddingVertical: 7,
    paddingHorizontal: 16,
    alignSelf: 'flex-start',
    marginTop: 8,
  },
  ctaButtonText: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 10,
    color: C.forestGreen,
    letterSpacing: 0.8,
  },
  ctaSmall: {
    fontSize: 8,
    color: C.paleGreen,
    marginTop: 5,
  },
  // Share invitation
  shareBox: {
    marginTop: 8,
    borderWidth: 1,
    borderColor: C.borderGray,
    borderRadius: 6,
    padding: 10,
  },
  shareTitle: {
    fontSize: 9.5,
    fontWeight: 700,
    marginBottom: 2,
  },
  shareText: {
    fontSize: 8.5,
    color: C.mediumGray,
    lineHeight: 1.4,
  },
  shareLink: {
    color: C.forestGreen,
    fontWeight: 700,
    textDecoration: 'none',
  },
  // Footer
  footer: {
    marginTop: 8,
    paddingTop: 6,
    borderTopWidth: 1,
    borderTopColor: C.borderGray,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  footerText: {
    fontSize: 7,
    color: C.mediumGray,
  },
});

const RESULT_COLORS: Record<ReportCardGame['result'], string> = {
  W: C.winGreen,
  L: C.lossRed,
  D: C.drawGray,
  U: C.mediumGray,
};

const CTA_TEAM_NAME_MAX = 40;

// --- Helpers ---

// Neither font has ▲/▼ (U+25B2/U+25BC), so the triangle is drawn rather than typed.
function RankMovement({ change }: { change: number | null }) {
  const text = formatRankMovement(change);
  if (text == null || change == null) return null;
  const color = change > 0 ? C.winGreen : C.lossRed;
  return (
    <View style={s.movementRow}>
      <Svg width={8} height={8} viewBox="0 0 10 10">
        <Polygon points={change > 0 ? '5,0 10,9 0,9' : '0,1 10,1 5,10'} fill={color} />
      </Svg>
      <Text style={[s.movementText, { color }]}>{text}</Text>
    </View>
  );
}

function GameRow({ game }: { game: ReportCardGame }) {
  return (
    <View style={s.gameRow}>
      <Text style={s.gameDate}>{game.game_date}</Text>
      <Text style={s.gameOpponent}>{game.opponent_name}</Text>
      <Text style={s.gameScore}>{game.score}</Text>
      <Text style={[s.resultBadge, { backgroundColor: RESULT_COLORS[game.result] }]}>{game.result}</Text>
    </View>
  );
}

// --- Props ---

export interface ReportCardGame {
  game_date: string;
  opponent_name: string;
  score: string;
  result: 'W' | 'L' | 'D' | 'U';
}

export interface ReportCardNextGame {
  game_date: string;
  opponent_name: string;
}

export interface ReportCardProps {
  team: {
    team_id_master: string;
    team_name: string;
    club_name: string | null;
    state: string | null;
    age: number;
    gender: string;
  };
  ranking: {
    power_score_final: number;
    rank_in_cohort_final: number;
    rank_in_state_final: number | null;
    offense_norm: number | null;
    defense_norm: number | null;
    sos_norm: number;
    rank_change_7d: number | null;
    rank_change_30d: number | null;
    rank_change_state_7d: number | null;
    rank_change_state_30d: number | null;
    perf_centered: number | null;
    wins: number;
    losses: number;
    draws: number;
    games_played: number;
    total_wins: number;
    total_losses: number;
    total_draws: number;
    total_games_played: number;
    win_percentage: number | null;
  };
  games: ReportCardGame[];
  nextGame: ReportCardNextGame | null;
  cohortTotal: number | null;
  stateCohortTotal: number | null;
  rankingsAsOf: string | null;
  generatedDate: string;
  gamesLabel: string;
}

// --- Document ---

export function TeamReportCard({
  team,
  ranking,
  games,
  nextGame,
  cohortTotal,
  stateCohortTotal,
  rankingsAsOf,
  generatedDate,
  gamesLabel,
}: ReportCardProps) {
  const genderLabel = formatGender(team.gender);
  const cohortLabel = `U${team.age} ${genderLabel}`;
  const stateName = team.state ? US_STATES.find((st) => st.code === team.state?.toLowerCase())?.name : undefined;
  const stateLabel = stateDisplayName(team.state);
  const winPct =
    ranking.games_played > 0
      ? `${Math.round(((ranking.wins + 0.5 * ranking.draws) / ranking.games_played) * 100)}%`
      : '—';
  const boardPath = backToRankingsPath({ region: null, ageGroup: null, gender: null }, team);
  const upgradeUrl = reportCardUpgradeUrl(team.team_id_master, 'pdf');
  // Past this length the name wraps the headline onto a second line; with the longest names also wrapping the
  // header, that pushes the footer onto a second page.
  const ctaTeam = team.team_name.length <= CTA_TEAM_NAME_MAX ? team.team_name : 'your team';

  return (
    <Document>
      <Page size="LETTER" style={s.page}>
        {/* Brand strip */}
        <View style={s.brandBar}>
          <Text style={s.brandName}>PITCHRANK</Text>
          <Text style={s.brandTag}>TEAM REPORT CARD</Text>
        </View>

        {/* Team identity */}
        <View style={s.teamBlock}>
          <Text style={s.teamName}>{team.team_name}</Text>
          <Text style={s.teamMeta}>
            {team.club_name ? `${team.club_name} · ` : ''}
            {team.state ? `${team.state.toUpperCase()} · ` : ''}
            {cohortLabel}
          </Text>
          <Text style={s.teamMeta}>
            {rankingsAsOf ? `Rankings as of ${rankingsAsOf} · ` : ''}Report created {generatedDate}
          </Text>
        </View>

        {/* National rank, state rank, PowerScore */}
        <View style={s.statRow}>
          <View style={s.statBox}>
            <Text style={s.statLabel}>NATIONAL RANK</Text>
            <Text style={s.statValue}>#{ranking.rank_in_cohort_final}</Text>
            <Text style={s.statSub}>
              {cohortTotal != null
                ? `of ${cohortTotal.toLocaleString()} ${cohortLabel} teams · Top ${topPercent(ranking.rank_in_cohort_final, cohortTotal)}%`
                : `${cohortLabel} teams nationally`}
            </Text>
            <RankMovement change={ranking.rank_change_30d} />
          </View>
          {ranking.rank_in_state_final != null && stateLabel && (
            <View style={s.statBox}>
              <Text style={s.statLabel}>{stateLabel.toUpperCase()} RANK</Text>
              <Text style={s.statValue}>#{ranking.rank_in_state_final}</Text>
              <Text style={s.statSub}>
                {stateCohortTotal != null ? `of ${stateCohortTotal.toLocaleString()} ` : ''}
                {cohortLabel} teams in {stateLabel}
              </Text>
            </View>
          )}
          <View style={s.statBox}>
            <Text style={s.statLabel}>POWERSCORE</Text>
            <Text style={s.statValue}>{formatPowerScore(ranking.power_score_final)}</Text>
            <Text style={s.statSub}>Same score shown on pitchrank.io</Text>
          </View>
        </View>

        {/* Record */}
        <View style={s.statRow}>
          <View style={s.statBox}>
            <Text style={s.statLabel}>RECENT RECORD</Text>
            <Text style={s.recordValue}>{formatRecentRecord(ranking)}</Text>
            <Text style={s.statSub}>
              Last {ranking.games_played} ranked games · {winPct} win rate (draws count half)
            </Text>
          </View>
        </View>

        {/* Last 5 games */}
        <Text style={s.sectionTitle}>Last {LAST_GAMES_SHOWN} games · most recent first</Text>
        {games.length > 0 ? (
          games.slice(0, LAST_GAMES_SHOWN).map((g, i) => <GameRow key={i} game={g} />)
        ) : (
          <Text style={s.noGames}>No scored games yet</Text>
        )}

        {/* Premium CTA */}
        <View style={s.ctaBox}>
          <Text style={s.ctaKicker}>
            {nextGame
              ? `NEXT UP: VS ${nextGame.opponent_name.toUpperCase()} · ${nextGame.game_date.toUpperCase()}`
              : 'PITCHRANK+'}
          </Text>
          <Text style={s.ctaTitle}>
            {nextGame ? `How does ${ctaTeam} match up?` : `See how ${ctaTeam} stacks up against any opponent`}
          </Text>
          {PREMIUM_BENEFITS.map((benefit) => (
            <Text key={benefit} style={s.ctaBenefit}>
              • {benefit}
            </Text>
          ))}
          <Link src={upgradeUrl}>
            <View style={s.ctaButton}>
              <Text style={s.ctaButtonText}>START YOUR FREE 7-DAY TRIAL</Text>
            </View>
          </Link>
          <Text style={s.ctaSmall}>{TRIAL_TERMS}</Text>
        </View>

        {/* Share invitation */}
        <View style={s.shareBox}>
          <Text style={s.shareTitle}>Share this with your team chat</Text>
          <Text style={s.shareText}>
            Other parents can get a free report for their own team at{' '}
            <Link src={`${BASE_URL}/report-card`} style={s.shareLink}>
              pitchrank.io/report-card
            </Link>
            . See the full {cohortLabel} {stateName ?? 'national'} rankings at{' '}
            <Link src={`${BASE_URL}${boardPath}`} style={s.shareLink}>
              {`pitchrank.io${boardPath}`}
            </Link>
            .
          </Text>
        </View>

        {/* Footer */}
        <View style={s.footer}>
          <Text style={s.footerText}>{reportFooter(gamesLabel)}</Text>
          <Text style={s.footerText}>pitchrank.io</Text>
        </View>
      </Page>
    </Document>
  );
}
