import React from 'react';

interface BlogPostSchemaProps {
  title: string;
  excerpt: string;
  slug: string;
  date: string;
  author: string;
  readingTime?: string;
  tags?: string[];
  modifiedDate?: string;
  image?: string;
  articleSection?: string;
}

/**
 * BlogPosting structured data component
 * Implements Google's BlogPosting schema for enhanced search results
 * @see https://developers.google.com/search/docs/appearance/structured-data/article
 */
export function BlogPostSchema({
  title,
  excerpt,
  slug,
  date,
  author,
  readingTime,
  tags,
  modifiedDate,
  image,
  articleSection,
}: BlogPostSchemaProps) {
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';
  const postUrl = `${baseUrl}/blog/${slug}`;
  const imageUrl = image
    ? image.startsWith('http')
      ? image
      : `${baseUrl}${image}`
    : `${baseUrl}/opengraph-image.png`;
  
  const schema = {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: title,
    description: excerpt,
    url: postUrl,
    datePublished: date,
    dateModified: modifiedDate || date,
    author: {
      '@type': 'Person',
      name: author,
    },
    publisher: {
      '@type': 'Organization',
      name: 'PitchRank',
      logo: {
        '@type': 'ImageObject',
        url: `${baseUrl}/logos/pitchrank-wordmark.svg`,
      },
    },
    image: imageUrl,
    mainEntityOfPage: {
      '@type': 'WebPage',
      '@id': postUrl,
    },
    ...(articleSection && { articleSection }),
    ...(tags && tags.length > 0 && { keywords: tags.join(', ') }),
    ...(readingTime && { 
      // Extract minutes from "X min read" format
      wordCount: parseInt(readingTime) * 200, // Approximate 200 words per minute
    }),
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
    />
  );
}

// Also export as default for flexibility
export default BlogPostSchema;
