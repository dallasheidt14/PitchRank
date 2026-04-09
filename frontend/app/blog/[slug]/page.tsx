import { PageHeader } from '@/components/PageHeader';
import { BlogContent } from '@/components/BlogContent';
import { NewsletterSubscribe } from '@/components/NewsletterSubscribe';
import { BlogPostSchema } from '@/components/BlogPostSchema';
import { BlogFAQSchema } from '@/components/BlogFAQSchema';
import { BreadcrumbSchema } from '@/components/BreadcrumbSchema';
import { getBlogPost, getAllBlogSlugs } from '@/lib/blog';
import { BLOG_FAQS } from '@/lib/blog-faqs';
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { BASE_URL } from '@/lib/constants';

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
  if (!post) {
    return {
      title: 'Post Not Found',
    };
  }

  const canonicalUrl = `${BASE_URL}/blog/${slug}`;
  const heroImage = post.image ? `${BASE_URL}${post.image}` : `${BASE_URL}/opengraph-image.png`;

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
          url: heroImage,
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
      images: [heroImage],
    },
  };
}

export default async function BlogPostPage({ params }: BlogPostPageProps) {
  const { slug } = await params;
  const post = getBlogPost(slug);

  if (!post) {
    notFound();
  }

  const heroImagePath = post.image || '/opengraph-image.png';

  return (
    <div className="container mx-auto py-8 px-4">
      <BlogPostSchema
        title={post.title}
        excerpt={post.excerpt}
        slug={slug}
        date={post.date}
        author={post.author}
        readingTime={post.readingTime}
        tags={post.tags}
        image={heroImagePath}
        articleSection={post.tags?.[0]}
      />
      <BreadcrumbSchema
        items={[
          { name: 'Blog', href: '/blog' },
          { name: post.title, href: `/blog/${slug}` },
        ]}
      />
      {BLOG_FAQS[slug] && <BlogFAQSchema faqs={BLOG_FAQS[slug]} />}
      <PageHeader title={post.title} description={post.excerpt} showBackButton backHref="/blog" />

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
