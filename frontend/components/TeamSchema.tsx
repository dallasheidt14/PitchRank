'use client';

interface TeamSchemaProps {
  teamName: string;
  clubName?: string;
  state?: string;
  ageGroup?: number;
  gender?: 'M' | 'F' | 'B' | 'G';
  rank?: number;
  powerScore?: number;
  wins?: number;
  losses?: number;
  draws?: number;
}

/**
 * SportsTeam structured data for team pages
 * Helps Google understand team information for rich results
 */
export function TeamSchema({
  teamName,
  clubName,
  state,
  ageGroup,
  gender,
  rank,
  powerScore,
  wins,
  losses,
  draws,
}: TeamSchemaProps) {
  const genderDisplay = gender === 'M' || gender === 'B' ? 'Male' : 'Female';

  const schema = {
    '@context': 'https://schema.org',
    '@type': 'SportsTeam',
    name: teamName,
    sport: 'Soccer',
    ...(clubName && { memberOf: {
      '@type': 'SportsOrganization',
      name: clubName,
    }}),
    ...(state && { location: {
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressRegion: state,
        addressCountry: 'US',
      },
    }}),
    ...(ageGroup && { audience: {
      '@type': 'PeopleAudience',
      suggestedMaxAge: ageGroup,
      suggestedGender: genderDisplay,
    }}),
    ...(wins !== undefined && losses !== undefined && {
      aggregateRating: {
        '@type': 'AggregateRating',
        ratingValue: powerScore?.toFixed(2) || '0',
        bestRating: '100',
        worstRating: '0',
        ratingCount: (wins || 0) + (losses || 0) + (draws || 0),
      },
    }),
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(schema),
      }}
    />
  );
}
