import { blogPosts } from '@/content/blog-posts';

export interface BlogPost {
  slug: string;
  title: string;
  excerpt: string;
  content: React.ReactNode;
  date: string;
  author: string;
  readingTime?: string;
  tags?: string[];
}

/**
 * Get all blog posts sorted by date (newest first)
 */
export function getAllBlogPosts(): BlogPost[] {
  return [...blogPosts].sort((a, b) => 
    new Date(b.date).getTime() - new Date(a.date).getTime()
  );
}

/**
 * Get a single blog post by slug
 */
export function getBlogPost(slug: string): BlogPost | undefined {
  return blogPosts.find(post => post.slug === slug);
}

/**
 * Get all blog post slugs for static generation
 */
export function getAllBlogSlugs(): string[] {
  return blogPosts.map(post => post.slug);
}

/**
 * Calculate reading time from content
 */
export function calculateReadingTime(content: string): string {
  const wordsPerMinute = 200;
  const words = content.trim().split(/\s+/).length;
  const minutes = Math.ceil(words / wordsPerMinute);
  return `${minutes} min read`;
}
