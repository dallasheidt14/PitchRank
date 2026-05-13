import { PITCHRANK_TEAM_AUTHOR } from '@/lib/constants';
import { safeJsonLd } from '@/lib/schema-utils';

/**
 * Self-referential Organization JSON-LD for the /authors/pitchrank-team page.
 * Adds a top-level @context so the entity validates standalone; other consumers
 * (BlogPostSchema, MethodologySchema) embed PITCHRANK_TEAM_AUTHOR as a nested
 * `author` value where the parent schema already supplies @context.
 */
export function AuthorEntitySchema() {
  const schema = {
    '@context': 'https://schema.org',
    ...PITCHRANK_TEAM_AUTHOR,
  };

  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(schema) }} />;
}

export default AuthorEntitySchema;
