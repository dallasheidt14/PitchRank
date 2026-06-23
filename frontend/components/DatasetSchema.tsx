import React from 'react';
import { BASE_URL, PITCHRANK_PUBLISHER, PITCHRANK_TEAM_AUTHOR } from '@/lib/constants';
import { safeJsonLd } from '@/lib/schema-utils';

export interface DatasetSchemaProps {
  name: string;
  description: string;
  slug: string;
  dateModified: string;
  temporalCoverage: string;
  variableMeasured: string[];
}

/**
 * Dataset structured data component.
 * Implements schema.org/Dataset so first-party reports are citable as a primary
 * data source (dataset rich results plus AI/GEO surfaces).
 * @see https://developers.google.com/search/docs/appearance/structured-data/dataset
 */
export function DatasetSchema({
  name,
  description,
  slug,
  dateModified,
  temporalCoverage,
  variableMeasured,
}: DatasetSchemaProps) {
  const datasetUrl = `${BASE_URL}/blog/${slug}`;

  const schema = {
    '@context': 'https://schema.org',
    '@type': 'Dataset',
    name,
    description,
    url: datasetUrl,
    creator: PITCHRANK_TEAM_AUTHOR,
    publisher: PITCHRANK_PUBLISHER,
    license: `${BASE_URL}/terms-of-service`,
    isAccessibleForFree: true,
    dateModified,
    temporalCoverage,
    variableMeasured,
    distribution: {
      '@type': 'DataDownload',
      contentUrl: datasetUrl,
      encodingFormat: 'text/html',
    },
  };

  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(schema) }} />;
}

export default DatasetSchema;
