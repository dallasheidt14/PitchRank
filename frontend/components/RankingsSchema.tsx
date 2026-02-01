'use client';

interface RankedTeam {
  teamName: string;
  clubName?: string | null;
  rank?: number | null;
  powerScore?: number | null;
  state?: string | null;
}

interface RankingsSchemaProps {
  region: string;
  ageGroup: string;
  gender: string;
  topTeams: RankedTeam[];
  totalTeams?: number;
  lastUpdated?: string | null;
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
  const rankingsSchema: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name: `${ageDisplay} ${genderDisplay} Soccer Rankings - ${regionDisplay}`,
    description: `Top ${ageDisplay} ${genderDisplay.toLowerCase()} soccer team rankings ${region === 'national' ? 'nationally' : `in ${regionDisplay}`}`,
    url: `${baseUrl}/rankings/${region}/${ageGroup}/${gender}`,
    numberOfItems: totalTeams || topTeams.length,
    itemListElement: topTeams.slice(0, 10).map((team, index) => {
      const item: Record<string, unknown> = {
        '@type': 'SportsTeam',
        name: team.teamName,
        sport: 'Soccer',
      };
      
      if (team.clubName) {
        item.memberOf = {
          '@type': 'SportsOrganization',
          name: team.clubName,
        };
      }
      
      if (team.state) {
        item.location = {
          '@type': 'Place',
          address: {
            '@type': 'PostalAddress',
            addressRegion: team.state,
            addressCountry: 'US',
          },
        };
      }
      
      return {
        '@type': 'ListItem',
        position: team.rank ?? index + 1,
        item,
      };
    }),
  };

  if (lastUpdated) {
    rankingsSchema.dateModified = lastUpdated;
  }

  // WebPage schema
  const webPageSchema: Record<string, unknown> = {
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
    mainEntity: rankingsSchema,
  };

  if (lastUpdated) {
    webPageSchema.dateModified = lastUpdated;
  }

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
