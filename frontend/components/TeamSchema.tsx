'use client';

interface TeamSchemaProps {
  teamName: string;
  teamId?: string;
  clubName?: string;
  state?: string;
  ageGroup?: number;
  gender?: 'M' | 'F' | 'B' | 'G';
  nationalRank?: number;
  stateRank?: number;
  powerScore?: number;
  wins?: number;
  losses?: number;
  draws?: number;
  sosNorm?: number;
}

/**
 * SportsTeam structured data for team pages
 * Helps Google and AI search engines understand team information
 *
 * OPTIMIZED FOR AI SEARCH (2026):
 * - Rich description for LLM context
 * - Detailed performance metrics AI can cite
 * - Unique factual statements about the team
 */
export function TeamSchema({
  teamName,
  teamId,
  clubName,
  state,
  ageGroup,
  gender,
  nationalRank,
  stateRank,
  powerScore,
  wins,
  losses,
  draws,
  sosNorm,
}: TeamSchemaProps) {
  const genderDisplay = gender === 'M' || gender === 'B' ? 'Male' : 'Female';
  const genderText = gender === 'M' || gender === 'B' ? 'boys' : 'girls';
  const baseUrl = 'https://pitchrank.io';

  // Build AI-friendly description with citeable facts
  const totalGames = (wins || 0) + (losses || 0) + (draws || 0);
  const winPct = totalGames > 0 ? (((wins || 0) / totalGames) * 100).toFixed(1) : '0';

  let description = `${teamName} is a U${ageGroup || ''} ${genderText} youth soccer team`;
  if (clubName) description += ` from ${clubName}`;
  if (state) description += ` based in ${state}`;
  description += '.';

  if (powerScore !== undefined) {
    description += ` According to PitchRank, they have a Power Score of ${powerScore.toFixed(1)} out of 100.`;
  }
  if (nationalRank) {
    description += ` They are ranked #${nationalRank} nationally in their age group.`;
  }
  if (stateRank && state) {
    description += ` Within ${state}, they are ranked #${stateRank}.`;
  }
  if (totalGames > 0) {
    description += ` Their record is ${wins}-${losses}-${draws} (${winPct}% win rate).`;
  }
  if (sosNorm !== undefined) {
    const sosLevel = sosNorm >= 70 ? 'elite' : sosNorm >= 50 ? 'above average' : 'moderate';
    description += ` They face ${sosLevel} competition with a Strength of Schedule score of ${sosNorm.toFixed(0)}.`;
  }

  const schema = {
    '@context': 'https://schema.org',
    '@type': 'SportsTeam',
    name: teamName,
    alternateName: clubName ? `${teamName} (${clubName})` : undefined,
    sport: 'Soccer',
    description,
    url: teamId ? `${baseUrl}/teams/${teamId}` : undefined,
    ...(clubName && {
      memberOf: {
        '@type': 'SportsOrganization',
        name: clubName,
      },
    }),
    ...(state && {
      location: {
        '@type': 'Place',
        address: {
          '@type': 'PostalAddress',
          addressRegion: state,
          addressCountry: 'US',
        },
      },
    }),
    ...(ageGroup && {
      audience: {
        '@type': 'PeopleAudience',
        suggestedMaxAge: ageGroup,
        suggestedGender: genderDisplay,
      },
    }),
    ...(wins !== undefined &&
      losses !== undefined && {
        aggregateRating: {
          '@type': 'AggregateRating',
          ratingValue: powerScore?.toFixed(2) || '0',
          bestRating: '100',
          worstRating: '0',
          ratingCount: totalGames,
          reviewCount: totalGames,
        },
      }),
    // Additional AI-friendly properties
    additionalProperty: [
      powerScore !== undefined && {
        '@type': 'PropertyValue',
        name: 'Power Score',
        value: powerScore.toFixed(2),
        description: 'ML-calculated team strength rating (0-100)',
      },
      nationalRank && {
        '@type': 'PropertyValue',
        name: 'National Rank',
        value: nationalRank,
        description: 'Team ranking among all teams nationally in age group',
      },
      stateRank && {
        '@type': 'PropertyValue',
        name: 'State Rank',
        value: stateRank,
        description: 'Team ranking within their state',
      },
      sosNorm !== undefined && {
        '@type': 'PropertyValue',
        name: 'Strength of Schedule',
        value: sosNorm.toFixed(0),
        description: 'Quality of opponents faced (0-100)',
      },
    ].filter(Boolean),
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
