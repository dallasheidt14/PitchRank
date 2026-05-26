import React from 'react';
import { BASE_URL, PITCHRANK_PUBLISHER, PITCHRANK_TEAM_AUTHOR } from '@/lib/constants';
import { safeJsonLd } from '@/lib/schema-utils';

interface MethodologySchemaProps {
  datePublished: string;
  dateModified: string;
}

/** /methodology has no visible byline, so the JSON-LD author entity is the only attribution signal for AI engines. */
export function MethodologySchema({ datePublished, dateModified }: MethodologySchemaProps) {
  const pageUrl = `${BASE_URL}/methodology`;

  const schema = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: 'How PitchRank Youth Soccer Rankings Work',
    description:
      'How PitchRank calculates youth soccer team rankings using opponent quality, cross-league strength calibration, schedule strength, and machine-learning trend detection. Updated weekly with verified game data from all 50 states.',
    url: pageUrl,
    datePublished,
    dateModified,
    author: PITCHRANK_TEAM_AUTHOR,
    publisher: PITCHRANK_PUBLISHER,
    image: `${BASE_URL}/opengraph-image.png`,
    mainEntityOfPage: {
      '@type': 'WebPage',
      '@id': pageUrl,
    },
  };

  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(schema) }} />;
}

export default MethodologySchema;
