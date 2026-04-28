import type { RankingRow } from '@/types/RankingRow';

export interface CohortModuleData {
  totalTeams: number;
  positioningHook: string;
  topClubs: Array<{ name: string; count: number }>;
  risers: Array<{ teamId: string; teamName: string; clubName: string | null; change: number }>;
  fallers: Array<{ teamId: string; teamName: string; clubName: string | null; change: number }>;
  lastGameDate: string | null;
  lastCalculated: string | null;
  locationText: string;
  ageGroupDisplay: string;
  genderDisplay: string;
  genderLabel: string;
  isNational: boolean;
  region: string;
  /** Raw URL-safe gender param ('male' or 'female') for link construction */
  genderSlug: string;
}

function getPositioningHook(count: number): string {
  if (count >= 500) return 'one of the deepest groups in the country';
  if (count >= 200) return 'a strong competitive group';
  if (count >= 50) return 'a growing group';
  return 'an emerging group';
}

export function computeCohortModules(
  teams: RankingRow[],
  locationText: string,
  ageGroupDisplay: string,
  genderDisplay: string,
  isNational: boolean,
  region: string,
  genderSlug: string
): CohortModuleData {
  const totalTeams = teams.length;
  const positioningHook = getPositioningHook(totalTeams);

  // Top clubs by team count in this cohort
  const clubCounts = new Map<string, number>();
  for (const team of teams) {
    if (team.club_name) {
      clubCounts.set(team.club_name, (clubCounts.get(team.club_name) ?? 0) + 1);
    }
  }
  const topClubs = [...clubCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, count]) => ({ name, count }));

  // Biggest movers — use state rank change for state pages, national for national
  const rankChangeField = isNational ? 'rank_change_7d' : 'rank_change_state_7d';
  const activeTeams = teams.filter((t) => t.status === 'Active' && (t.total_games_played ?? 0) >= 8);

  const risers = activeTeams
    .filter((t) => (t[rankChangeField] ?? 0) > 0)
    .sort((a, b) => (b[rankChangeField] ?? 0) - (a[rankChangeField] ?? 0))
    .slice(0, 3)
    .map((t) => ({
      teamId: t.team_id_master,
      teamName: t.team_name,
      clubName: t.club_name,
      change: t[rankChangeField]!,
    }));

  const fallers = activeTeams
    .filter((t) => (t[rankChangeField] ?? 0) < 0)
    .sort((a, b) => (a[rankChangeField] ?? 0) - (b[rankChangeField] ?? 0))
    .slice(0, 3)
    .map((t) => ({
      teamId: t.team_id_master,
      teamName: t.team_name,
      clubName: t.club_name,
      change: t[rankChangeField]!,
    }));

  // Most recent game date across all teams in cohort
  let lastGameDate: string | null = null;
  for (const team of teams) {
    if (team.last_game && (!lastGameDate || team.last_game > lastGameDate)) {
      lastGameDate = team.last_game;
    }
  }

  const lastCalculated = teams[0]?.last_calculated ?? null;
  // formatGender returns "Boys"/"Girls", not "Male"/"Female"
  const genderLabel = genderDisplay === 'Boys' || genderDisplay === 'Male' ? 'boys' : 'girls';

  return {
    totalTeams,
    positioningHook,
    topClubs,
    risers,
    fallers,
    lastGameDate,
    lastCalculated,
    locationText,
    ageGroupDisplay,
    genderDisplay,
    genderLabel,
    isNational,
    region,
    genderSlug,
  };
}

/**
 * States that have a pillar blog post.
 * Returns the blog slug and display title, or null if no pillar exists.
 */
const STATE_PILLAR_SLUGS: Record<string, { slug: string; title: string }> = {
  az: { slug: 'arizona-youth-soccer-rankings-guide', title: 'Arizona Youth Soccer Rankings Guide' },
  ca: { slug: 'california-youth-soccer-rankings-guide', title: 'California Youth Soccer Rankings Guide' },
  co: { slug: 'colorado-youth-soccer-rankings-guide', title: 'Colorado Youth Soccer Rankings Guide' },
  fl: { slug: 'florida-youth-soccer-rankings-guide', title: 'Florida Youth Soccer Rankings Guide' },
  md: { slug: 'maryland-youth-soccer-rankings-guide', title: 'Maryland Youth Soccer Rankings Guide' },
  mi: { slug: 'michigan-youth-soccer-rankings-guide', title: 'Michigan Youth Soccer Rankings Guide' },
  nj: { slug: 'new-jersey-youth-soccer-rankings-guide', title: 'New Jersey Youth Soccer Rankings Guide' },
  ny: { slug: 'new-york-youth-soccer-rankings-guide', title: 'New York Youth Soccer Rankings Guide' },
  nc: { slug: 'north-carolina-youth-soccer-rankings-guide', title: 'North Carolina Youth Soccer Rankings Guide' },
  pa: { slug: 'pennsylvania-youth-soccer-rankings-guide', title: 'Pennsylvania Youth Soccer Rankings Guide' },
  tx: { slug: 'texas-youth-soccer-rankings-guide', title: 'Texas Youth Soccer Rankings Guide' },
  va: { slug: 'virginia-youth-soccer-rankings-guide', title: 'Virginia Youth Soccer Rankings Guide' },
};

export function getRelatedGuide(stateCode: string): { slug: string; title: string } | null {
  return STATE_PILLAR_SLUGS[stateCode.toLowerCase()] ?? null;
}

/**
 * Build FAQ items for this cohort's ranking page.
 */
export function buildCohortFAQ(data: CohortModuleData): Array<{ question: string; answer: string }> {
  const { totalTeams, locationText, ageGroupDisplay, genderLabel, isNational } = data;
  const scope = isNational ? 'nationally' : `in ${locationText}`;

  return [
    {
      question: `How many ${ageGroupDisplay} ${genderLabel} soccer teams are there ${scope}?`,
      answer: `PitchRank tracks ${totalTeams.toLocaleString()} active ${ageGroupDisplay} ${genderLabel} teams ${scope} across all competitive leagues.`,
    },
    {
      question: `How often do ${isNational ? 'national' : locationText} ${ageGroupDisplay} ${genderLabel} rankings update?`,
      answer: 'Weekly every Monday as new game results come in. Rankings stabilize after 8\u201310 games.',
    },
    {
      question: `Which leagues are tracked for ${isNational ? 'national' : locationText} ${ageGroupDisplay} ${genderLabel} rankings?`,
      answer:
        'EDP, ECNL, MLS Next, NPL, US Youth Soccer state leagues, showcases, and friendlies \u2014 every competitive game we can find.',
    },
  ];
}
