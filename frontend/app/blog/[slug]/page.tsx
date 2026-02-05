import { PageHeader } from '@/components/PageHeader';
import { BlogContent } from '@/components/BlogContent';
import { NewsletterSubscribe } from '@/components/NewsletterSubscribe';
import { getBlogPost, getAllBlogSlugs } from '@/lib/blog';
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

interface BlogPostPageProps {
  params: Promise<{
    slug: string;
  }>;
}

export async function generateStaticParams() {
  const slugs = getAllBlogSlugs();
  return slugs.map((slug) => ({
    slug,
  }));
}

export async function generateMetadata({ params }: BlogPostPageProps): Promise<Metadata> {
  const { slug } = await params;
  const post = getBlogPost(slug);
  const baseUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://pitchrank.io';
  
  if (!post) {
    return {
      title: 'Post Not Found',
    };
  }

  const canonicalUrl = `${baseUrl}/blog/${slug}`;

  return {
    title: post.title,
    description: post.excerpt,
    alternates: {
      canonical: canonicalUrl,
    },
    openGraph: {
      title: `${post.title} | PitchRank`,
      description: post.excerpt,
      url: canonicalUrl,
      siteName: 'PitchRank',
      type: 'article',
      publishedTime: post.date,
      authors: [post.author],
      images: [
        {
          url: `${baseUrl}/logos/pitchrank-wordmark.svg`,
          width: 1200,
          height: 630,
          alt: post.title,
        },
      ],
    },
    twitter: {
      card: 'summary_large_image',
      title: `${post.title} | PitchRank`,
      description: post.excerpt,
      images: [`${baseUrl}/logos/pitchrank-wordmark.svg`],
    },
  };
}

export default async function BlogPostPage({ params }: BlogPostPageProps) {
  const { slug } = await params;
  const post = getBlogPost(slug);

  if (!post) {
    notFound();
  }

  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title={post.title}
        description={post.excerpt}
        showBackButton
        backHref="/blog"
      />
      
      <div className="max-w-4xl mx-auto mt-8">
        <div className="mb-8 text-sm text-muted-foreground flex items-center gap-4">
          <span>{post.author}</span>
          <span>•</span>
          <time dateTime={post.date}>
            {new Date(post.date).toLocaleDateString('en-US', {
              year: 'numeric',
              month: 'long',
              day: 'numeric',
            })}
          </time>
          {post.readingTime && (
            <>
              <span>•</span>
              <span>{post.readingTime}</span>
            </>
          )}
        </div>

        <BlogContent content={post.content} />

        {/* Newsletter Subscription */}
        <div className="mt-16 mb-8">
          <NewsletterSubscribe />
        </div>
      </div>
    </div>
  );
}
