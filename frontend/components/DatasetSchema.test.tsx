import { describe, expect, it } from 'vitest';
import { DatasetSchema } from './DatasetSchema';
import { BASE_URL } from '@/lib/constants';

interface JsonLdScriptElement {
  props: {
    type: string;
    dangerouslySetInnerHTML: { __html: string };
  };
}

function parseEmittedSchema(element: unknown): Record<string, unknown> {
  const html = (element as JsonLdScriptElement).props.dangerouslySetInnerHTML.__html;
  return JSON.parse(html.replace(/\\u003c/g, '<'));
}

const props = {
  name: 'State of Texas Youth Soccer 2026',
  description: 'First-party Texas rankings dataset.',
  slug: 'state-of-texas-youth-soccer-2026',
  dateModified: '2026-06-22',
  temporalCoverage: '2025-06-22/2026-06-22',
  variableMeasured: ['Ranked teams', 'Matches analyzed', 'Leagues covered'],
};

describe('DatasetSchema', () => {
  it('emits Dataset schema with creator entity, publisher, and free access', () => {
    const schema = parseEmittedSchema(DatasetSchema(props));

    expect(schema['@type']).toBe('Dataset');
    expect(schema.name).toBe(props.name);
    expect(schema.description).toBe(props.description);
    expect(schema.url).toBe(`${BASE_URL}/blog/${props.slug}`);
    expect(schema.isAccessibleForFree).toBe(true);
    expect(schema.dateModified).toBe(props.dateModified);
    expect(schema.temporalCoverage).toBe(props.temporalCoverage);
    expect(schema.variableMeasured).toEqual(props.variableMeasured);

    const creator = schema.creator as { '@type': string; '@id': string; name: string };
    expect(creator['@type']).toBe('Organization');
    expect(creator['@id']).toBe(`${BASE_URL}/authors/pitchrank-team`);
    expect((schema.publisher as { name: string }).name).toBe('PitchRank');
  });

  it('advertises an HTML DataDownload distribution at the page URL', () => {
    const schema = parseEmittedSchema(DatasetSchema(props));
    const distribution = schema.distribution as { '@type': string; contentUrl: string; encodingFormat: string };

    expect(distribution['@type']).toBe('DataDownload');
    expect(distribution.contentUrl).toBe(`${BASE_URL}/blog/${props.slug}`);
    expect(distribution.encodingFormat).toBe('text/html');
  });

  it('points the license at the terms-of-service URL', () => {
    const schema = parseEmittedSchema(DatasetSchema(props));
    expect(schema.license).toBe(`${BASE_URL}/terms-of-service`);
  });
});
