import { describe, expect, it } from 'vitest';
import { BlogPostSchema } from './BlogPostSchema';
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

describe('BlogPostSchema', () => {
  it('emits BlogPosting schema with PitchRank Team Organization author', () => {
    const element = BlogPostSchema({
      title: 'Test Post',
      excerpt: 'A short excerpt.',
      slug: 'test-post',
      date: '2026-04-30',
    });
    const schema = parseEmittedSchema(element);

    expect(schema['@type']).toBe('BlogPosting');
    expect(schema.url).toBe(`${BASE_URL}/blog/test-post`);
    const author = schema.author as { '@type': string; '@id': string; name: string };
    expect(author['@type']).toBe('Organization');
    expect(author['@id']).toBe(`${BASE_URL}/authors/pitchrank-team`);
    expect(author.name).toBe('PitchRank Team');
    expect((schema.publisher as { name: string }).name).toBe('PitchRank');
  });
});
