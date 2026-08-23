---
name: seo
description: >
  PitchRank-specific SEO surfaces and rules — state pillar pages, llms.txt
  regeneration, the blog frontmatter contract, the topic backlog, and analytics
  access. Use for any SEO, blog, llms.txt, state-pillar, or search-visibility
  task on pitchrank.io. Generic SEO methodology (audits, schema, E-E-A-T, Core
  Web Vitals) lives in the toprank and marketing-skills plugins (user-level,
  not tracked in this repo), not here.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash
---

# SEO — PitchRank Surfaces

## Surfaces

| Surface | Where | Notes |
|---------|-------|-------|
| State pillar pages | `frontend/lib/cohort-seo.ts` — `STATE_PILLAR_SLUGS` | Canonical slug + title per state; feeds llms.txt (pillar posts reach the sitemap via their blog slugs) |
| llms.txt | `frontend/scripts/generate-llms-txt.ts` → `frontend/public/llms.txt` | Generated file — never hand-edit the output |
| Blog posts | MDX frontmatter + TSX `BlogPost` objects | Field shape: `BlogPost` in `frontend/lib/blog.tsx`; date rules: `frontend/CLAUDE.md` → Content Authoring |
| Topic backlog | `brand/blog-topics.json` | Pre-vetted topics with target keyword, tags, and FAQ pairs |
| Structured data | `RankingsSchema`, `TeamSchema`, `BlogPostSchema`, `FAQSchema`, `BreadcrumbSchema` components | JSON-LD, rendered per page |
| Sitemap | `frontend/app/sitemap.ts` | Dynamic; no manual sitemap files |

## Hard Rules

Canonical source for rules 1 and 2: `frontend/CLAUDE.md` (Content Authoring
and Content Generation) — it wins on any disagreement.

1. **Regenerate llms.txt after any blog or pillar change.** Any blog post edit
   or `STATE_PILLAR_SLUGS` change requires:

   ```bash
   cd frontend && npm run generate-llms
   ```

   Commit the regenerated `public/llms.txt` in the same PR. The
   `frontend-llms-drift` CI job fails the PR if the committed file is stale.

2. **Bump `modifiedDate` on every blog edit.** Format is ISO-8601 UTC:
   `'YYYY-MM-DDT00:00:00Z'` — a bare `YYYY-MM-DD` triggers Google Rich Results
   "missing timezone" warnings. New posts set both `date` and `modifiedDate`
   to the publish date. No lint rule enforces this; it is checked at PR review.

3. **Verify every stat before publishing.** Cross-check claims against current
   in-window sources and against previously published posts. Never fabricate
   or infer claims (e.g., seeding rules) without a cited source.

## Analytics Access

- **GA4 credentials are Vercel-only** and cannot be pulled locally. Use the
  site's `/analytics` dashboard instead of trying to query GA4 directly.
- **GSC** goes through the `google-search-console` skill (user-level, not
  tracked in this repo). Mind privacy thresholds: low numbers are often
  dimension undercounting — retry with aggregate queries before concluding
  traffic is missing.
