import fs from 'fs';
import matter from 'gray-matter';
import path from 'path';
import { describe, expect, it } from 'vitest';
import { BLOG_FAQS } from './blog-faqs';

const NEW_SLUGS = ['ecnl-vs-mls-next', 'ecnl-vs-npl', 'what-is-ecnl'] as const;

const BLOG_DIR = path.join(__dirname, '..', 'content', 'blog');

/**
 * Paraphrases of questions already registered by other posts; normalized equality alone misses
 * these. Registered questions only — only a registered entry becomes a competing FAQPage
 * `Question`, so on-page headings are out of scope.
 */
const FORBIDDEN_QUESTION_VARIANTS = [
  'is ecnl or mls next higher level',
  'which is higher ecnl or mls next',
  'which is better ecnl or mls next',
  'is mls next higher than ecnl',
  'is ecnl higher than mls next',
  'what is the difference between ecnl and mls next',
  'difference between ecnl and mls next',
  'is ecnl or mls next better for my child',
  'what is the difference between ecnl and ecnl regional league',
  'difference between ecnl and ecnl rl',
  'ecnl vs ecnl rl',
  'is ecnl rl the same as ecnl',
  'what is npl in soccer',
  'what does npl stand for',
  'what does npl stand for in soccer',
  'what is the npl',
];

function readPost(slug: string): string {
  return fs.readFileSync(path.join(BLOG_DIR, `${slug}.mdx`), 'utf8');
}

function stripFrontmatter(raw: string): string {
  return raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '');
}

/**
 * Reduces MDX prose and registry text to a comparable plain form. Link, emphasis and curly-quote
 * stripping are load-bearing: an answer containing an inline citation, a bold span, or a
 * typographic apostrophe would otherwise fail despite rendering correctly.
 */
function normalize(text: string): string {
  return text
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/(?<![\w*_])([_*])(?!\s)([^\n]*?[^\s])\1(?![\w*_])/g, '$2')
    .replace(/\s+/g, ' ')
    .trim();
}

function normalizeQuestion(question: string): string {
  return normalize(question)
    .toLowerCase()
    .replace(/[^\w\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseRenderedFaqs(raw: string): Map<string, string> {
  const body = stripFrontmatter(raw);
  const section = body.split(/^## Frequently Asked Questions\s*$/m)[1] ?? '';
  const beforeFooter = section.split(/^---\s*$/m)[0] ?? '';
  const blocks = beforeFooter.split(/^### /m).slice(1);

  return new Map(
    blocks.map((block) => {
      const [heading, ...rest] = block.split(/\r?\n/);
      return [normalize(heading), normalize(rest.join('\n'))];
    })
  );
}

describe('BLOG_FAQS registration for the league comparison posts', () => {
  it.each(NEW_SLUGS)('%s has a BLOG_FAQS entry', (slug) => {
    expect(BLOG_FAQS[slug]).toBeDefined();
    expect(BLOG_FAQS[slug].length).toBeGreaterThan(0);
  });

  it.each(NEW_SLUGS)('%s declares a frontmatter slug matching its filename', (slug) => {
    // A slug that disagrees with its filename publishes the post at a different URL, which
    // silently drops BLOG_FAQS[slug] from the rendered JSON-LD and 404s every inbound link.
    expect(matter(readPost(slug)).data.slug).toBe(slug);
  });

  it.each(NEW_SLUGS)('%s renders every registered question with its own answer', (slug) => {
    const rendered = parseRenderedFaqs(readPost(slug));

    for (const { question, answer } of BLOG_FAQS[slug]) {
      const renderedAnswer = rendered.get(normalize(question));
      expect(renderedAnswer, `question not rendered on ${slug}: ${question}`).toBeDefined();
      expect(renderedAnswer, `answer does not match its question on ${slug}: ${question}`).toBe(normalize(answer));
    }
  });

  it('registers no question already owned by another post', () => {
    const newSlugs = new Set<string>(NEW_SLUGS);
    const existing = new Map<string, string>();

    for (const [slug, faqs] of Object.entries(BLOG_FAQS)) {
      if (newSlugs.has(slug)) continue;
      for (const { question } of faqs) {
        existing.set(normalizeQuestion(question), slug);
      }
    }

    for (const slug of NEW_SLUGS) {
      for (const { question } of BLOG_FAQS[slug]) {
        const owner = existing.get(normalizeQuestion(question));
        expect(owner, `${slug} reuses a question already registered elsewhere: ${question}`).toBeUndefined();
      }
    }
  });

  it('registers no question matching a known paraphrase of an existing one', () => {
    for (const slug of NEW_SLUGS) {
      for (const { question } of BLOG_FAQS[slug]) {
        expect(FORBIDDEN_QUESTION_VARIANTS, `${slug} registers a forbidden paraphrase: ${question}`).not.toContain(
          normalizeQuestion(question)
        );
      }
    }
  });

  it('registers no question twice across the three new posts', () => {
    const seen = new Map<string, string>();

    for (const slug of NEW_SLUGS) {
      for (const { question } of BLOG_FAQS[slug]) {
        const key = normalizeQuestion(question);
        expect(seen.get(key), `${slug} duplicates a question from an earlier post: ${question}`).toBeUndefined();
        seen.set(key, slug);
      }
    }
  });

  it('links the three posts to each other and to the rankings', () => {
    // Nothing else in the repo reads post bodies, so a later prose edit could silently remove a
    // link. The leading `[^!]` skips image embeds.
    const hasLink = (from: string, href: string) =>
      new RegExp(String.raw`(^|[^!])\[[^\]]*\]\(${href}\)`).test(readPost(from));

    for (const slug of NEW_SLUGS) {
      for (const target of NEW_SLUGS.filter((other) => other !== slug)) {
        expect(hasLink(slug, `/blog/${target}`), `${slug} must link to /blog/${target}`).toBe(true);
      }
      expect(hasLink(slug, '/rankings'), `${slug} must link to /rankings`).toBe(true);
    }

    expect(
      hasLink('youth-soccer-tryouts-2026', '/blog/ecnl-vs-mls-next'),
      'youth-soccer-tryouts-2026 must keep its inbound link to /blog/ecnl-vs-mls-next'
    ).toBe(true);
  });
});
