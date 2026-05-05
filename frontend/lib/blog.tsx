import fs from 'fs';
import path from 'path';
import matter from 'gray-matter';
import { blogPosts } from '@/content/blog-posts';

export interface BlogPost {
  slug: string;
  title: string;
  excerpt: string;
  content: React.ReactNode | string;
  date: string;
  modifiedDate?: string;
  author: string;
  readingTime?: string;
  tags?: string[];
  image?: string;
}

const BLOG_DIR = path.join(process.cwd(), 'content', 'blog');

/**
 * Parse a single markdown file into a BlogPost.
 */
function parseMarkdownFile(file: string): BlogPost {
  const raw = fs.readFileSync(path.join(BLOG_DIR, file), 'utf-8');
  const { data, content } = matter(raw);

  const slug = data.slug || file.replace(/\.(md|mdx)$/, '');
  return {
    slug,
    title: data.title || slug,
    excerpt: data.excerpt || '',
    content,
    date: data.date ? String(data.date) : '1970-01-01',
    modifiedDate: data.modifiedDate,
    author: data.author || 'PitchRank Team',
    readingTime: data.readingTime,
    tags: data.tags,
    image: data.image,
  };
}

/** Module-level cache for markdown posts (populated once per build). */
let _mdCache: BlogPost[] | null = null;

/**
 * Load blog posts from markdown files in content/blog/.
 * Cached after first call to avoid repeated filesystem reads.
 */
function getMarkdownBlogPosts(): BlogPost[] {
  if (_mdCache) return _mdCache;
  if (!fs.existsSync(BLOG_DIR)) return [];

  const files = fs.readdirSync(BLOG_DIR).filter((f) => f.endsWith('.md') || f.endsWith('.mdx'));
  _mdCache = files.map(parseMarkdownFile);
  return _mdCache;
}

/**
 * Get all blog posts (TSX + markdown) sorted by date (newest first)
 */
export function getAllBlogPosts(): BlogPost[] {
  const tsx = [...blogPosts] as BlogPost[];
  const md = getMarkdownBlogPosts();
  return [...tsx, ...md].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
}

/**
 * Get a single blog post by slug
 */
export function getBlogPost(slug: string): BlogPost | undefined {
  return getAllBlogPosts().find((post) => post.slug === slug);
}

/**
 * Get all blog post slugs for static generation
 */
export function getAllBlogSlugs(): string[] {
  return [...new Set(getAllBlogPosts().map((post) => post.slug))];
}
