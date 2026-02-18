/**
 * BlogPosting structured data (Schema.org JSON-LD) for blog posts
 * Enables rich results for blog content in Google Search
 */

interface BlogPostSchemaProps {
  title: string;
  excerpt: string;
  slug: string;
  date: string;
  author: string;
  readingTime?: string;
  tags?: string[];
}

export function BlogPostSchema({
  title,
  excerpt,
  slug,
  date,
  author,
  tags,
}: BlogPostSchemaProps) {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

  const schema = {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: title,
    description: excerpt,
    url: `${baseUrl}/blog/${slug}`,
    datePublished: date,
    dateModified: date,
    author: {
      '@type': 'Person',
      name: author,
    },
    publisher: {
      '@type': 'Organization',
      name: 'PitchRank',
      url: baseUrl,
      logo: {
        '@type': 'ImageObject',
        url: `${baseUrl}/logos/pitchrank-logo-dark.png`,
      },
    },
    mainEntityOfPage: {
      '@type': 'WebPage',
      '@id': `${baseUrl}/blog/${slug}`,
    },
    image: {
      '@type': 'ImageObject',
      url: `${baseUrl}/logos/pitchrank-wordmark.svg`,
    },
    ...(tags && tags.length > 0 && { keywords: tags.join(', ') }),
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(schema),
      }}
    />
  );
}
