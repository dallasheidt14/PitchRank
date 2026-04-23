import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Breadcrumbs } from '@/components/Breadcrumbs';
import { US_STATES, AGE_GROUPS, BASE_URL } from '@/lib/constants';
import { safeJsonLd } from '@/lib/schema-utils';
import { api } from '@/lib/api';
import { formatPowerScore } from '@/lib/utils';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

interface StateOverviewPageProps {
  params: Promise<{
    region: string;
  }>;
}

/**
 * Get state info from code
 */
function getStateInfo(stateCode: string): { code: string; name: string } | null {
  const state = US_STATES.find((s) => s.code.toLowerCase() === stateCode.toLowerCase());
  if (state) return { code: state.code, name: state.name };
  if (stateCode.toLowerCase() === 'national') return { code: 'national', name: 'National' };
  return null;
}

/**
 * State-specific meta descriptions for high-impression queries with low CTR.
 * Keyed by lowercase state code. Falls back to generic template if not listed.
 */
const STATE_DESCRIPTIONS: Record<string, string> = {
  co: 'Colorado youth soccer rankings for every age group — Rapids Youth, Real Colorado, Colorado Storm and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  tx: 'Texas youth soccer rankings for every age group — FC Dallas, Solar SC, Lonestar and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  md: 'Maryland youth soccer rankings for every age group — Baltimore Armour, Pipeline SC, MSC and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ca: 'California youth soccer rankings for every age group — LA Galaxy, San Diego Surf, Beach FC and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ny: 'New York youth soccer rankings for every age group — Manhattan SC, SUSA, Albertson and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ga: 'Georgia youth soccer rankings for every age group — Atlanta United, Concorde Fire, United Futbol and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  nj: 'New Jersey youth soccer rankings for every age group — PDA, STA, Players Development and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  az: 'Arizona youth soccer rankings for every age group — SC Del Sol, Scottsdale Blackhawks, Real Salt Lake AZ and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  pa: 'Pennsylvania youth soccer rankings for every age group — Philadelphia Union, FC DELCO, Bethlehem and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  fl: 'Florida youth soccer rankings for every age group — Weston FC, South Florida Football Academy, Orlando City and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  va: 'Virginia youth soccer rankings for every age group — Richmond United, Beach FC, Arlington Soccer and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  or: 'Oregon youth soccer rankings for every age group — Oregon Premier FC, Oregon Surf SC, Eastside Timbers and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  la: 'Louisiana youth soccer rankings for every age group — Louisiana Fire SC, LA Krewe Rush, Louisiana Elite and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  al: 'Alabama youth soccer rankings for every age group — Alabama FC, Hoover-Vestavia, Auburn Soccer Club and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  mn: 'Minnesota youth soccer rankings for every age group — MN Thunder Academy, Salvo SC, Minnesota Rush and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ar: 'Arkansas youth soccer rankings for every age group — Arkansas Comets, Arkansas Rising, Sporting Arkansas and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  wa: 'Washington youth soccer rankings for every age group — Crossfire Premier, Eastside FC, Seattle United and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  oh: 'Ohio youth soccer rankings for every age group — Cincinnati United Premier, Club Ohio, Cleveland Force SC and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ky: 'Kentucky youth soccer rankings for every age group — LouCity Academy, Kings Hammer, Lexington Sporting and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  nc: 'North Carolina youth soccer rankings for every age group — NCFC, Charlotte Soccer Academy, Wake FC and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ne: 'Nebraska youth soccer rankings for every age group — Sting Nebraska, Gretna Elite Academy, Sporting Nebraska and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ks: 'Kansas youth soccer rankings for every age group — FC Wichita, Sporting Wichita, Sporting Blue Valley and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ma: 'Massachusetts youth soccer rankings for every age group — NEFC, FC Stars, FC Boston Bolts and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ct: 'Connecticut youth soccer rankings for every age group — CFC North, Inter Connecticut, Oakwood SC and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  me: 'Maine youth soccer rankings for every age group — Seacoast United Maine, Maine Lightning, FC America Maine and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ut: 'Utah youth soccer rankings for every age group — La Roca FC, Utah Avalanche, Wasatch SC and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  id: 'Idaho youth soccer rankings for every age group — Boise Timbers, Idaho Rush, Idaho Inferno and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ms: 'Mississippi youth soccer rankings for every age group — Mississippi Rush, Lobos Rush, Desoto FC and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ak: 'Alaska youth soccer rankings for every age group — Cook Inlet, Alaska Rush, Chugiak SC and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
  ok: 'Oklahoma youth soccer rankings for every age group — Oklahoma Energy FC, FC Tulsa Academy, Tulsa Soccer Club and more. 77K+ teams rated by PowerScore from real game results. Updated every Monday.',
};

/**
 * Generate metadata for state overview pages
 */
export async function generateMetadata({ params }: StateOverviewPageProps): Promise<Metadata> {
  const resolvedParams = await params;
  const { region } = resolvedParams;

  const stateInfo = getStateInfo(region);
  if (!stateInfo) {
    return { title: 'Not Found' };
  }

  const canonicalUrl = `${BASE_URL}/rankings/${region.toLowerCase()}`;
  const isNational = region.toLowerCase() === 'national';

  const title = isNational
    ? 'National Youth Soccer Rankings 2026 — Updated Weekly | PitchRank'
    : `${stateInfo.name} Youth Soccer Rankings 2026 — Updated Weekly | PitchRank`;

  const description = isNational
    ? 'National youth soccer rankings for all age groups. 77K+ teams ranked across 700K+ games analyzed. See where your team stands. Updated weekly.'
    : (STATE_DESCRIPTIONS[region.toLowerCase()] ??
      `${stateInfo.name} youth soccer rankings - Find where your team ranks among 77K+ teams. PowerScore ratings updated weekly from 700K+ analyzed games. Start now!`);

  const ogTitle = isNational
    ? 'National Youth Soccer Rankings 2026 | PitchRank'
    : `${stateInfo.name} Youth Soccer Rankings 2026 | PitchRank`;

  return {
    title,
    description,
    alternates: {
      canonical: canonicalUrl,
    },
    openGraph: {
      title: ogTitle,
      description,
      url: canonicalUrl,
      siteName: 'PitchRank',
      type: 'website',
      images: [
        {
          url: `${BASE_URL}/opengraph-image.png`,
          width: 1200,
          height: 630,
          alt: ogTitle,
        },
      ],
    },
    twitter: {
      card: 'summary_large_image',
      title: ogTitle,
      description,
      images: [`${BASE_URL}/opengraph-image.png`],
    },
  };
}

/**
 * Generate static params for popular states
 */
export async function generateStaticParams() {
  // Pre-generate pages for popular states + national
  const popularStates = ['national', 'ca', 'fl', 'tx', 'az', 'ny', 'nj', 'ga', 'pa', 'il', 'nc', 'wa', 'co', 'oh'];
  return popularStates.map((region) => ({ region }));
}

export default async function StateOverviewPage({ params }: StateOverviewPageProps) {
  const resolvedParams = await params;
  const { region } = resolvedParams;

  const stateInfo = getStateInfo(region);
  if (!stateInfo) {
    notFound();
  }

  const isNational = region.toLowerCase() === 'national';

  // Fetch top teams for each gender in popular age groups (for preview)
  let boysTeamCount = 0;
  let girlsTeamCount = 0;
  const topBoys: Array<{
    age: string;
    teams: Array<{ team_id_master: string; team_name: string; club_name: string | null; power_score_final: number }>;
  }> = [];
  const topGirls: Array<{
    age: string;
    teams: Array<{ team_id_master: string; team_name: string; club_name: string | null; power_score_final: number }>;
  }> = [];

  try {
    const previewAges = ['u12', 'u13', 'u14'];
    const regionParam = isNational ? null : region;

    // Fetch top-3 teams per age/gender AND counts for U12 in parallel
    const [boysCount, girlsCount, ...previews] = await Promise.all([
      api.getRankingsCount(regionParam, 'u12', 'M'),
      api.getRankingsCount(regionParam, 'u12', 'F'),
      ...previewAges.flatMap((age) => [
        api.getRankings(regionParam, age, 'M', { limit: 3 }),
        api.getRankings(regionParam, age, 'F', { limit: 3 }),
      ]),
    ]);

    boysTeamCount = boysCount;
    girlsTeamCount = girlsCount;

    for (let i = 0; i < previewAges.length; i++) {
      const boysData = previews[i * 2];
      const girlsData = previews[i * 2 + 1];
      const age = previewAges[i].toUpperCase();

      topBoys.push({
        age,
        teams: boysData.map((t) => ({
          team_id_master: t.team_id_master,
          team_name: t.team_name,
          club_name: t.club_name,
          power_score_final: t.power_score_final,
        })),
      });

      topGirls.push({
        age,
        teams: girlsData.map((t) => ({
          team_id_master: t.team_id_master,
          team_name: t.team_name,
          club_name: t.club_name,
          power_score_final: t.power_score_final,
        })),
      });
    }
  } catch (error) {
    console.error('Error fetching state overview data:', error);
  }

  // Visible FAQ content — schema must match rendered markup exactly
  const stateLabel = isNational ? 'National' : stateInfo.name;
  const faqItems = [
    {
      q: isNational
        ? 'What is the top-ranked youth soccer club in the United States?'
        : `What is the best youth soccer club in ${stateLabel}?`,
      a: `Top-ranked clubs vary by age group and update weekly. See the Top Boys Teams and Top Girls Teams sections above to view the leading ${stateLabel} clubs by age group.`,
    },
    {
      q: isNational ? 'How are youth soccer teams ranked?' : `How are ${stateLabel} youth soccer teams ranked?`,
      a: 'Teams are ranked by PowerScore — a rating built from real game results. PowerScore weighs wins, margin of victory, strength of opponent, and game context. Rankings cover U10 through U19 for both boys and girls.',
    },
    {
      q: 'How often are rankings updated?',
      a: 'Rankings update every Monday, based on game results from the prior week. Top teams, risers, and fallers are recomputed each week.',
    },
    {
      q: 'Are these rankings free?',
      a: `Yes — all ${stateLabel} youth soccer rankings are free to browse without an account.`,
    },
    {
      q: 'Which age groups are covered?',
      a: `PitchRank ranks U10 through U19 for both boys and girls${isNational ? '' : ` in ${stateLabel}`}. Use the age group navigation above to open each age group's full rankings table.`,
    },
  ];

  // Structured data for SEO — CollectionPage + ItemList of age/gender sub-pages + FAQPage
  const collectionPageSchema = {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: isNational ? 'National Youth Soccer Rankings' : `${stateInfo.name} Youth Soccer Rankings`,
    description: isNational
      ? 'Comprehensive national youth soccer rankings by age group and gender'
      : `Youth soccer rankings for ${stateInfo.name} across all age groups`,
    url: `${BASE_URL}/rankings/${region.toLowerCase()}`,
    mainEntity: {
      '@type': 'ItemList',
      numberOfItems: AGE_GROUPS.length * 2,
      itemListElement: AGE_GROUPS.flatMap((age, ageIdx) => [
        {
          '@type': 'ListItem',
          position: ageIdx * 2 + 1,
          name: `${stateLabel} ${age.toUpperCase()} Boys Soccer Rankings`,
          url: `${BASE_URL}/rankings/${region.toLowerCase()}/${age}/male`,
        },
        {
          '@type': 'ListItem',
          position: ageIdx * 2 + 2,
          name: `${stateLabel} ${age.toUpperCase()} Girls Soccer Rankings`,
          url: `${BASE_URL}/rankings/${region.toLowerCase()}/${age}/female`,
        },
      ]),
    },
  };

  const faqSchema = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqItems.map((item) => ({
      '@type': 'Question',
      name: item.q,
      acceptedAnswer: {
        '@type': 'Answer',
        text: item.a,
      },
    })),
  };

  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(collectionPageSchema) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(faqSchema) }} />

      <div className="container mx-auto py-8 px-4">
        <Breadcrumbs />

        {/* Page Header */}
        <div className="relative bg-secondary/30 border-b-2 border-primary py-8 sm:py-12 mb-8 -mx-4 px-4">
          <div className="absolute left-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
          <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold uppercase text-primary mb-2">
            {isNational ? 'National' : stateInfo.name} Soccer Rankings
          </h1>
          <p className="text-muted-foreground text-base sm:text-lg">
            {isNational
              ? 'Browse youth soccer rankings across the USA'
              : `Youth soccer team rankings in ${stateInfo.name}`}
          </p>
          {(boysTeamCount > 0 || girlsTeamCount > 0) && (
            <p className="text-sm text-muted-foreground mt-2">
              {boysTeamCount > 0 && `${boysTeamCount.toLocaleString()} Boys teams`}
              {boysTeamCount > 0 && girlsTeamCount > 0 && ' • '}
              {girlsTeamCount > 0 && `${girlsTeamCount.toLocaleString()} Girls teams`} (U12 division)
            </p>
          )}
          {!isNational && (
            <p className="text-sm text-muted-foreground mt-2">
              Part of{' '}
              <Link href="/rankings" className="text-primary hover:underline font-medium">
                77,000+ teams ranked nationally
              </Link>
            </p>
          )}
        </div>

        {/* Age Group Grid */}
        <section className="mb-12">
          <h2 className="text-2xl font-bold mb-6">Browse by Age Group</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
            {AGE_GROUPS.map((age) => (
              <div
                key={age}
                className="bg-card border border-border rounded-lg p-4 hover:border-primary transition-colors"
              >
                <h3 className="font-bold text-lg mb-2">{age.toUpperCase()}</h3>
                <div className="space-y-1">
                  <Link
                    href={`/rankings/${region.toLowerCase()}/${age}/male`}
                    className="block text-sm text-primary hover:underline"
                  >
                    Boys →
                  </Link>
                  <Link
                    href={`/rankings/${region.toLowerCase()}/${age}/female`}
                    className="block text-sm text-primary hover:underline"
                  >
                    Girls →
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Top Teams Preview */}
        <div className="grid md:grid-cols-2 gap-8 mb-12">
          {/* Top Boys */}
          <section>
            <h2 className="text-2xl font-bold mb-4">Top Boys Teams</h2>
            <div className="space-y-4">
              {topBoys.map(({ age, teams }) => (
                <div key={age} className="bg-card border border-border rounded-lg p-4">
                  <div className="flex justify-between items-center mb-2">
                    <h3 className="font-semibold">{age} Boys</h3>
                    <Link
                      href={`/rankings/${region.toLowerCase()}/${age.toLowerCase()}/male`}
                      className="text-xs text-primary hover:underline"
                    >
                      View All →
                    </Link>
                  </div>
                  {teams.length > 0 ? (
                    <ol className="space-y-1">
                      {teams.map((team, idx) => (
                        <li key={team.team_id_master} className="text-sm flex items-center gap-2">
                          <span className="text-muted-foreground w-4">{idx + 1}.</span>
                          <Link href={`/teams/${team.team_id_master}`} className="hover:text-primary truncate">
                            {team.team_name}
                          </Link>
                          <span className="text-xs text-muted-foreground ml-auto">
                            {formatPowerScore(team.power_score_final)}
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="text-sm text-muted-foreground">No teams ranked yet</p>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Top Girls */}
          <section>
            <h2 className="text-2xl font-bold mb-4">Top Girls Teams</h2>
            <div className="space-y-4">
              {topGirls.map(({ age, teams }) => (
                <div key={age} className="bg-card border border-border rounded-lg p-4">
                  <div className="flex justify-between items-center mb-2">
                    <h3 className="font-semibold">{age} Girls</h3>
                    <Link
                      href={`/rankings/${region.toLowerCase()}/${age.toLowerCase()}/female`}
                      className="text-xs text-primary hover:underline"
                    >
                      View All →
                    </Link>
                  </div>
                  {teams.length > 0 ? (
                    <ol className="space-y-1">
                      {teams.map((team, idx) => (
                        <li key={team.team_id_master} className="text-sm flex items-center gap-2">
                          <span className="text-muted-foreground w-4">{idx + 1}.</span>
                          <Link href={`/teams/${team.team_id_master}`} className="hover:text-primary truncate">
                            {team.team_name}
                          </Link>
                          <span className="text-xs text-muted-foreground ml-auto">
                            {formatPowerScore(team.power_score_final)}
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="text-sm text-muted-foreground">No teams ranked yet</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* Other States */}
        {!isNational && (
          <section className="border-t border-border pt-8">
            <h2 className="text-xl font-bold mb-4">Rankings in Other States</h2>
            <div className="flex flex-wrap gap-2">
              <Link
                href="/rankings/national"
                className="px-3 py-1.5 bg-primary text-primary-foreground rounded text-sm hover:bg-primary/90"
              >
                National
              </Link>
              {US_STATES.filter((s) => s.code.toLowerCase() !== region.toLowerCase()).map((state) => (
                <Link
                  key={state.code}
                  href={`/rankings/${state.code.toLowerCase()}`}
                  className="px-3 py-1.5 bg-muted text-foreground rounded text-sm hover:bg-muted/80"
                >
                  {state.name}
                </Link>
              ))}
            </div>
          </section>
        )}

        {isNational && (
          <section className="border-t border-border pt-8">
            <h2 className="text-xl font-bold mb-4">Browse by State</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
              {US_STATES.map((state) => (
                <Link
                  key={state.code}
                  href={`/rankings/${state.code.toLowerCase()}`}
                  className="px-3 py-2 bg-muted text-foreground rounded text-sm hover:bg-muted/80 text-center"
                >
                  {state.name}
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* FAQ — mirrors FAQPage JSON-LD above. Keep copy in sync with faqItems. */}
        <section className="border-t border-border pt-8 mt-8">
          <h2 className="text-xl font-bold mb-4">Frequently Asked Questions</h2>
          <dl className="divide-y divide-border/60">
            {faqItems.map((item) => (
              <div key={item.q} className="py-3 first:pt-0">
                <dt className="text-sm font-medium">{item.q}</dt>
                <dd className="text-sm text-muted-foreground mt-1 leading-relaxed">{item.a}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </>
  );
}
