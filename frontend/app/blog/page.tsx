import { PageHeader } from '@/components/PageHeader';
import { BlogCard } from '@/components/BlogCard';
import { NewsletterSubscribe } from '@/components/NewsletterSubscribe';
import { BreadcrumbSchema } from '@/components/BreadcrumbSchema';
import type { Metadata } from 'next';
import { getAllBlogPosts } from '@/lib/blog';

const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';

export const metadata: Metadata = {
  title: 'Blog',
  description: 'Learn about youth soccer rankings, our algorithm methodology, and how PitchRank helps teams, coaches, and parents understand competitive soccer.',
  alternates: {
    canonical: `${baseUrl}/blog`,
  },
  openGraph: {
    title: 'Blog | PitchRank',
    description: 'Educational content about youth soccer rankings, algorithm methodology, and competitive soccer insights.',
    url: `${baseUrl}/blog`,
    siteName: 'PitchRank',
    type: 'website',
    images: [
      {
        url: '/logos/pitchrank-wordmark.svg',
        width: 1200,
        height: 630,
        alt: 'PitchRank Blog',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Blog | PitchRank',
    description: 'Educational content about youth soccer rankings and competitive soccer insights.',
    images: ['/logos/pitchrank-wordmark.svg'],
  },
};

export default function BlogPage() {
  const posts = getAllBlogPosts();

  return (
    <div className="container mx-auto py-8 px-4">
      <BreadcrumbSchema
        items={[
          { name: 'Blog', href: '/blog' },
        ]}
      />
      <PageHeader
        title="PitchRank Blog"
        description="Educational content about youth soccer rankings, our algorithm, and competitive soccer insights"
        showBackButton
        backHref="/"
      />
      
      <div className="max-w-5xl mx-auto mt-8">
        {posts.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-muted-foreground">No blog posts yet. Check back soon!</p>
          </div>
        ) : (
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {posts.map((post) => (
              <BlogCard key={post.slug} post={post} />
            ))}
          </div>
        )}

        {/* Newsletter Subscription */}
        <div className="mt-16 mb-8">
          <NewsletterSubscribe />
        </div>
      </div>
    </div>
  );
}
