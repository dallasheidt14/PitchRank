---
name: seo
description: >
  PitchRank-specific SEO surfaces and rules — state pillar pages and state guide
  posts, llms.txt regeneration, the blog frontmatter contract, the topic backlog,
  and analytics access. Use for any SEO, blog, state guide, llms.txt,
  state-pillar, or search-visibility task on pitchrank.io. Generic SEO methodology (audits, schema, E-E-A-T, Core
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

## State Guide Posts

A state guide is `frontend/content/blog/<state>-youth-soccer-rankings-guide.mdx`.
Mirror the most recent guide's structure.

1. **Pick the state.** List the guides on `origin/main`, not the local tree. Rank
   uncovered states by GSC page-dimension impressions on `/rankings/<code>`, which
   undercounts less than the query dimension, and by published ranked teams.
2. **Count ranked teams from `rankings_view` with `status = 'Active'`.** Counting every
   status gives tracked teams, which run several times larger. The view's state column
   is `state` and its `gender` is `M`/`F`. Status meanings are in
   `.claude/skills/matching-tournament-rosters/references/reading-the-rankings.md`.
3. **Scan the state's ranked club names before linking its boards.** Foreign or
   out-of-state clubs mis-filed under the state code can fill a board, and the guide
   links every age-group board. When they do, hold the guide and backlog the mis-filing.
4. **Verify every external claim against a primary source for the current season.**
   - Take club-to-league membership from the leagues' own member lists: theecnl.com,
     mlssoccer.com/mlsnext, girlsacademyleague.com (including Aspire), and US Club
     Soccer's National 1 League. `teams.league` is a manual backfill's guess from team
     names, not a membership list.
   - Take State Cup qualification, seeding and advancement from the state
     association's current rules page.
   - Confirm club home cities on the club's own site.
5. **Write the three template lines IMP-247 tracks from sources, not from an older
   guide:**
   - how other ranking systems score teams (GotSport also awards league placement points)
   - how State Cup seeds and qualifies teams (from step 4's rules page)
   - the academic filter (NCAA initial eligibility uses core-course GPA, not test scores)
6. **Use the standard internal link set:** `/rankings` once, `/rankings/<code>` three
   times, the 18 age-group boards (U10–U17 and U19, boys and girls), and
   `https://pitchrank.io` twice.
7. **Register the guide.**
   - Add a `STATE_PILLAR_SLUGS` entry.
   - Add five `BLOG_FAQS` entries in `frontend/lib/blog-faqs.ts` whose answers match the
     rendered FAQ text verbatim. Check them with the normalization in
     `frontend/lib/blog-faqs.test.ts`, whether or not that test lists the new slug.
   - Regenerate llms.txt.

## Analytics Access

- **GA4 credentials are Vercel-only** and cannot be pulled locally. Use the
  site's `/analytics` dashboard instead of trying to query GA4 directly.
- **GSC** goes through the `google-search-console` skill (user-level, not
  tracked in this repo). Mind privacy thresholds: low numbers are often
  dimension undercounting — retry with aggregate queries before concluding
  traffic is missing.
