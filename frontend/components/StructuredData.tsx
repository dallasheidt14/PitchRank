/**
 * Structured Data (Schema.org JSON-LD) component
 * Provides rich metadata for search engines and AI search platforms
 * Optimized for LLM retrieval and citation in 2026
 */
export function StructuredData() {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

  // Organization Schema - Enhanced for AI recognition
  const organizationSchema = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: 'PitchRank',
    alternateName: 'PitchRank Youth Soccer Rankings',
    url: baseUrl,
    logo: `${baseUrl}/logos/pitchrank-logo-dark.png`,
    description:
      'PitchRank is the leading data-powered youth soccer team ranking platform covering U10 through U18 age groups across all 50 US states. Our V53E algorithm uses machine learning to calculate power scores, enabling fair cross-age and cross-state team comparisons.',
    foundingDate: '2024',
    slogan: 'Data-powered youth soccer rankings',
    keywords:
      'youth soccer rankings, club soccer rankings, U10 soccer rankings, U12 soccer rankings, U14 soccer rankings, U16 soccer rankings, U18 soccer rankings, soccer power rankings, youth soccer team comparison',
    sameAs: [
      'https://twitter.com/pitchrank',
      'https://instagram.com/pitchrank',
      'https://facebook.com/pitchrank',
      'https://linkedin.com/company/pitchrank',
    ],
    contactPoint: {
      '@type': 'ContactPoint',
      contactType: 'Customer Support',
      email: 'dallasheidt14@gmail.com',
    },
    areaServed: {
      '@type': 'Country',
      name: 'United States',
    },
    knowsAbout: [
      'Youth Soccer Rankings',
      'Club Soccer Analytics',
      'Soccer Team Power Scores',
      'Strength of Schedule Analysis',
      'Cross-Age Soccer Comparisons',
    ],
  };

  // WebSite Schema with Search Action
  const websiteSchema = {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: 'PitchRank',
    url: baseUrl,
    description:
      'Youth soccer team rankings with cross-age and cross-state support for U10-U18 boys and girls teams',
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${baseUrl}/rankings?q={search_term_string}`,
      },
      'query-input': 'required name=search_term_string',
    },
  };

  // SportsOrganization Schema
  const sportsOrgSchema = {
    '@context': 'https://schema.org',
    '@type': 'SportsOrganization',
    name: 'PitchRank',
    sport: 'Soccer',
    url: baseUrl,
    description:
      'Comprehensive ranking system for youth soccer teams across the United States using the V53E machine learning algorithm',
    memberOf: {
      '@type': 'Organization',
      name: 'Youth Soccer Community',
    },
  };

  // Dataset Schema - Critical for AI search retrieval
  // AI platforms love structured datasets they can cite
  const datasetSchema = {
    '@context': 'https://schema.org',
    '@type': 'Dataset',
    name: 'PitchRank Youth Soccer Team Rankings Dataset',
    description:
      'Comprehensive weekly rankings of youth soccer teams across the United States, covering U10 through U18 age groups for both boys and girls. Includes power scores, strength of schedule, offensive/defensive ratings, and win-loss records calculated using the V53E machine learning algorithm.',
    url: `${baseUrl}/rankings`,
    keywords: [
      'youth soccer rankings',
      'club soccer data',
      'soccer team statistics',
      'U10 U12 U14 U16 U18 soccer',
      'boys soccer rankings',
      'girls soccer rankings',
      'state soccer rankings',
      'national soccer rankings',
    ],
    creator: {
      '@type': 'Organization',
      name: 'PitchRank',
      url: baseUrl,
    },
    dateModified: new Date().toISOString().split('T')[0],
    temporalCoverage: '2024/..',
    spatialCoverage: {
      '@type': 'Place',
      name: 'United States',
    },
    variableMeasured: [
      {
        '@type': 'PropertyValue',
        name: 'Power Score',
        description:
          'ML-adjusted composite score representing overall team strength (0-100 scale)',
      },
      {
        '@type': 'PropertyValue',
        name: 'Strength of Schedule',
        description: 'Normalized measure of opponent difficulty faced',
      },
      {
        '@type': 'PropertyValue',
        name: 'Offensive Rating',
        description: 'Normalized goals scored per game adjusted for opponent strength',
      },
      {
        '@type': 'PropertyValue',
        name: 'Defensive Rating',
        description: 'Normalized goals allowed per game adjusted for opponent strength',
      },
    ],
    distribution: {
      '@type': 'DataDownload',
      contentUrl: `${baseUrl}/rankings`,
      encodingFormat: 'text/html',
    },
    license: 'https://creativecommons.org/licenses/by-nc/4.0/',
    isAccessibleForFree: true,
  };

  // Speakable Schema - Optimized for voice assistants and AI readers
  const speakableSchema = {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: 'PitchRank Youth Soccer Rankings',
    speakable: {
      '@type': 'SpeakableSpecification',
      cssSelector: [
        '.team-name',
        '.power-score',
        '.ranking-position',
        '.methodology-summary',
        'h1',
        'h2',
        '.team-stats-summary',
      ],
    },
    url: baseUrl,
  };

  return (
    <>
      {/* Organization Schema */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(organizationSchema),
        }}
      />

      {/* WebSite Schema */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(websiteSchema),
        }}
      />

      {/* SportsOrganization Schema */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(sportsOrgSchema),
        }}
      />

      {/* Dataset Schema - AI search optimization */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(datasetSchema),
        }}
      />

      {/* Speakable Schema - Voice assistant optimization */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(speakableSchema),
        }}
      />
    </>
  );
}
