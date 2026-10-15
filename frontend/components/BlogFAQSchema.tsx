/**
 * FAQ Schema (Structured Data)
 * Renders FAQPage JSON-LD for the Q&A a page shows; pass it the same list the page renders.
 * Helps Google display FAQ rich results in search.
 */

import type { FAQ } from '@/lib/blog-faqs';
import { safeJsonLd } from '@/lib/schema-utils';

interface BlogFAQSchemaProps {
  faqs: FAQ[];
}

export function BlogFAQSchema({ faqs }: BlogFAQSchemaProps) {
  const schema = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqs.map((faq) => ({
      '@type': 'Question',
      name: faq.question,
      acceptedAnswer: {
        '@type': 'Answer',
        text: faq.answer,
      },
    })),
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: safeJsonLd(schema),
      }}
    />
  );
}
