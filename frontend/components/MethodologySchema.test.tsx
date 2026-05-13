import { describe, expect, it } from 'vitest';
import { MethodologySchema } from './MethodologySchema';
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

describe('MethodologySchema', () => {
  it('emits Article schema with PitchRank Team author and the supplied dates', () => {
    const element = MethodologySchema({ datePublished: '2026-04-30', dateModified: '2026-05-01' });
    const schema = parseEmittedSchema(element);

    expect(schema['@type']).toBe('Article');
    expect((schema.author as { '@id': string })['@id']).toBe(`${BASE_URL}/authors/pitchrank-team`);
    expect(schema.datePublished).toBe('2026-04-30');
    expect(schema.dateModified).toBe('2026-05-01');
    expect((schema.publisher as { name: string }).name).toBe('PitchRank');
  });
});
