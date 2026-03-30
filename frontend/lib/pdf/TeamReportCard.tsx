import React from 'react';
import {
  Document,
  Page,
  View,
  Text,
  Link,
  StyleSheet,
  Font,
} from '@react-pdf/renderer';

// Register fonts via Google Fonts CDN
Font.register({
  family: 'Oswald',
  fonts: [
    {
      src: 'https://fonts.gstatic.com/s/oswald/v53/TK3_WkUHHAIjg75cFRf3bXL8LICs1_FvsUZiYA.ttf',
      fontWeight: 400,
    },
    {
      src: 'https://fonts.gstatic.com/s/oswald/v53/TK3_WkUHHAIjg75cFRf3bXL8LICs18NvsUZiYA.ttf',
      fontWeight: 700,
    },
  ],
});

Font.register({
  family: 'DM Sans',
  fonts: [
    {
      src: 'https://fonts.gstatic.com/s/dmsans/v15/rP2Hp2ywxg089UriI5-g4vlH9VoD8Cmcqbu0-K4.ttf',
      fontWeight: 400,
    },
    {
      src: 'https://fonts.gstatic.com/s/dmsans/v15/rP2Hp2ywxg089UriI5-g4vlH9VoD8CmcqbuN_K4.ttf',
      fontWeight: 700,
    },
  ],
});

// --- Colors (from brand/creative-kit.md) ---
const C = {
  forestGreen: '#0B5345',
  lightGreen: '#1a6b5c',
  electricYellow: '#F4D03F',
  white: '#FFFFFF',
  nearBlack: '#1a1a1a',
  lightGray: '#F3F4F6',
  mediumGray: '#6B7280',
  borderGray: '#E5E7EB',
  winGreen: '#10B981',
  lossRed: '#EF4444',
  drawGray: '#9CA3AF',
};

// --- Shared styles ---
const s = StyleSheet.create({
  page: {
    fontFamily: 'DM Sans',
    fontSize: 10,
    color: C.nearBlack,
    backgroundColor: C.white,
    paddingTop: 30,
    paddingBottom: 30,
    paddingHorizontal: 36,
  },
  // Header
  headerBar: {
    backgroundColor: C.forestGreen,
    paddingVertical: 14,
    paddingHorizontal: 20,
    marginBottom: 16,
    marginHorizontal: -36,
    marginTop: -30,
  },
  brandName: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 20,
    color: C.electricYellow,
    letterSpacing: 2,
  },
  headerSubtitle: {
    fontFamily: 'Oswald',
    fontWeight: 400,
    fontSize: 11,
    color: C.white,
    marginTop: 2,
    letterSpacing: 1,
  },
  teamNameRow: {
    marginBottom: 4,
    marginTop: 12,
  },
  teamName: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 22,
    color: C.forestGreen,
  },
  teamMeta: {
    fontSize: 9,
    color: C.mediumGray,
    marginBottom: 14,
  },
  // Section
  sectionTitle: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 11,
    color: C.forestGreen,
    letterSpacing: 1,
    marginBottom: 8,
    textTransform: 'uppercase' as const,
  },
  divider: {
    borderBottomWidth: 1,
    borderBottomColor: C.borderGray,
    marginVertical: 10,
  },
  // Ranking Overview
  rankRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  rankBox: {
    width: '30%',
    alignItems: 'center',
    backgroundColor: C.lightGray,
    borderRadius: 6,
    paddingVertical: 10,
    paddingHorizontal: 6,
  },
  rankNumber: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 32,
    color: C.forestGreen,
  },
  rankLabel: {
    fontSize: 8,
    color: C.mediumGray,
    marginTop: 2,
    textAlign: 'center',
  },
  rankChange: {
    fontSize: 8,
    marginTop: 2,
  },
  // PowerScore bar
  scoreBarOuter: {
    height: 14,
    backgroundColor: C.borderGray,
    borderRadius: 7,
    marginTop: 4,
    marginBottom: 2,
    overflow: 'hidden',
  },
  scoreBarInner: {
    height: 14,
    backgroundColor: C.forestGreen,
    borderRadius: 7,
  },
  scoreLabel: {
    fontSize: 9,
    color: C.mediumGray,
  },
  scoreBold: {
    fontWeight: 700,
    color: C.nearBlack,
  },
  // Strength bars
  strengthRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  strengthLabel: {
    width: 60,
    fontSize: 9,
    color: C.mediumGray,
  },
  strengthBarOuter: {
    flex: 1,
    height: 10,
    backgroundColor: C.borderGray,
    borderRadius: 5,
    overflow: 'hidden',
    marginRight: 8,
  },
  strengthBarInner: {
    height: 10,
    borderRadius: 5,
  },
  strengthValue: {
    width: 30,
    fontSize: 9,
    fontWeight: 700,
    textAlign: 'right',
  },
  // Record boxes
  recordRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  recordBox: {
    width: '23%',
    alignItems: 'center',
    backgroundColor: C.lightGray,
    borderRadius: 4,
    paddingVertical: 6,
  },
  recordNumber: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 18,
    color: C.nearBlack,
  },
  recordLabel: {
    fontSize: 7,
    color: C.mediumGray,
    marginTop: 1,
    textTransform: 'uppercase' as const,
  },
  // Recent results table
  gameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 4,
    borderBottomWidth: 0.5,
    borderBottomColor: C.borderGray,
  },
  gameDate: {
    width: 60,
    fontSize: 8,
    color: C.mediumGray,
  },
  gameOpponent: {
    flex: 1,
    fontSize: 9,
  },
  gameScore: {
    width: 40,
    fontSize: 9,
    fontWeight: 700,
    textAlign: 'center',
  },
  gameBadge: {
    width: 18,
    fontSize: 8,
    fontWeight: 700,
    textAlign: 'center',
    borderRadius: 3,
    paddingVertical: 1,
    color: C.white,
  },
  // Premium CTA
  ctaBox: {
    backgroundColor: C.forestGreen,
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 18,
    marginTop: 12,
  },
  ctaTitle: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 12,
    color: C.electricYellow,
    marginBottom: 6,
    letterSpacing: 1,
  },
  ctaText: {
    fontSize: 8.5,
    color: C.white,
    lineHeight: 1.5,
    marginBottom: 2,
  },
  ctaButton: {
    backgroundColor: C.electricYellow,
    borderRadius: 4,
    paddingVertical: 6,
    paddingHorizontal: 16,
    alignSelf: 'flex-start',
    marginTop: 8,
  },
  ctaButtonText: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 10,
    color: C.forestGreen,
    letterSpacing: 0.5,
  },
  ctaSmall: {
    fontSize: 7,
    color: C.lightGreen,
    marginTop: 4,
  },
  // Footer
  footer: {
    marginTop: 'auto',
    paddingTop: 8,
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

// --- Helper components ---

function RankChangeText({ change }: { change: number | null }) {
  if (change == null || change === 0) return <Text style={[s.rankChange, { color: C.mediumGray }]}>—</Text>;
  const isUp = change > 0;
  return (
    <Text style={[s.rankChange, { color: isUp ? C.winGreen : C.lossRed }]}>
      {isUp ? `▲${change}` : `▼${Math.abs(change)}`} 30d
    </Text>
  );
}

function StrengthBar({ label, value, color }: { label: string; value: number | null; color?: string }) {
  const v = value ?? 0;
  const pct = Math.round(v * 100);
  return (
    <View style={s.strengthRow}>
      <Text style={s.strengthLabel}>{label}</Text>
      <View style={s.strengthBarOuter}>
        <View style={[s.strengthBarInner, { width: `${pct}%`, backgroundColor: color || C.forestGreen }]} />
      </View>
      <Text style={s.strengthValue}>{v.toFixed(2)}</Text>
    </View>
  );
}

function ResultBadge({ result }: { result: string }) {
  const colorMap: Record<string, string> = {
    W: C.winGreen,
    L: C.lossRed,
    D: C.drawGray,
    U: C.mediumGray,
  };
  return (
    <Text style={[s.gameBadge, { backgroundColor: colorMap[result] || C.mediumGray }]}>
      {result}
    </Text>
  );
}

function FormIndicator({ perf }: { perf: number | null }) {
  if (perf == null) return null;
  let label: string;
  let color: string;
  if (perf > 0.05) {
    label = '▲ Overperforming';
    color = C.winGreen;
  } else if (perf < -0.05) {
    label = '▼ Underperforming';
    color = C.lossRed;
  } else {
    label = '● On Track';
    color = C.mediumGray;
  }
  return <Text style={{ fontSize: 8, color, marginTop: 2 }}>{label}</Text>;
}

// --- Props ---

export interface ReportCardGame {
  game_date: string;
  opponent_name: string;
  score: string;
  result: 'W' | 'L' | 'D' | 'U';
}

export interface ReportCardProps {
  team: {
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
  cohortTotal: number;
  stateCohortTotal: number;
  generatedDate: string;
}

// --- Document ---

export function TeamReportCard({
  team,
  ranking,
  games,
  cohortTotal,
  stateCohortTotal,
  generatedDate,
}: ReportCardProps) {
  const percentile = Math.round((1 - ranking.rank_in_cohort_final / cohortTotal) * 100);
  const genderLabel = team.gender === 'M' || team.gender === 'B' ? 'Boys' : 'Girls';
  const winPct = ranking.win_percentage != null
    ? `${Math.round(ranking.win_percentage)}%`
    : ranking.total_games_played > 0
      ? `${Math.round(((ranking.total_wins + 0.5 * ranking.total_draws) / ranking.total_games_played) * 100)}%`
      : '—';

  return (
    <Document>
      <Page size="LETTER" style={s.page}>
        {/* Header bar */}
        <View style={s.headerBar}>
          <Text style={s.brandName}>PITCHRANK</Text>
          <Text style={s.headerSubtitle}>TEAM REPORT CARD</Text>
        </View>

        {/* Team identity */}
        <View style={s.teamNameRow}>
          <Text style={s.teamName}>{team.team_name}</Text>
        </View>
        <Text style={s.teamMeta}>
          {team.club_name ? `${team.club_name} · ` : ''}
          {team.state ? `${team.state.toUpperCase()} · ` : ''}
          U{team.age} {genderLabel} · Generated {generatedDate}
        </Text>

        {/* Ranking Overview */}
        <Text style={s.sectionTitle}>Ranking Overview</Text>
        <View style={s.rankRow}>
          <View style={s.rankBox}>
            <Text style={s.rankNumber}>#{ranking.rank_in_cohort_final}</Text>
            <Text style={s.rankLabel}>National Rank{'\n'}of {cohortTotal} teams</Text>
            <RankChangeText change={ranking.rank_change_30d} />
          </View>
          {ranking.rank_in_state_final != null && (
            <View style={s.rankBox}>
              <Text style={s.rankNumber}>#{ranking.rank_in_state_final}</Text>
              <Text style={s.rankLabel}>State Rank{'\n'}of {stateCohortTotal} in {team.state?.toUpperCase()}</Text>
              <RankChangeText change={ranking.rank_change_state_30d} />
            </View>
          )}
          <View style={s.rankBox}>
            <Text style={[s.rankNumber, { fontSize: 24 }]}>{ranking.power_score_final.toFixed(2)}</Text>
            <Text style={s.rankLabel}>PowerScore</Text>
            <Text style={[s.rankChange, { color: C.forestGreen }]}>Top {percentile > 0 ? percentile : 1}%</Text>
          </View>
        </View>

        {/* PowerScore bar */}
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 2 }}>
          <Text style={s.scoreLabel}>PowerScore</Text>
          <Text style={[s.scoreLabel, s.scoreBold]}>{ranking.power_score_final.toFixed(2)}</Text>
        </View>
        <View style={s.scoreBarOuter}>
          <View style={[s.scoreBarInner, { width: `${Math.round(ranking.power_score_final * 100)}%` }]} />
        </View>

        <View style={s.divider} />

        {/* Strength Profile */}
        <Text style={s.sectionTitle}>Strength Profile</Text>
        <StrengthBar label="Offense" value={ranking.offense_norm} />
        <StrengthBar label="Defense" value={ranking.defense_norm} />
        <StrengthBar label="Schedule" value={ranking.sos_norm} color={C.lightGreen} />

        <View style={s.divider} />

        {/* Season Record */}
        <Text style={s.sectionTitle}>Season Record</Text>
        <View style={s.recordRow}>
          <View style={s.recordBox}>
            <Text style={s.recordNumber}>{ranking.games_played}</Text>
            <Text style={s.recordLabel}>Games</Text>
          </View>
          <View style={s.recordBox}>
            <Text style={[s.recordNumber, { color: C.winGreen }]}>{ranking.wins}</Text>
            <Text style={s.recordLabel}>Wins</Text>
          </View>
          <View style={s.recordBox}>
            <Text style={[s.recordNumber, { color: C.lossRed }]}>{ranking.losses}</Text>
            <Text style={s.recordLabel}>Losses</Text>
          </View>
          <View style={s.recordBox}>
            <Text style={s.recordNumber}>{ranking.draws}</Text>
            <Text style={s.recordLabel}>Draws</Text>
          </View>
        </View>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 2 }}>
          <Text style={{ fontSize: 9 }}>
            Win Rate: <Text style={{ fontWeight: 700 }}>{winPct}</Text>
          </Text>
          <Text style={{ fontSize: 9, color: C.mediumGray }}>
            Career: {ranking.total_wins}-{ranking.total_losses}-{ranking.total_draws} ({ranking.total_games_played} games)
          </Text>
        </View>
        <FormIndicator perf={ranking.perf_centered} />

        <View style={s.divider} />

        {/* Recent Results */}
        {games.length > 0 && (
          <>
            <Text style={s.sectionTitle}>Recent Results</Text>
            {games.map((g, i) => (
              <View key={i} style={s.gameRow}>
                <Text style={s.gameDate}>{g.game_date}</Text>
                <Text style={s.gameOpponent}>{g.opponent_name}</Text>
                <Text style={s.gameScore}>{g.score}</Text>
                <ResultBadge result={g.result} />
              </View>
            ))}
          </>
        )}

        {/* Premium CTA */}
        <View style={s.ctaBox}>
          <Text style={s.ctaTitle}>WANT THE FULL PICTURE?</Text>
          <Text style={s.ctaText}>{'✓ Head-to-head team comparisons'}</Text>
          <Text style={s.ctaText}>{'✓ Predictive matchup analytics'}</Text>
          <Text style={s.ctaText}>{'✓ 90-day ranking trend charts'}</Text>
          <Text style={s.ctaText}>{'✓ Strength of schedule deep-dives'}</Text>
          <Text style={s.ctaText}>{'✓ Weekly ranking alerts for your team'}</Text>
          <Link src="https://pitchrank.io/upgrade">
            <View style={s.ctaButton}>
              <Text style={s.ctaButtonText}>Start Your Free Trial</Text>
            </View>
          </Link>
          <Text style={s.ctaSmall}>7 days free · $6.99/mo · Cancel anytime</Text>
        </View>

        {/* Footer */}
        <View style={s.footer}>
          <Text style={s.footerText}>
            Rankings powered by PitchRank&apos;s 13-layer algorithm · 25,000+ teams · Updated weekly
          </Text>
          <Text style={s.footerText}>pitchrank.io</Text>
        </View>
      </Page>
    </Document>
  );
}
