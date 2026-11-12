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
| Structured data | `RankingsSchema`, `TeamSchema`, `BlogPostSchema`, `BlogFAQSchema`, `BreadcrumbSchema` components | JSON-LD, rendered per page; the visible `Breadcrumbs` emits its own BreadcrumbList, so don't pair it with `BreadcrumbSchema` |
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

4. **Change a recurring fact everywhere in one PR, or leave it.** Before
   editing a claim the site repeats (the PowerScore scale, a methodology
   statement), grep all of `frontend/` for every wording of it, including
   numbers derived from it (score bands, worked examples). Expect hits in
   `frontend/content/blog-posts.tsx`, `frontend/content/blog/` (Markdown and
   MDX posts both render), `frontend/lib/blog-faqs.ts` (rendered as JSON-LD
   that must agree with the post around it), `frontend/lib/methodology-faqs.ts`
   (the Methodology FAQ, shown and marked up from that one list), and display code such as
   `frontend/components/TeamSchema.tsx`. Check `.turbo/improvements.md` for
   an entry already tracking it. A partial change leaves a page's JSON-LD
   contradicting its own article.

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
   Count ranked teams per age group and gender too. Where boys play high school soccer
   in the fall, older boys teams last played in spring and drop off the board after
   `GlickoConfig.INACTIVE_DAYS` without a game; explain a thin older-boys board once
   `rankings_view` shows the missing teams as `Inactive` and the state high school
   association confirms the boys season. Give the window in rounded months, not the
   setting's day count, which changes when the cutoff is retuned.

   Report opponent-state shares as who teams played ("against out-of-state teams"),
   not where: the share is the opponent's `teams.state_code` (what `rankings_view.state`
   exposes), not the venue. It counts each ranked team's own games, so a game between
   two ranked in-state teams counts twice; phrase it as a share of the teams' own games
   ("Counting each team's own games, 49% were against…"), not of the distinct-game
   total. Describe a median as "half" ("half haven't recorded a game since late May"),
   never "most".
3. **Scan the state's ranked club names before linking its boards.** Foreign or
   out-of-state clubs mis-filed under the state code can fill a board, and the guide
   links every age-group board. When they do, hold the guide and backlog the mis-filing.
4. **Verify every external claim against a primary source for the current season.**
   - Take club-to-league membership from the leagues' own member lists: theecnl.com,
     mlssoccer.com/mlsnext, girlsacademyleague.com (including Aspire), and US Club
     Soccer's National 1 League. `teams.league` is a manual backfill's guess from team
     names, not a membership list.
   - Read ECNL membership from its standings pages, which render only in a browser after
     the conference is chosen; ECNL's post-season structure PDFs can omit a club. MLS
     NEXT member pages can still carry last season's label; when no current list exists,
     attribute membership to the season the list names rather than presenting it as current.
   - Take State Cup qualification, seeding and advancement from the state
     association's current rules page. Some associations split the cup into fall and
     spring competitions by age group, and some by gender too; say which competition
     any dates you give belong to.
   - Confirm club home cities on the club's own site.
5. **Write these template lines from sources, not from an older guide:**
   - how other ranking systems score teams (GotSport also awards league placement points; IMP-247)
   - how State Cup seeds and qualifies teams (from step 4's rules page; IMP-247)
   - the academic filter (NCAA initial eligibility uses core-course GPA, not test scores; IMP-247)
   - the PowerScore scale: 0–100 as the boards show it (`formatPowerScore`), in the body
     and the FAQ answers step 7 registers. The older guides' 0.0–1.0 wording is IMP-294's;
     Hard Rule 4 governs editing an existing claim, not a new guide.
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
  tracked in this repo) or the `seo` plugin (`seo:seo` skill, `seo` CLI and its
  reports). Mind privacy thresholds: low numbers are often
  dimension undercounting — retry with aggregate queries before concluding
  traffic is missing.
- **Read decay reports against the season.** The `seo` plugin's `decaying-pages` and
  `search-performance-overview` reports compare adjacent windows; a pair spanning Aug 1
  compares off-season with in-season traffic; `decaying-pages` takes
  `comparison: "year-over-year"` to avoid that once a year of data exists. Before calling
  a guide decaying, check whether its query moved to the state board while both stayed
  on page one.
- **The Search Analytics API rejects `groupType: "or"`** in `dimensionFilterGroups`
  (HTTP 400, whether sent through `seo gsc-query` or the google-search-console skill).
  Use one filter with `operator: "includingRegex"` and an anchored alternation such as
  `^(query one|query two)$`.
