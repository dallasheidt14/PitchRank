'use client';

interface RankedTeam {
  teamName: string;
  clubName?: string;
  rank: number;
  powerScore?: number;
  state?: string;
}

interface RankingsSchemaProps {
  region: string;
  ageGroup: string;
  gender: string;
  topTeams: RankedTeam[];
  totalTeams?: number;
  lastUpdated?: string;
}

/**
 * Rankings structured data for ranking pages
 * Helps Google understand ranking information for rich results
 */
export function RankingsSchema({
  region,
  ageGroup,
  gender,
  topTeams,
  totalTeams,
  lastUpdated,
}: RankingsSchemaProps) {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';
  const genderDisplay = gender === 'male' ? 'Boys' : 'Girls';
  const regionDisplay = region === 'national' ? 'National' : region.toUpperCase();
  const ageDisplay = ageGroup.toUpperCase();

  // ItemList schema for rankings
  const rankingsSchema = {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name: `${ageDisplay} ${genderDisplay} Soccer Rankings - ${regionDisplay}`,
    description: `Top ${ageDisplay} ${genderDisplay.toLowerCase()} soccer team rankings ${region === 'national' ? 'nationally' : `in ${regionDisplay}`}`,
    url: `${baseUrl}/rankings/${region}/${ageGroup}/${gender}`,
    numberOfItems: totalTeams || topTeams.length,
    ...(lastUpdated && { dateModified: lastUpdated }),
    itemListElement: topTeams.slice(0, 10).map((team, index) => ({
      '@type': 'ListItem',
      position: team.rank || index + 1,
      item: {
        '@type': 'SportsTeam',
        name: team.teamName,
        sport: 'Soccer',
        ...(team.clubName && {
          memberOf: {
            '@type': 'SportsOrganization',
            name: team.clubName,
          },
        }),
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
      },
    })),
  };

  // WebPage schema
  const webPageSchema = {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: `${ageDisplay} ${genderDisplay} Soccer Rankings - ${regionDisplay}`,
    description: `Comprehensive ${ageDisplay} ${genderDisplay.toLowerCase()} soccer team rankings with PowerScores and performance metrics`,
    url: `${baseUrl}/rankings/${region}/${ageGroup}/${gender}`,
    isPartOf: {
      '@type': 'WebSite',
      name: 'PitchRank',
      url: baseUrl,
    },
    about: {
      '@type': 'Thing',
      name: `${ageDisplay} ${genderDisplay} Youth Soccer`,
    },
    ...(lastUpdated && { dateModified: lastUpdated }),
    mainEntity: rankingsSchema,
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(rankingsSchema),
        }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(webPageSchema),
        }}
      />
    </>
  );
}
