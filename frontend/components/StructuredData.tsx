/**
 * Structured Data (Schema.org JSON-LD) component
 * Provides rich metadata for search engines
 */
export function StructuredData() {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

  // Organization Schema
  const organizationSchema = {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: 'PitchRank',
    url: baseUrl,
    logo: `${baseUrl}/logos/pitchrank-logo-dark.png`,
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
      email: 'dallasheidt14@gmail.com',
    },
  };

  // WebSite Schema with Search Action
  const websiteSchema = {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: 'PitchRank',
    url: baseUrl,
    description: 'Youth soccer team rankings with cross-age and cross-state support',
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
