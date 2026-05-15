import path from 'path';
import React from 'react';
import { Document, Page, View, Text, Link, StyleSheet, Font } from '@react-pdf/renderer';
import { formatGender } from '@/lib/constants';

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
  blurGray: '#D1D5DB',
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
    paddingBottom: 24,
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
    marginTop: 14,
    marginBottom: 12,
  },
  teamName: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 22,
    color: C.forestGreen,
    letterSpacing: 0.5,
  },
  teamMeta: {
    fontSize: 9,
    color: C.mediumGray,
    marginTop: 3,
  },
  // Hero stats (PowerScore + Rank)
  heroRow: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 10,
  },
  heroBox: {
    flex: 1,
    backgroundColor: C.lightGray,
    borderRadius: 6,
    padding: 14,
  },
  heroLabel: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 8,
    color: C.mediumGray,
    letterSpacing: 1.5,
    marginBottom: 4,
  },
  heroValue: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 36,
    color: C.forestGreen,
    lineHeight: 1.1,
  },
  heroValueRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 6,
  },
  heroChange: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 12,
  },
  heroSub: {
    fontSize: 9,
    color: C.mediumGray,
    marginTop: 4,
  },
  // Record + Last 5
  midRow: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 14,
  },
  midBox: {
    flex: 1,
    backgroundColor: C.lightGray,
    borderRadius: 6,
    padding: 12,
  },
  midLabel: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 8,
    color: C.mediumGray,
    letterSpacing: 1.5,
    marginBottom: 4,
  },
  recordValue: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 22,
    color: C.nearBlack,
  },
  recordSub: {
    fontSize: 9,
    color: C.mediumGray,
    marginTop: 2,
  },
  formRow: {
    flexDirection: 'row',
    gap: 6,
    marginTop: 2,
  },
  formBadge: {
    width: 22,
    height: 22,
    borderRadius: 11,
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 11,
    color: C.white,
    textAlign: 'center',
    lineHeight: 1.8,
  },
  // Section
  sectionTitle: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 10,
    color: C.forestGreen,
    letterSpacing: 1.5,
    marginBottom: 8,
    textTransform: 'uppercase' as const,
  },
  divider: {
    borderBottomWidth: 1,
    borderBottomColor: C.borderGray,
    marginVertical: 12,
  },
  // Locked premium teasers (2x2 grid)
  lockedSection: {
    marginBottom: 10,
  },
  lockedGridRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 10,
  },
  lockedCard: {
    flex: 1,
    backgroundColor: C.lightGray,
    borderRadius: 6,
    padding: 12,
    borderLeftWidth: 3,
    borderLeftColor: C.electricYellow,
  },
  lockedHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
    gap: 6,
  },
  lockedPill: {
    backgroundColor: C.electricYellow,
    color: C.forestGreen,
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 7,
    letterSpacing: 1,
    paddingHorizontal: 5,
    paddingVertical: 2,
    borderRadius: 3,
  },
  lockedTitle: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 10,
    color: C.forestGreen,
    letterSpacing: 0.8,
    textTransform: 'uppercase' as const,
  },
  lockedDesc: {
    fontSize: 8.5,
    color: C.mediumGray,
    marginBottom: 6,
    lineHeight: 1.4,
  },
  lockedBlur: {
    flexDirection: 'row',
    gap: 4,
    marginTop: 4,
  },
  lockedBlurBar: {
    height: 6,
    backgroundColor: C.blurGray,
    borderRadius: 3,
    flex: 1,
  },
  // Premium CTA
  ctaBox: {
    backgroundColor: C.forestGreen,
    borderRadius: 6,
    paddingVertical: 14,
    paddingHorizontal: 18,
    marginTop: 4,
  },
  ctaTitle: {
    fontFamily: 'Oswald',
    fontWeight: 700,
    fontSize: 13,
    color: C.electricYellow,
    marginBottom: 6,
    letterSpacing: 0.5,
  },
  ctaText: {
    fontSize: 9,
    color: C.white,
    lineHeight: 1.5,
  },
  ctaButton: {
    backgroundColor: C.electricYellow,
    borderRadius: 4,
    paddingVertical: 7,
    paddingHorizontal: 16,
    alignSelf: 'flex-start',
    marginTop: 10,
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
    color: C.electricYellow,
    marginTop: 5,
  },
  // Footer
  footer: {
    marginTop: 14,
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

// --- Helpers ---

function RankWithDelta({ rank, change }: { rank: number; change: number | null }) {
  return (
    <View style={s.heroValueRow}>
      <Text style={s.heroValue}>#{rank}</Text>
      {change != null && change !== 0 && (
        <Text style={[s.heroChange, { color: change > 0 ? C.winGreen : C.lossRed }]}>
          {change > 0 ? `▲${change}` : `▼${Math.abs(change)}`}
        </Text>
      )}
    </View>
  );
}

function FormCircle({ result }: { result: string }) {
  const colorMap: Record<string, string> = {
    W: C.winGreen,
    L: C.lossRed,
    D: C.drawGray,
    U: C.mediumGray,
  };
  return <Text style={[s.formBadge, { backgroundColor: colorMap[result] || C.mediumGray }]}>{result}</Text>;
}

function LockedCard({ title, description }: { title: string; description: string }) {
  return (
    <View style={s.lockedCard}>
      <View style={s.lockedHeader}>
        <Text style={s.lockedPill}>PREMIUM</Text>
        <Text style={s.lockedTitle}>{title}</Text>
      </View>
      <Text style={s.lockedDesc}>{description}</Text>
      {/* Blurred visual hint — suggests data is "there" but obscured */}
      <View style={s.lockedBlur}>
        <View style={s.lockedBlurBar} />
        <View style={[s.lockedBlurBar, { flex: 0.7 }]} />
        <View style={[s.lockedBlurBar, { flex: 0.4 }]} />
      </View>
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
  const percentile = Math.max(1, Math.round((1 - ranking.rank_in_cohort_final / cohortTotal) * 100));
  const genderLabel = formatGender(team.gender);
  // Use season fields (wins/losses/draws/games_played), not total_* — the report
  // card is a current-season summary, and conflating with career history would
  // misstate the headline for teams whose all-time differs from this season.
  const seasonWinPct =
    ranking.games_played > 0
      ? `${Math.round(((ranking.wins + 0.5 * ranking.draws) / ranking.games_played) * 100)}%`
      : '—';
  const recordStr = `${ranking.wins}-${ranking.losses}-${ranking.draws}`;
  // Last 5: aggregate W/L/D shape only — opponent + score detail is premium-gated.
  const last5 = games.slice(0, 5).map((g) => g.result);

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
            {team.state ? `${team.state.toUpperCase()} · ` : ''}U{team.age} {genderLabel} · Generated {generatedDate}
          </Text>
        </View>

        {/* Hero stats — PowerScore + National Rank */}
        <View style={s.heroRow}>
          <View style={s.heroBox}>
            <Text style={s.heroLabel}>POWERSCORE</Text>
            <Text style={s.heroValue}>{ranking.power_score_final.toFixed(3)}</Text>
            <Text style={s.heroSub}>
              Top {percentile}% nationally · #{ranking.rank_in_cohort_final} of {cohortTotal.toLocaleString()}
            </Text>
          </View>
          <View style={s.heroBox}>
            <Text style={s.heroLabel}>NATIONAL RANK</Text>
            <RankWithDelta rank={ranking.rank_in_cohort_final} change={ranking.rank_change_30d} />
            <Text style={s.heroSub}>
              {ranking.rank_in_state_final != null && team.state
                ? `#${ranking.rank_in_state_final} in ${team.state.toUpperCase()} · ${stateCohortTotal.toLocaleString()} teams`
                : '30-day change'}
            </Text>
          </View>
        </View>

        {/* Record + Last 5 */}
        <View style={s.midRow}>
          <View style={s.midBox}>
            <Text style={s.midLabel}>SEASON RECORD</Text>
            <Text style={s.recordValue}>{recordStr}</Text>
            <Text style={s.recordSub}>
              Win rate {seasonWinPct} · {ranking.games_played} games
            </Text>
          </View>
          <View style={s.midBox}>
            <Text style={s.midLabel}>LAST 5</Text>
            {last5.length > 0 ? (
              <View style={s.formRow}>
                {last5.map((r, i) => (
                  <FormCircle key={i} result={r} />
                ))}
              </View>
            ) : (
              <Text style={s.recordSub}>No scored games yet</Text>
            )}
          </View>
        </View>

        <View style={s.divider} />

        {/* What's inside PitchRank+ — locked previews */}
        <Text style={s.sectionTitle}>What&apos;s inside PitchRank+</Text>
        <View style={s.lockedSection}>
          <View style={s.lockedGridRow}>
            <LockedCard
              title="Game History"
              description="Every game this season with over- and underperformance highlights — see which results boosted your rank and which dragged it down."
            />
            <LockedCard
              title="Ranking History + Momentum"
              description="Where you've ranked over time, recent momentum, and a goal-differential trajectory chart that shows the shape of your season."
            />
          </View>
          <View style={s.lockedGridRow}>
            <LockedCard
              title="Team Insights"
              description="Clutch Factor, Season Truth, and persona analysis — the patterns inside your results that the raw W-L-D doesn't show."
            />
            <LockedCard
              title="Compare + Predict"
              description="Head-to-head comparisons and matchup predictions that are scary accurate. Watchlist any team and get alerts when their rank moves."
            />
          </View>
        </View>

        {/* Premium CTA */}
        <View style={s.ctaBox}>
          <Text style={s.ctaTitle}>DON&apos;T MAKE A $10K CLUB DECISION ON A HUNCH.</Text>
          <Text style={s.ctaText}>
            Unlock the four sections above — your full game history, ranking history, team insights, and scary-accurate
            matchup predictions. Cancel anytime.
          </Text>
          <Link src="https://pitchrank.io/upgrade">
            <View style={s.ctaButton}>
              <Text style={s.ctaButtonText}>START FREE 7-DAY TRIAL</Text>
            </View>
          </Link>
          <Text style={s.ctaSmall}>7 days free · $6.99/mo · Cancel anytime</Text>
        </View>

        {/* Footer */}
        <View style={s.footer}>
          <Text style={s.footerText}>Powered by PitchRank · 1.1M+ games analyzed · Updated weekly</Text>
          <Text style={s.footerText}>pitchrank.io</Text>
        </View>
      </Page>
    </Document>
  );
}
