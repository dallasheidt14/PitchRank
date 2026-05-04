/**
 * Generate frontend/public/llms.txt — a markdown content map for AI engines
 * (ChatGPT, Claude, Perplexity, Gemini) following the llms.txt convention.
 *
 * Sources:
 * - Blog posts: getAllBlogPosts() from @/lib/blog (merged TSX + MDX)
 * - State pillars: STATE_PILLAR_SLUGS from @/lib/cohort-seo
 * - Base URL: BASE_URL from @/lib/constants
 *
 * Output sections (in order):
 *   # PitchRank
 *   ## About
 *   ## Core Content
 *   ## Blog              (non-pillar posts only)
 *   ## State Pillars     (canonical home for STATE_PILLAR_SLUGS entries)
 *
 * Fail-closed: any parse error or missing pillar post exits non-zero.
 * Idempotent: deterministic ordering (insertion order on STATE_PILLAR_SLUGS,
 * date-desc on getAllBlogPosts()).
 *
 * Usage:
 *   npm run generate-llms              # writes to public/llms.txt
 *   npx tsx scripts/generate-llms-txt.ts > public/llms.txt
 *
 * CI: .github/workflows/ci.yml frontend-llms-drift job runs this and then
 * `git diff --exit-code public/llms.txt` to fail builds on stale committed output.
 */

import { getAllBlogPosts, type BlogPost } from '@/lib/blog';
import { STATE_PILLAR_SLUGS } from '@/lib/cohort-seo';
import { BASE_URL } from '@/lib/constants';

function buildPillarSet(): Set<string> {
  return new Set(Object.values(STATE_PILLAR_SLUGS).map((p) => p.slug));
}

function renderHeader(): string {
  return ['# PitchRank', '> Data-powered youth soccer team rankings and performance analytics', ''].join('\n');
}

function renderAbout(): string {
  return [
    '## About',
    'PitchRank provides the most accurate youth soccer rankings in the United States, covering U10-U19 boys and girls teams across all 50 states. Rankings are updated weekly based on game results from sanctioned leagues and tournaments.',
    '',
  ].join('\n');
}

function renderCoreContent(): string {
  const lines = [
    '## Core Content',
    `- [Methodology](${BASE_URL}/methodology): How PitchRank calculates rankings`,
    `- [National Rankings](${BASE_URL}/rankings): Top youth soccer teams across the United States`,
    `- [About PitchRank](${BASE_URL}/authors/pitchrank-team): The team behind the rankings`,
    '',
  ];
  return lines.join('\n');
}

function renderBlog(nonPillarPosts: BlogPost[]): string {
  const lines = ['## Blog', '*State-specific guides are listed under State Pillars below.*', ''];
  for (const post of nonPillarPosts) {
    lines.push(`- [${post.title}](${BASE_URL}/blog/${post.slug}): ${post.excerpt}`);
  }
  lines.push('');
  return lines.join('\n');
}

function renderStatePillars(allPosts: BlogPost[]): string {
  const postBySlug = new Map<string, BlogPost>();
  for (const post of allPosts) {
    postBySlug.set(post.slug, post);
  }

  const lines = ['## State Pillars'];
  for (const [, entry] of Object.entries(STATE_PILLAR_SLUGS)) {
    const post = postBySlug.get(entry.slug);
    if (!post) {
      throw new Error(
        `pillar slug "${entry.slug}" not found in blog posts (check STATE_PILLAR_SLUGS in lib/cohort-seo.ts)`
      );
    }
    lines.push(`- [${entry.title}](${BASE_URL}/blog/${entry.slug}): ${post.excerpt}`);
  }
  lines.push('');
  return lines.join('\n');
}

function main(): void {
  const allPosts = getAllBlogPosts();
  if (!allPosts.length) {
    throw new Error('empty post set returned by getAllBlogPosts()');
  }

  const pillarSet = buildPillarSet();
  const nonPillarPosts = allPosts.filter((p) => !pillarSet.has(p.slug));

  const output = [
    renderHeader(),
    renderAbout(),
    renderCoreContent(),
    renderBlog(nonPillarPosts),
    renderStatePillars(allPosts),
  ].join('\n');

  process.stdout.write(output);
}

try {
  main();
} catch (error) {
  const message = error instanceof Error ? error.stack || error.message : String(error);
  process.stderr.write(`[generate-llms-txt] failed: ${message}\n`);
  process.exit(1);
}
