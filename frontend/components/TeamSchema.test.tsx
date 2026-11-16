import { describe, expect, it } from 'vitest';
import { TeamSchema } from './TeamSchema';

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

describe('TeamSchema', () => {
  it('rates the team on the same 0-100 scale as its bestRating and the page', () => {
    const schema = parseEmittedSchema(
      TeamSchema({ teamName: 'U12 Pre-MLS Next HG', powerScore: 0.4892, wins: 10, losses: 2, draws: 1 })
    );

    const rating = schema.aggregateRating as Record<string, unknown>;
    expect(rating.ratingValue).toBe('48.92');
    expect(rating.bestRating).toBe('100');
  });
});
