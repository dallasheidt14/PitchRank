/**
 * Rankings Page Structured Data
 * Provides rich, AI-retrievable metadata for ranking pages
 *
 * OPTIMIZED FOR AI SEARCH (2026):
 * - ItemList schema for top teams (LLMs can cite specific rankings)
 * - WebPage schema with speakable content
 * - Breadcrumb integration for navigation context
 */

interface RankingsPageSchemaProps {
  region: string;
  ageGroup: string;
  gender: string;
  topTeams?: Array<{
    name: string;
    rank: number;
    powerScore: number;
    state?: string;
    club?: string;
  }>;
}

/**
 * Get full state name from code
 */
function getStateName(stateCode: string): string {
  const stateNames: Record<string, string> = {
    al: 'Alabama',
    ak: 'Alaska',
    az: 'Arizona',
    ar: 'Arkansas',
    ca: 'California',
    co: 'Colorado',
    ct: 'Connecticut',
    de: 'Delaware',
    fl: 'Florida',
    ga: 'Georgia',
    hi: 'Hawaii',
    id: 'Idaho',
    il: 'Illinois',
    in: 'Indiana',
    ia: 'Iowa',
    ks: 'Kansas',
    ky: 'Kentucky',
    la: 'Louisiana',
    me: 'Maine',
    md: 'Maryland',
    ma: 'Massachusetts',
    mi: 'Michigan',
    mn: 'Minnesota',
    ms: 'Mississippi',
    mo: 'Missouri',
    mt: 'Montana',
    ne: 'Nebraska',
    nv: 'Nevada',
    nh: 'New Hampshire',
    nj: 'New Jersey',
    nm: 'New Mexico',
    ny: 'New York',
    nc: 'North Carolina',
    nd: 'North Dakota',
    oh: 'Ohio',
    ok: 'Oklahoma',
    or: 'Oregon',
    pa: 'Pennsylvania',
    ri: 'Rhode Island',
    sc: 'South Carolina',
    sd: 'South Dakota',
    tn: 'Tennessee',
    tx: 'Texas',
    ut: 'Utah',
    vt: 'Vermont',
    va: 'Virginia',
    wa: 'Washington',
    wv: 'West Virginia',
    wi: 'Wisconsin',
    wy: 'Wyoming',
  };
  return stateNames[stateCode.toLowerCase()] || stateCode.toUpperCase();
}

export function RankingsPageSchema({
  region,
  ageGroup,
  gender,
  topTeams = [],
}: RankingsPageSchemaProps) {
  const baseUrl = 'https://pitchrank.io';
  const isNational = region.toLowerCase() === 'national';
  const regionDisplay = isNational ? 'National' : getStateName(region);
  const ageDisplay = ageGroup.toUpperCase();
  const genderDisplay = gender.toLowerCase() === 'male' ? 'Boys' : 'Girls';
  const pageUrl = `${baseUrl}/rankings/${region.toLowerCase()}/${ageGroup.toLowerCase()}/${gender.toLowerCase()}`;

  // Create AI-friendly page description
  const pageDescription = `Complete ${ageDisplay} ${genderDisplay} youth soccer team rankings ${isNational ? 'across the United States' : `in ${regionDisplay}`}. Rankings are calculated using PitchRank's V53E machine learning algorithm, which analyzes power scores, strength of schedule, and performance trends. Updated weekly every Monday.`;

  // WebPage schema with speakable content for AI/voice
  const webPageSchema = {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: `${ageDisplay} ${genderDisplay} Soccer Rankings - ${regionDisplay}`,
    description: pageDescription,
    url: pageUrl,
    dateModified: new Date().toISOString(),
    isPartOf: {
      '@type': 'WebSite',
      name: 'PitchRank',
      url: baseUrl,
    },
    about: {
      '@type': 'Thing',
      name: `${ageDisplay} ${genderDisplay} Youth Soccer Rankings`,
      description: `Power rankings for ${ageDisplay} age group ${genderDisplay.toLowerCase()} soccer teams`,
    },
    speakable: {
      '@type': 'SpeakableSpecification',
      cssSelector: ['h1', '.ranking-position', '.team-name', '.power-score'],
    },
    mainEntity: {
      '@type': 'ItemList',
      name: `Top ${ageDisplay} ${genderDisplay} Soccer Teams - ${regionDisplay}`,
      description: `The highest ranked ${ageDisplay} ${genderDisplay.toLowerCase()} youth soccer teams ${isNational ? 'in the United States' : `in ${regionDisplay}`} according to PitchRank.`,
      numberOfItems: topTeams.length,
      itemListOrder: 'https://schema.org/ItemListOrderDescending',
      itemListElement: topTeams.slice(0, 10).map((team, index) => ({
        '@type': 'ListItem',
        position: team.rank || index + 1,
        name: team.name,
        item: {
          '@type': 'SportsTeam',
          name: team.name,
          sport: 'Soccer',
          description: `${team.name} is ranked #${team.rank} with a Power Score of ${team.powerScore.toFixed(1)}${team.state ? ` from ${team.state}` : ''}${team.club ? ` (${team.club})` : ''}.`,
          ...(team.state && {
            location: {
              '@type': 'Place',
              address: {
                '@type': 'PostalAddress',
                addressRegion: team.state,
                addressCountry: 'US',
              },
            },
          }),
          aggregateRating: {
            '@type': 'AggregateRating',
            ratingValue: team.powerScore.toFixed(2),
            bestRating: '100',
            worstRating: '0',
          },
        },
      })),
    },
  };

  // Breadcrumb schema
  const breadcrumbSchema = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      {
        '@type': 'ListItem',
        position: 1,
        name: 'Home',
        item: baseUrl,
      },
      {
        '@type': 'ListItem',
        position: 2,
        name: 'Rankings',
        item: `${baseUrl}/rankings`,
      },
      {
        '@type': 'ListItem',
        position: 3,
        name: `${ageDisplay} ${genderDisplay} - ${regionDisplay}`,
        item: pageUrl,
      },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(webPageSchema),
        }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(breadcrumbSchema),
        }}
      />
    </>
  );
}
