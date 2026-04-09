/**
 * Blog-specific FAQ Schema (Structured Data)
 * Renders FAQPage JSON-LD for blog posts that have state-specific Q&A.
 * Helps Google display FAQ rich results in search.
 */

import type { FAQ } from '@/lib/blog-faqs';

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
        __html: JSON.stringify(schema).replace(/</g, '\\u003c'),
      }}
    />
  );
}
