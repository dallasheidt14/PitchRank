import { BASE_URL } from '@/lib/constants';

/**
 * Structured Data (Schema.org JSON-LD) component
 * Provides rich metadata for search engines
 */
export function StructuredData() {
  // Organization Schema
  const organizationSchema = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: 'PitchRank',
    url: BASE_URL,
    logo: `${BASE_URL}/logos/pitchrank-logo-dark.png`,
    description: 'Data-powered youth soccer team rankings and performance analytics',
    sameAs: [
      'https://twitter.com/pitchrank',
      'https://instagram.com/pitchrank',
      'https://facebook.com/pitchrank',
      'https://linkedin.com/company/pitchrank',
    ],
    contactPoint: {
      '@type': 'ContactPoint',
      contactType: 'Customer Support',
      email: 'pitchrankio@gmail.com',
    },
  };

  // WebSite Schema with Search Action
  const websiteSchema = {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: 'PitchRank',
    url: BASE_URL,
    description: 'Youth soccer team rankings with cross-age and cross-state support',
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${BASE_URL}/rankings?q={search_term_string}`,
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
    url: BASE_URL,
    description: 'Comprehensive ranking system for youth soccer teams across the United States',
    memberOf: {
      '@type': 'Organization',
      name: 'Youth Soccer Community',
    },
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
    </>
  );
}
