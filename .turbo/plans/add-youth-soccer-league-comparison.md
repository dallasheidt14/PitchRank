---
status: done
---

# Plan: Add Youth Soccer League-Comparison Blog Pages

## Context

`/blog/youth-soccer-levels-explained` is the highest-impression page on pitchrank.io and its worst
converter: **24,877 impressions and 182 clicks (0.73% CTR) in the last 28 days** (GSC,
`sc-domain:pitchrank.io`, 2026-06-24 → 2026-07-21). It ranks well but cannot satisfy the intent it
attracts. The queries driving those impressions are league *comparisons* the page does not answer
in a SERP snippet:

| Query | Impressions | Clicks | Position |
|---|---|---|---|
| is npl or ecnl better | 678 | 0 | 8.2 |
| national 1 league vs ecnl | 167 | 0 | 10.4 |
| youth soccer pyramid | 151 | 0 | 8.6 |
| what does ecnl stand for | 138 | 0 | 9.8 |
| ecnl soccer | 92 | 0 | 2.4 |
| mls next | 30 | 0 | 2.2 |
| ecnl rl | 21 | 0 | 2.9 |
| edp soccer | 21 | 0 | 2.9 |

Also present: `difference between ecnl and ecnl rl`, `mls next vs ecnl vs npl`, `is ecnl the highest
level of soccer`, `what is after mls next`, `ecnl vs npl`, `is ecnl rl better than npl`, `npl vs mls
next`, `is usys better than ecnl`, `what does npl stand for in soccer`, `ecnl levels`, `ecnl
meaning`, `usys national league vs ecnl`. The whole league/level query cluster runs **5,985
impressions at 0.48% CTR**.

This plan adds three dedicated comparison pages that answer those questions directly. Estimated
upside ~+300–400 clicks/month. Secondary benefit: these are exactly the questions parents ask
LLMs, and ChatGPT referrals to the site are up 39% month-over-month (47 → 72 sessions/28d, GA4).

**Hard constraint — the protected page is NOT TOUCHED AT ALL.**
`frontend/content/blog/youth-soccer-levels-explained.mdx` holds live top-3 rankings (#2.4
`ecnl soccer`, #2.2 `mls next`, #2.9 `ecnl rl`, #2.9 `edp soccer`) that must not regress. This plan
makes **zero** changes to that file — no links, no `modifiedDate` bump, nothing. It must not appear
in the diff. That makes the guard a single unambiguous command (see Verification) instead of a
content-inspection apparatus.

*Why no outbound links (this was reconsidered deliberately):* earlier drafts added ≤4 links from the
protected page to the new pages. The guard needed to police even that link-only edit failed review
three times running — first absent, then passing vacuously because its `git diff` pathspec resolved
relative to the wrong directory, then defeated by wrapping the frontmatter `title` in a markdown
link (which the guard's own link-stripping normalization reduced back to the baseline string).
Separately, linking *from* the page that ranks #2.2 for `mls next` *to* a new page about MLS NEXT
hands exact-match anchor equity to a competitor for its own head term. The new pages remain fully
discoverable via the sitemap, the blog index, `llms.txt`, cross-links to each other, and one
inbound link from `youth-soccer-tryouts-2026` (Step 5). Adding links from the protected page later —
as an isolated follow-up PR, after T+28 monitoring confirms rankings held — remains available and
would be trivially reviewable on its own.

**Scope note — "protected page untouched" ≠ "no existing file touched".** This plan edits exactly one
pre-existing blog post, `frontend/content/blog/youth-soccer-tryouts-2026.mdx`, adding a single link
plus a `modifiedDate` bump (Step 5). That post holds **no top-3 rankings** and is therefore not
protected; it is edited *because* it already competes for `/blog/ecnl-vs-mls-next`'s head intent via
its own FAQ (`:199` visible, `blog-faqs.ts:1023` registered), and a contextual link is the standard
way to consolidate that overlap. The hard constraint below concerns
`youth-soccer-levels-explained.mdx` only, and is unaffected.

### Decisions locked before drafting

1. **Three pages, not four.** A `youth soccer pyramid` page was considered and **rejected** — that
   cluster is the core topic of the protected page, so a new page would compete with it directly.
   Pyramid queries stay with the existing page.
2. **Single H1 on new pages.** `frontend/app/blog/[slug]/page.tsx:103` already renders the title as
   an `<h1>` via `PageHeader` (the actual `<h1>` is `frontend/components/PageHeader.tsx:24`), and
   every existing post then emits a *second* H1 in its markdown body. New pages omit the body H1 and
   start at `##`. Existing posts are not touched.
3. **First-party data with stable framing.** Pages cite PitchRank's own ranking data using round,
   slow-moving figures so they do not go stale when rankings update each Monday.
   **Do not invent the figure.** Read it from the same source the site itself uses
   (`api.getDbStats()` / the `homepage_stats` cache — see `frontend/lib/stats.ts`) and round
   **down**. For reference, `frontend/lib/stats.ts:13` sets
   `FALLBACK_STATS = { totalTeams: 59000, totalGames: 1_100_000 }` with the comment "Kept at or
   below the true live counts so marketing copy never overstates" — any prose figure must respect
   that same discipline. Hardcoding a count in prose is a deliberate, narrow exception to the
   dynamic-count direction of PRs #935/#936; keep it conservative and sourced.
4. **Strictly neutral comparison.** The pages do **not** declare which league is "better" or advise
   which to choose. They front-load a *factual structural* answer (which leagues operate at which
   tier, who runs them, how entry works) and let parents draw conclusions. Neutral does not mean
   vague — sentence one still answers the structural question directly.
5. **Primary sources + first-party data.** Every factual claim traces to an official league source
   (ECNL, MLS NEXT, US Club Soccer, US Youth Soccer, EDP) or to PitchRank's own rankings. No hunted
   expert quotes. **No fabrication of any kind** — see Step 2.
6. **Never target the protected page's head terms.** The new pages must **not** target the bare
   head terms `ecnl soccer`, `mls next`, `ecnl rl`, or `edp soccer`. All four are live top-3
   rankings held by `/blog/youth-soccer-levels-explained`, and aiming a new page at them is the
   same cannibalization risk that got the pyramid page rejected in decision 1 — except against
   *live* positions rather than a position-8.6 query. New pages target long-tail comparison and
   definitional intent only.
7. **The protected page is not edited at all.** No outbound links, no `modifiedDate` bump. This
   applies to `youth-soccer-levels-explained.mdx` specifically — **not** to every pre-existing file.
   One other post, `youth-soccer-tryouts-2026.mdx`, does get a one-line link plus a `modifiedDate`
   bump (Step 5); it holds no top-3 rankings and is not protected. See the
   hard-constraint paragraph above for the reasoning. This is what makes the guard a one-line
   `git diff --quiet` rather than a diff parser — and a one-line guard cannot be defeated by
   content that normalizes back to the baseline.

## Pattern Survey

**Baseline: `origin/main` @ `2aba761a3`.** Every fact below was confirmed via
`git show origin/main:<path>` / `git ls-tree origin/main`, not the working tree.

### Analogous Features

**(1) Blog authoring paths — two, both merged at read time**

- `frontend/lib/blog.tsx:62` — `getAllBlogPosts()` = `[...blogPosts (TSX), ...getMarkdownBlogPosts() (filesystem)]`, sorted date-desc at `:65` (**by date only — no secondary tiebreak**; see the date contract in Step 4). Both paths produce the same `BlogPost` interface (`frontend/lib/blog.tsx:6-17`).
- **Path A (Markdown/MDX)** — `frontend/content/blog/*.{md,mdx}`, **discovered by filesystem glob** (`fs.readdirSync(BLOG_DIR).filter(f => f.endsWith('.md') || f.endsWith('.mdx'))`, `frontend/lib/blog.tsx:54` — **unsorted**). No registry entry needed. Parsed with `gray-matter` at `frontend/lib/blog.tsx:24-40`. MDX example: `frontend/content/blog/ohio-youth-soccer-rankings-guide.mdx` (306 lines / ~3,200 words).
- **Path B (Programmatic TSX)** — `frontend/content/blog-posts.tsx:51` `export const blogPosts: BlogPost[]`, an **explicit registry array** (3,432 lines, 8 posts). `content` is JSX. TSX examples: California at `frontend/content/blog-posts.tsx:1223`, Texas at `:1900`.
- **CRITICAL — `/blog/youth-soccer-levels-explained` is MDX**, not TSX: `frontend/content/blog/youth-soccer-levels-explained.mdx` (201 lines, ~2,190 words, `date: '2026-04-29'`, `modifiedDate: '2026-04-30T00:00:00Z'`). **This plan makes no edits to it** (locked decision 7) — it is read-only context, and the Verification guard asserts it is absent from the diff entirely.
- **`.mdx` is a lie — it is plain markdown.** `frontend/components/BlogContent.tsx:34` renders string content through `react-markdown` + `remark-gfm` only. There is **no MDX compiler**: `frontend/package.json` has `react-markdown ^10.1.0`, `remark-gfm ^4.0.1`, `gray-matter ^4.0.3` and **no** `@next/mdx` / `next-mdx-remote`; `frontend/next.config.ts` has no `pageExtensions`/mdx config. **JSX/custom components in a `.mdx` file will not render.**

**(2) Metadata contract**

- Type: `frontend/lib/blog.tsx:6-17` — `BlogPost { slug, title, excerpt, content, date, modifiedDate?, author, readingTime?, tags?, image? }`.
- Required in practice: `title`, `slug`, `excerpt`, `author`, `date`. Defaults at `frontend/lib/blog.tsx:29-38`.
- **`keywords:` in existing MDX frontmatter is dead weight** — `parseMarkdownFile` never reads it.
- `generateMetadata` at `frontend/app/blog/[slug]/page.tsx:28-70`: `title: post.title` (root template appends `| PitchRank` — `frontend/app/layout.tsx:44-47`), `description: post.excerpt`, `alternates.canonical = ${BASE_URL}/blog/${slug}`, OG `type: 'article'`, image = `post.image` ?? `/opengraph-image.png`, `twitter: summary_large_image`.
- Observed lengths: titles 36–99 chars (most ≤ 58); excerpts 132–205 chars.

**(3) FAQ registration — visible and schema FAQs are TWO SOURCES, not one**

- `frontend/lib/blog-faqs.ts` (1,028 lines): `export interface FAQ { question: string; answer: string }` and `export const BLOG_FAQS: Record<string, FAQ[]>`, **keyed by slug**. **32 slugs registered**. The protected page's entry is `BLOG_FAQS['youth-soccer-levels-explained']` at **`frontend/lib/blog-faqs.ts:958`** (8 entries) — **do not touch it** (see Step 6).
- Wiring: `frontend/app/blog/[slug]/page.tsx:101` — `{BLOG_FAQS[slug] && <BlogFAQSchema faqs={BLOG_FAQS[slug]} />}`. `BlogFAQSchema` emits **FAQPage JSON-LD only — zero visible DOM**.
- ⚠️ **FAQ rich results no longer exist.** Google stopped showing the FAQ rich result in Search on
  **2026-05-07** and removed the feature's documentation on **2026-06-15**
  (https://developers.google.com/search/docs/appearance/structured-data/faqpage — verified 2026-07-27).
  So `FAQPage` markup on this site earns **no SERP treatment today**, and no page here — including the
  protected one — has a "live FAQPage rich result". This does **not** make the markup pointless:
  Google still parses it for page understanding, and it directly serves this plan's LLM/GEO goal
  (ChatGPT referrals up 39% MoM). But it changes *why* FAQ differentiation matters — see Step 6 — and
  it makes any "FAQPage eligible" check unsatisfiable, since the Rich Results Test no longer reports
  the type at all (see Verification).
- Visible FAQs come from the post body (`youth-soccer-levels-explained.mdx:165`, Ohio `:270`).
- **Authors must duplicate FAQ content.** The two already drift on `origin/main` (schema "What is the difference…" vs page "What's the difference…"). Contrast `frontend/components/RankingsPillar.tsx:12` `buildRankingsPillarFaqItems`, commented "schema must match rendered content" — the only single-source prior art, and it is TSX-only.

**(4) Schema components**

- `frontend/components/BlogPostSchema.tsx` — `BlogPosting`; `dateModified: modifiedDate || date`; author/publisher from `PITCHRANK_TEAM_AUTHOR` / `PITCHRANK_PUBLISHER` in `frontend/lib/constants.ts`; `wordCount` derived from `parseInt(readingTime) * 200`.
- `frontend/components/BlogFAQSchema.tsx` — `FAQPage`; prop `{faqs: FAQ[]}`.
- `frontend/components/BreadcrumbSchema.tsx` — `BreadcrumbList`.
- Shared helper `safeJsonLd` from `@/lib/schema-utils`. No `<JsonLd>` wrapper.
- All wired centrally at `frontend/app/blog/[slug]/page.tsx:83-99` — **a new post gets BlogPosting + BreadcrumbList for free**; only FAQPage requires a registry entry.

**(5) llms.txt pipeline**

- `frontend/scripts/generate-llms-txt.ts:89` — `main()` calls `getAllBlogPosts()` and `STATE_PILLAR_SLUGS`. **A new non-state post is picked up automatically** into `## Blog` via `renderBlog()` (`:60`). Note `renderStatePillars()` (`:69`) builds a slug→post map and iterates `STATE_PILLAR_SLUGS`, so **pillar order is independent of post order** — only the `## Blog` section is sensitive to post ordering.
- `frontend/public/llms.txt` (53 lines) is committed and **drift-verified in CI**: `.github/workflows/ci.yml` job `frontend-llms-drift` (lines 97-114) runs `npm run generate-llms` then `git diff --exit-code public/llms.txt`.
- `npm run generate-llms` = `tsx scripts/generate-llms-txt.ts > public/llms.txt` (`frontend/package.json`).
- **Hook is NOT in the repo.** Only tracked hook is `frontend/.husky/pre-commit` (`cd frontend && npx lint-staged`). The llms auto-regen lives in untracked local `C:\PitchRank\.claude\hooks\pre-commit-guard.sh`, triggering on `^frontend/(app/blog/|content/blog/|lib/(blog|cohort-seo|constants)\.tsx?$)`. **`frontend/lib/blog-faqs.ts` does NOT match** — and CI has no auto-regen at all.

**(6) Internal linking / cross-link registration**

- The cross-link map is **state-only**: `frontend/lib/cohort-seo.ts:116` `STATE_PILLAR_SLUGS` (21 states), consumed by `getRelatedGuide()` at `:140`, used once at `frontend/app/rankings/[region]/[ageGroup]/[gender]/page.tsx:198`. **A non-state comparison post has no analogous registry to join.**
- `frontend/components/RankingsPillar.tsx:37` `POPULAR_STATES` `hasGuide` flag — also state-only.
- blog→rankings links are **hand-authored markdown, not a helper** (Ohio `:254-268` GFM table; blockquote CTAs at `:38`, `:252`).
- **Registration points for a NON-STATE post:** the `.mdx` file (mandatory), a `BLOG_FAQS[slug]` entry (conventional), a regenerated `llms.txt` (CI-gated). `STATE_PILLAR_SLUGS`, `POPULAR_STATES`, `BLOG_DATASETS`, and `next.config.ts` redirects are **not applicable**.
- **Blog index automatic** (`frontend/app/blog/page.tsx:41`). **Sitemap automatic** (`frontend/app/sitemap.ts:61`, priority 0.6). **Static params automatic** (`frontend/app/blog/[slug]/page.tsx:21`).

**(7) Content conventions**

- Exactly one `#` H1 inside the body — **which duplicates the `<h1>` from `PageHeader`** (`frontend/app/blog/[slug]/page.tsx:103`; the `<h1>` itself is `frontend/components/PageHeader.tsx:24`). Established but SEO-imperfect; this plan deviates (decision 2).
- Intro paragraphs sit between the body H1 and the first `##`. No verdict box, no TOC.
- `##` major sections, `###` sub-sections and FAQ questions. Both pillars end with `## Frequently Asked Questions` (8 Q&A) → `---` → bold **About PitchRank:** footer with `/rankings` links.
- CTAs are markdown blockquotes: `> **Ready to check?** [See all Ohio youth soccer rankings](/rankings/oh)`.
- Tables: GFM pipe tables (`remark-gfm`), styled by `MARKDOWN_STYLES` in `frontend/components/BlogContent.tsx:21-22`.
- **No shared MDX components exist.**
- Typical state pillar: ~3,200 words. `youth-soccer-levels-explained` ~2,190 words / `'11 min read'`. `readingTime` is author-declared and feeds `wordCount` in JSON-LD.

**(8) Tests**

- Runner: **`npm run test`** = `vitest run` (`frontend/package.json`), from `C:/PitchRank/frontend`. Config `frontend/vitest.config.ts` (happy-dom, excludes `e2e/**`).
- `frontend/components/BlogPostSchema.test.tsx`, `frontend/components/DatasetSchema.test.tsx`, `frontend/lib/schema-utils.test.ts`, `frontend/lib/cohort-seo.test.ts`, `frontend/__tests__/middleware.test.ts:244`.
- **Gaps:** nothing covers post registration/discovery, FAQ↔visible-content parity, `BLOG_FAQS` key validity, llms.txt content, or `generateMetadata`.

### Reusable Utilities

- `frontend/lib/blog.tsx:62` `getAllBlogPosts()` — single source feeding **five consumers**: the blog index (`frontend/app/blog/page.tsx:41`), `getBlogPost`, `getAllBlogSlugs`, `frontend/app/sitemap.ts:61`, `generateStaticParams`, and the llms.txt generator. **Do not modify it** — two of those consumers are user/crawler-facing, so a change there is not additive.
- `frontend/lib/blog.tsx:72` / `:79` `getBlogPost(slug)` / `getAllBlogSlugs()` — `getAllBlogSlugs` de-dupes via `new Set`, so a TSX/MDX slug collision silently resolves to the TSX entry.
- `frontend/lib/schema-utils.ts` `safeJsonLd(schema)` — mandatory JSON-LD serializer.
- `frontend/lib/constants.ts` — `BASE_URL`, `PITCHRANK_PUBLISHER`, `PITCHRANK_TEAM_AUTHOR`. Never hardcode a domain.
- `frontend/components/RankingsPillar.tsx:12` `buildRankingsPillarFaqItems` — single-source FAQ prior art (TSX-only). `POPULAR_STATES` is at `:41`.

### Convention Anchors

- **`dateModified` bump-on-edit (PR #720 = `000e88993`)**: `frontend/CLAUDE.md:284-289`. Every blog post edit must bump `modifiedDate`. Format **ISO-8601 UTC `'YYYY-MM-DDT00:00:00Z'`** — bare `YYYY-MM-DD` triggers Rich Results "missing timezone" warnings. Checked at PR review; no lint rule.
  - ⚠️ **Documented deviation:** the three new posts use `T09:00:00Z` / `T10:00:00Z` / `T11:00:00Z`
    rather than the documented `T00:00:00Z` hour. This is deliberate and narrow — the *format* still
    matches the convention (quoted ISO-8601 UTC), only the hour differs. **The reason is sort
    ordering, not timezones:** `frontend/lib/blog.tsx:65` sorts by date only and `:54` reads the
    directory unsorted, so identical timestamps fall back to filesystem order, which differs between
    Windows/NTFS locally and ext4 on the CI runner — that would break the `llms.txt` drift check.
    Distinct hours make the comparator non-zero for every pair. Call this out in the PR description
    so a reviewer applying `frontend/CLAUDE.md:287` does not read it as a mistake.
- **Derived-file regeneration**: root `CLAUDE.md:30` — regenerate llms.txt before committing. Procedure `frontend/CLAUDE.md:293-303`.
- **Slug = filename**, with a matching explicit `slug:` in frontmatter.
- **Schema is centrally wired, not per-post.**
- **Redirects** live in `frontend/next.config.ts:42-69`. `youth-soccer-levels-explained` has none and **none should be added**.
- **`.agents/product-marketing.md` does NOT exist at `origin/main`** — untracked local-only. It cannot serve as a source of truth for product claims.

### Proposed Alignment

Follow the MDX path (`frontend/content/blog/<slug>.mdx`), mirroring `ohio-youth-soccer-rankings-guide.mdx` structurally — filesystem discovery gives blog index, sitemap, `generateStaticParams`, BlogPosting JSON-LD, BreadcrumbList, and llms.txt inclusion for free. The TSX registry only earns its cost when a post needs live data or React components, which comparison prose does not. Deviate on the body H1 (decision 2). Do not restructure the shared FAQ rendering — guard the duplication with a parity test instead (Step 6).

---

## Pre-flight: Branch and Working Tree (READ FIRST)

**The local checkout is not safe to branch from as-is.** At planning time
`C:/PitchRank` was on `fix/modular11-events-division-mapping`, **83 commits behind
`origin/main`**, with **143 modified files** — including two files this plan touches
(`frontend/lib/blog-faqs.ts`, `frontend/public/llms.txt`) — plus unrelated *staged* work
(`config/settings.py`, `docs/superpowers/specs/2026-05-28-somsports-tournament-scraper-design.md`).

Branching in place would bundle unrelated staged work and start from a stale base. Per the
project's worktree rule, staged work + unrelated HEAD is the documented case for isolating.

Before any edit:

```bash
cd C:/PitchRank && git fetch origin --prune
git worktree add C:/pitchrank-league-pages -b feat/league-comparison-pages origin/main
cd C:/pitchrank-league-pages && git status --porcelain   # MUST be empty
git diff --stat origin/main                              # MUST be empty
```

Notes:
- The worktree has no `node_modules` / `.env.local`. **`npm ci` in
  `C:/pitchrank-league-pages/frontend` is mandatory**, and **every** generation, test, lint,
  format, typecheck, and build command in this plan must run **inside the worktree**.
- **Do NOT run any verification from the main `C:/PitchRank/frontend` checkout.** Three concrete
  reasons, all verified: (a) `npm run generate-llms` *overwrites* `public/llms.txt`, which is
  already dirty there, destroying unrelated work; (b) that checkout is 83 commits behind and is
  **missing four blog posts** present at the baseline — `2026-06-15-massachusetts-youth-soccer-rankings.md`,
  `2026-06-22-connecticut-youth-soccer-rankings.md`, `2026-06-29-best-u13-soccer-teams.md`, and
  `2026-07-07-best-u11-soccer-teams.md` (all legacy dated non-pillar `.md` posts) — so a generated
  `llms.txt` would silently **drop four `## Blog` entries** and fail the CI drift check; (c) the
  generator and build read `content/blog/` from `process.cwd()`, so results would describe the
  wrong tree. *(Note: the two registered state pillars `indiana-` and `missouri-youth-soccer-rankings-guide.mdx`
  ARE present in the main checkout, so `renderStatePillars()` does not hard-fail there — the failure
  mode is silent omission, not a crash. Reason (a) alone is sufficient to mandate the worktree.)*
- The untracked llms.txt auto-regen hook lives in `C:/PitchRank/.claude/hooks/` and **will not
  exist in the worktree** — `npm run generate-llms` must be run manually (Step 7).
- Clean up after merge: `git worktree remove C:/pitchrank-league-pages` and delete the branch.

## Implementation Steps

1. **Create the branch, install dependencies, and verify a clean baseline**
   - Follow the Pre-flight block above verbatim. Do not proceed until
     `git status --porcelain` is empty and `git diff --stat origin/main` is empty.
   - **Install dependencies now, before any later step needs them:**
     ```bash
     cd C:/pitchrank-league-pages/frontend && npm ci
     cp C:/PitchRank/frontend/.env.local C:/pitchrank-league-pages/frontend/.env.local
     ```
     `npm ci` must precede Steps 4-5, which invoke `npx prettier --write` — without it, `npx` would
     fetch an unpinned Prettier (or prompt interactively / fail), producing formatting that may not
     match what CI's pinned version expects. Copying `.env.local` keeps the build step in
     Verification quiet enough to read; see the build bullet there for what to do if you skip it.
   - **Record the baseline commit** for every `git diff` guard in the Verification section:
     ```bash
     cd C:/pitchrank-league-pages && git merge-base HEAD origin/main
     ```
     Use this SHA rather than the bare `origin/main` ref in all diff guards — it is the branch point
     and stays stable even if `origin/main` later advances. At planning time it resolves to
     `2aba761a3`.
     - ⚠️ **Write the SHA down; do not rely on a `$BASE` shell variable.** Each Bash tool invocation
       starts a fresh shell, so a variable exported in one command is **gone** in the next. Every
       guard in Verification therefore recomputes the merge-base inline via command substitution.
       See the fail-open warning at the top of Verification for why this is load-bearing rather than
       stylistic.

2. **Evidence gathering — sources before prose (blocking; no fabrication)**
   - Collect and record a source URL for every factual claim the three pages will make, from
     official primary sources only:
     - `theecnl.com` — ECNL and ECNL Regional League (ECNL RL)
     - `mlssoccer.com/mlsnext` — MLS NEXT
     - **`usclubsoccer.org` — NPL and the National 1 League.** ⚠️ **NPL is operated by US Club
       Soccer, NOT US Youth Soccer.** Getting this wrong is a factual error about the league's
       governing body. Start from https://usclubsoccer.org/programs/leagues/
     - `usyouthsoccer.org` — the **USYS National League only** (do *not* cite it for NPL)
     - `edpsoccer.com` — EDP
   - ⚠️ **NPL is sunsetting.** Per US Club Soccer's announcement dated **2026-07-14**, the 2026
     season was NPL's **final** one; it is replaced for 2026-27 by the **National 1 League**,
     described there as "the top team-based competition in US Club Soccer and US Youth Soccer."
     Source: https://usclubsoccer.org/2026-npl-finals-crowns-champions-capping-final-season-as-transition-begins-to-national-1-league/
     Every NPL claim must carry explicit **current-vs-historical framing** — a page written as if
     NPL continues unchanged will be wrong within months of publishing.
   - Facts to source per league: full name and what the acronym stands for; governing body/operator;
     age groups served; how teams gain entry (application, invitation, promotion); national
     structure (conferences/regions); and postseason/national-championship pathway.
   - Build a source table (league → claim → URL → date accessed) and **write it to
     `.turbo/seo/league-comparison-sources.md`** as a real file in the worktree. The Verification
     fabrication spot-check depends on this table surviving — if it exists only in an implementer's
     working context it evaporates between sessions and that gate cannot run. Keeping it in the repo
     also makes the pages auditable later, when league facts change (as NPL's just did).

   - 🚨 **`.turbo/` IS GITIGNORED — every artifact this plan writes there must be force-added.**
     Applies to `.turbo/seo/league-comparison-sources.md` (this step),
     `.turbo/seo/league-comparison-firstparty.json` (Step 3), and the Appendix B monitoring files.
     Verified at the baseline:
     ```
     $ git check-ignore -v .turbo/seo/test.md
     "C:\Users\Dallas Heidt/.config/git/ignore":2:.turbo/    .turbo/seo/test.md     # exit 0
     ```
     The rule lives in the **global** excludes file, not the repo's `.gitignore`, so it is invisible
     to anyone reading the repo. The 46 already-tracked files under `.turbo/geo/` do **not** make new
     siblings visible — a tracked file stays tracked once added, but that grants nothing to its
     neighbours (`git status --ignored` shows other `.turbo/` files as `!!`). Without a force-add,
     `/finalize` silently skips these files, they never reach the PR, and the Verification
     fabrication spot-check has nothing to read.
     ```bash
     cd C:/pitchrank-league-pages && \
     git add -f .turbo/seo/league-comparison-sources.md && \
     git ls-files --error-unmatch .turbo/seo/league-comparison-sources.md
     ```
     `git ls-files --error-unmatch` is the confirmation — it exits non-zero if the path is still
     untracked, so a silently-dropped artifact fails loudly instead of vanishing. Do the same for the
     Step 3 JSON. *(Force-adding stages the file; that is unavoidable, since there is no other way to
     make an ignored path visible to `/finalize`. Keep it scoped to these exact artifact paths — do
     not `git add -f .turbo/`.)*
   - **Hard rule:** if a claim cannot be traced to a fetched URL, reframe it or drop it. Do not write
     "experts say", "many clubs", "generally considered", or any unsourced directional claim.
   - **Do not target `npsl`** (1,095 imp, 0 clicks). NPSL is the National Premier Soccer League, an
     **adult amateur** league — and note it is a *different entity* from NPL. The intent is
     unsatisfiable for a youth site.

3. **Pull the first-party ranking figures (reproducibly)**

   Two figures are needed: (A) the sitewide count of teams rated, and (B) the league mix among
   top-ranked teams at one representative age group. **Both queries are given below — run them, do
   not design them.**

   - **Credentials.** Both queries need `DATABASE_URL`, which `scripts/blog_research.py:25` loads
     via `load_dotenv` from the **repo-root** `C:/PitchRank/.env`. That file is gitignored and
     therefore **absent from the worktree** (Step 1 copies only `frontend/.env.local`, a different
     file with different keys). Either run from `C:/PitchRank` — safe, since both queries are
     read-only `SELECT`s and touch no working-tree files — or copy the env file across first:
     ```bash
     cp C:/PitchRank/.env C:/pitchrank-league-pages/.env
     ```
     The Supabase MCP server is an equally acceptable alternative if it is connected; if you use it,
     record that in the artifact instead of the psql/psycopg invocation.

   - **(A) Sitewide teams rated — must match the homepage counter.** Use the *homepage-cache*
     definition, not a bare `COUNT(*) FROM teams`. `scripts/blog_research.py` counts every row in
     `teams` including deprecated and unranked ones, which gives a materially larger and wrong
     answer. Verified definition (`supabase/migrations/20260615200000_homepage_stats_cache.sql:47-52`):
     ```sql
     SELECT COUNT(*)
       FROM public.rankings_full rf
       JOIN public.teams t ON t.team_id_master = rf.team_id
      WHERE rf.status = 'Active'
        AND t.is_deprecated IS NOT TRUE
        AND rf.power_score_final IS NOT NULL;
     ```
     **Round DOWN** to the nearest 1,000 for prose. `frontend/lib/stats.ts:13` sets
     `FALLBACK_STATS = { totalTeams: 59000, … }` with the comment "Kept at or below the true live
     counts so marketing copy never overstates" — respect that same discipline. If the live count is
     below the fallback, use the live count; never publish a number above it.

     **Also run the cache cross-check**, and record both numbers:
     ```sql
     -- the value the homepage actually serves
     SELECT total_teams, refreshed_at FROM public.homepage_stats WHERE id = TRUE;
     ```
     The recompute above and this cached row can legitimately differ: the cache refreshes once daily
     (`supabase/migrations/20260615200001_schedule_homepage_stats_refresh.sql` →
     `cron.schedule('refresh-homepage-stats', '13 8 * * *', …)`, i.e. 08:13 UTC), so the recompute is
     the *fresher* of the two by up to 24h. **If they round to different thousands, publish the
     lower.** Record both values and `refreshed_at` in the artifact.
     *(Why recompute at all rather than just reading the cache: the cache is the staler number, and
     `get_db_stats()` returns zero rows if the singleton row is ever missing — silent to a psql
     caller, though `frontend/lib/stats.ts` masks it with `FALLBACK_STATS`. Round-down plus the
     59,000 ceiling already guarantees prose cannot overstate the counter, so the fresher source is
     the safer default.)*

   - **(B) League mix at one age group.** Pick **one** age group and gender and **state both on the
     page** (e.g. "the top 50 U15 boys teams"). The two-stage form below is **mandatory, not a
     client preference** — the inner query picks the top-50 *rows*, the outer one groups them:
     ```sql
     SELECT league_group, COUNT(*) AS n
     FROM (
       SELECT COALESCE(
                CASE WHEN t.league IN ('MLS_NEXT_HD','MLS_NEXT_AD') THEN 'MLS_NEXT' ELSE t.league END,
                'UNAFFILIATED') AS league_group
         FROM public.rankings_full rf
         JOIN public.teams t ON t.team_id_master = rf.team_id
        WHERE rf.status = 'Active'
          AND t.is_deprecated IS NOT TRUE
          AND rf.power_score_final IS NOT NULL
          AND rf.age_group = 'u15'      -- lowercase; see gotcha below
          AND rf.gender = 'Male'        -- title-case; see gotcha below
        ORDER BY rf.power_score_final DESC, rf.team_id
        LIMIT 50
     ) top50
     GROUP BY league_group
     ORDER BY n DESC;
     ```
     A single-level query mixing `COUNT(*)` with an ungrouped column and
     `ORDER BY rf.power_score_final` is rejected by Postgres with SQLSTATE `42803`
     (`GroupingError`), and hoisting `LIMIT 50` to the outer query would limit *league buckets*
     instead of teams. The `, rf.team_id` tiebreak makes the top-50 cut deterministic when scores tie.
     - **Sanity gate: the returned `n` values must sum to exactly 50.** A sum of 0 means you hit one
       of the two case gotchas below — it is not a coverage problem, and it must not be mistaken for
       one (see the fallback rule, which zero rows would never legitimately trigger).
     - ⚠️ **`age_group` is lowercase but `gender` is title-case.** `age_group` is `'u15'`, never
       `'U15'`; `gender` is `'Male'`/`'Female'`, never `'boys'`. Neither column has a CHECK
       constraint, so the wrong case silently returns **zero rows** rather than erroring. Verified:
       `src/rankings/data_adapter.py` normalizes on write with `.str.title()`, mapping `Boys`→`Male`
       and `Girls`→`Female`, and `docs/SQL_QUERIES_FOR_RANKINGS.md` uses `gender = 'Male'` at every
       filter site.
     - ⚠️ **`MLS_NEXT_HD` and `MLS_NEXT_AD` are separate codes** and must be merged into one
       "MLS NEXT" bucket, or MLS NEXT's share is understated by roughly half. Verified league
       vocabulary (`supabase/migrations/20260402000000_add_league_column.sql:7`):
       `ECNL, ECNL_RL, MLS_NEXT_HD, MLS_NEXT_AD, GA, DPL, NPL, EA, NL, ASPIRE`; **`NULL` =
       unaffiliated** and must be counted as its own bucket, never dropped.
     - **Coverage fallback:** if `UNAFFILIATED` exceeds ~30% of the 50, `league` coverage is too
       sparse at that cohort to support a "roughly half" claim. Either try another age group, or
       drop figure (B) entirely and write the pages without it. **Do not** compute the share over
       only the rows that have a league — that silently inflates every league's percentage.

   - **Save the queries and their raw results to `.turbo/seo/league-comparison-firstparty.json`**,
     then **force-add it** exactly as Step 2 describes (`git add -f` + `git ls-files
     --error-unmatch`) — `.turbo/` is gitignored and `/finalize` will otherwise skip it silently.
     Record, per figure: the SQL as run, the
     age group and gender, the raw counts, the rounding applied, the data source
     (`DATABASE_URL` vs Supabase MCP), and the date accessed. The Verification fabrication
     spot-check reads this file — a figure in prose that is not in this file is unsourced.

   - Phrase figures so they do not go stale weekly: "roughly half of the top 50", not "exactly 27 of
     the top 50 as of July 21". Rankings republish every Monday.

4. **Author `frontend/content/blog/ecnl-vs-mls-next.mdx`**
   - Frontmatter mirroring `ohio-youth-soccer-rankings-guide.mdx`: `title`, `slug: 'ecnl-vs-mls-next'`
     (must equal the filename), `excerpt` (132–160 chars), `author: 'PitchRank Team'`,
     `date` and `modifiedDate` (full contract immediately below), `readingTime`, `tags`.
     Omit `keywords` — `parseMarkdownFile` ignores it.

   - **THE DATE CONTRACT (authoritative — Steps 5, 7 and Appendix A reference this, not vice versa).**
     - **At authoring time, use TODAY's UTC date.** The merge day is unknowable while the PR is being
       written and reviewed, so do not try to guess it. Appendix A refreshes the *date* immediately
       before merge; the *hours* never change.
     - **Assign one distinct hour per post, quoted:**
       | File | `date` and `modifiedDate` |
       |---|---|
       | `ecnl-vs-mls-next.mdx` | `'<YYYY-MM-DD>T09:00:00Z'` |
       | `ecnl-vs-npl.mdx` | `'<YYYY-MM-DD>T10:00:00Z'` |
       | `what-is-ecnl.mdx` | `'<YYYY-MM-DD>T11:00:00Z'` |
       Set each post's `modifiedDate` **equal to its own `date`** (satisfies `frontend/CLAUDE.md:288`).
     - **All three share ONE day.** Do not use three consecutive days — all three ship in one PR on
       one day, so future-dating two of them would be factually wrong and flows into `datePublished`
       and OG `publishedTime` (`frontend/app/blog/[slug]/page.tsx:52`).
     - **The quotes are load-bearing.** Unquoted YAML coerces a timestamp to a JS `Date`, and
       `frontend/lib/blog.tsx:34` does `String(data.date)` — yielding
       `"Fri Jul 24 2026 09:00:00 GMT+0000 (…)"`, which would poison `<time dateTime>` and schema
       `datePublished`. Quoted, it stays a clean ISO string.
     - **Why distinct hours — ordering, NOT timezones.** `frontend/lib/blog.tsx:65` sorts by date
       **only**, and `:54` reads the directory with `fs.readdirSync` (**unsorted**). Identical
       timestamps fall back to filesystem order — alphabetical on Windows/NTFS, hash order on the
       Ubuntu CI runner's ext4 — so local output could disagree with CI and fail the `llms.txt` drift
       check. Distinct hours make the comparator non-zero for every pair, so `readdirSync` order is
       never consulted.
       - ⚠️ An earlier draft justified this with a *viewer-timezone* argument (that `T00:00:00Z`
         renders as the previous day in ET/PT). **That reasoning was wrong and has been removed:**
         neither `frontend/app/blog/[slug]/page.tsx` nor `frontend/components/BlogCard.tsx` carries
         `'use client'`, so both `toLocaleDateString` calls run in **Server Components** at
         render/prerender time in the server's timezone, never in the viewer's browser. `T00:00:00Z`
         would render fine. Use `T09/10/11:00:00Z` for the ordering reason alone, and note the
         deviation from `frontend/CLAUDE.md:287` in the PR description (see Convention Anchors).
     - **Distinctness scope.** The three timestamps must differ from each other and from every
       existing **non-pillar** markdown post's date. Colliding with a **state pillar's** date is
       harmless — pillars render from `STATE_PILLAR_SLUGS` via `renderStatePillars()`, independent of
       post order; only the `## Blog` section is order-sensitive, and `renderBlog()` receives
       non-pillar posts. Colliding with a **TSX** post's date is also harmless — `getAllBlogPosts()`
       builds `[...tsx, ...md]` before a stable `Array.sort`, so a TSX entry always wins a cross-path
       tie deterministically. *(One such cross-path collision already exists —
       `state-of-texas-youth-soccer-2026` (TSX) and `2026-06-22-connecticut-youth-soccer-rankings`
       (MDX) both carry `2026-06-22` — and it is stable for exactly that reason.)*
       - ⚠️ **Do NOT expect markdown post dates to be globally unique.** An earlier draft claimed
         "no two markdown posts currently share a date"; that is **false**. Verified at the baseline,
         nine date groups collide under `frontend/content/blog/`: `2026-04-08` (colorado, michigan),
         `2026-04-11` (new-jersey, north-carolina), `2026-04-15` (pa-u10-boys, pennsylvania),
         `2026-04-28` (maryland, new-york, virginia), `2026-04-29` (georgia,
         youth-soccer-levels-explained), `2026-04-30` (illinois, ohio), `2026-05-11` (massachusetts,
         washington), `2026-05-16` (connecticut, minnesota), `2026-06-24` (indiana, missouri). Every
         one of those pairs is pillar-vs-pillar or pillar-vs-non-pillar, which is why `llms.txt` is
         stable today. The invariant that actually holds — and the only one you must preserve — is
         **distinctness among non-pillar posts**.
       - **Do NOT "fix" this by adding a sort tiebreak to `getAllBlogPosts()`.** That function has
         five consumers, two of them user/crawler-facing (the `/blog` index at
         `frontend/app/blog/page.tsx:41` and `frontend/app/sitemap.ts:61`) — changing it would
         reshuffle the live blog index and `sitemap.xml`, which is not additive. *(The missing
         tiebreak is a real but separate non-blocking cleanup; note it for the backlog rather than
         doing it here.)*
   - **Target length ~1,800–2,500 words**, in line with the protected page (~2,190) and below the
     state pillars (~3,200). Set `readingTime` from the *finished* draft: actual word count ÷ 200,
     rounded — `frontend/components/BlogPostSchema.tsx` derives JSON-LD `wordCount` as
     `parseInt(readingTime) * 200`, so a declared `'11 min read'` on a 1,200-word page publishes a
     false `wordCount` of 2,200.
   - **No `#` H1 in the body** (decision 2) — `PageHeader` already renders one. Start at `##`.
   - Open with a 40–60 word factual structural answer before the first `##`: which body operates
     each platform, what tier each occupies, and the single clearest practical difference. Neutral —
     no "better", no recommendation.
   - Include a GFM comparison table (operator, age groups, entry route, national structure,
     postseason) — comparison data in tables is required for extraction.
   - Target these queries in `##`/`###` headings phrased as questions: `difference between ecnl and
     mls next`, `is ecnl higher than mls next`, `mls next vs ecnl vs npl`, `what is after mls next`.
     **Do not target the bare head terms `mls next` or `ecnl soccer`** (decision 6 — protected).
   - **HEADINGS vs REGISTERED FAQs — these are different things, and Step 6 only constrains the
     second.** A target query may appear as a body `##`/`###` heading anywhere on the page,
     *including* as an unregistered `###` inside the `## Frequently Asked Questions` section. What
     Step 6 forbids is **registering** that question as a `BLOG_FAQS` entry. So
     `### What's the difference between ECNL and ECNL RL?` is a perfectly good on-page heading;
     it just must not also appear in `frontend/lib/blog-faqs.ts`. Step 6's parity test is written to
     tolerate unregistered `###` blocks in the FAQ section for exactly this reason.
   - Paragraphs 2–4 sentences. Cite source URLs inline. Include one first-party data paragraph from
     Step 3 and one blockquote CTA into `/rankings`.
   - **Format the file before committing:** run `npx prettier --write` on **this file only**.
     Prettier normalizes GFM table padding and separator rows (to `| ------ |`), and
     `frontend/.prettierignore` covers only `content/reports/`, so `content/blog/*.mdx` **is**
     format-checked by CI. **Never run `npm run format` / `prettier --write .`** — that rewrites
     every file under `frontend/`, including the protected page.
   - End with `## Frequently Asked Questions` (`###` per question) → `---` → bold **About PitchRank:**
     footer, matching the Ohio pillar's closing pattern.

5. **Author `frontend/content/blog/ecnl-vs-npl.mdx` and `frontend/content/blog/what-is-ecnl.mdx`**
   - Same structure, frontmatter contract, and rules as Step 4 — including **the date contract in
     Step 4** (`T10:00:00Z` for `ecnl-vs-npl`, `T11:00:00Z` for `what-is-ecnl`) and the per-file
     `npx prettier --write`.
   - **`ecnl-vs-npl` — keep the slug, but cover the NPL → National 1 League transition explicitly.**
     This page must serve both the existing NPL demand and the emerging National 1 League demand:
     - Existing NPL queries: `is npl or ecnl better` (678 imp — the single largest in the cluster),
       `npl vs ecnl`, `is ecnl rl better than npl`, `is npl better than ecnl rl`, `npl vs mls next`,
       `where does npl rank in youth soccer`, `what does npl stand for in soccer`.
     - Transition queries almost nobody has content for: `national 1 league vs ecnl` (167 imp),
       `is n1 better than ecnl rl` (34 imp), `n1 soccer league vs ecnl` (32 imp).
     - USYS queries: `is usys better than ecnl`, `usys national league vs ecnl`.
     - Required framing: NPL is run by **US Club Soccer**; 2026 was its **final season**; the
       **National 1 League** replaces it for 2026-27 as a joint US Club Soccer / US Youth Soccer
       platform. State clearly what is current versus historical so the page does not read as stale
       once the transition completes.
     - Must clearly distinguish **ECNL Regional League (ECNL RL)** from **ECNL** — several queries
       conflate them.
   - `what-is-ecnl` targets **definitional long-tail only**: `what does ecnl stand for`,
     `ecnl meaning`, `ecnl levels`, `ecnl tiers`, `difference between ecnl and ecnl rl`,
     `is ecnl the highest level of soccer`. Lead with the expansion of the acronym in the first
     sentence. **Do NOT target the bare head term `ecnl soccer`** — it is a live #2.4 ranking held
     by the protected page (decision 6). Likewise avoid `ecnl rl` and `edp soccer` as targets.
   - **Required internal links — every one of these is asserted in Verification, so none is optional:**
     - Each of the three new pages links to **both** of the other two, using absolute site-relative
       hrefs with the `/blog/` prefix: `/blog/ecnl-vs-mls-next`, `/blog/ecnl-vs-npl`,
       `/blog/what-is-ecnl`. A bare `(ecnl-vs-npl)` href resolves relative to the current URL and
       404s — the automated check in Verification exists to catch exactly that.
     - Each of the three links at least once to `/rankings`.

   - **One inbound link from a non-protected post — `frontend/content/blog/youth-soccer-tryouts-2026.mdx`.**
     Add a single contextual link to `/blog/ecnl-vs-mls-next` from that post, and bump its
     `modifiedDate` per `frontend/CLAUDE.md:284-289`. **This is the only file outside the three new
     pages, `blog-faqs.ts`, and `llms.txt` that this plan edits — and it is emphatically NOT the
     protected page.**
     - *Why this specific post:* it already competes for the intent. Verified at the baseline, it
       carries a visible `### Is ECNL or MLS NEXT better for my child?` FAQ at
       `frontend/content/blog/youth-soccer-tryouts-2026.mdx:199`, **and** a registered schema FAQ
       `'What is the difference between ECNL and MLS NEXT?'` at `frontend/lib/blog-faqs.ts:1023`.
       Linking from that answer to the dedicated page is the standard way to resolve a
       duplicate-intent overlap: it tells Google which URL should own the comparison.
     - *Why not the protected page:* unchanged — see the hard-constraint paragraph in Context. The
       tryouts post holds no top-3 rankings, so it carries none of that risk.
     - Do **not** restructure or reword that post's existing FAQ, and do **not** touch its
       `blog-faqs.ts` entry — add the link and bump `modifiedDate`, nothing else. The `blog-faqs.ts`
       guard in Verification will fail if its registered entry is edited.
     - *Note the discovery argument is NOT the justification here.* The three pages are not orphans:
       they cross-link to each other and appear in the `/blog` index, `sitemap.xml`, and `llms.txt` —
       the same entry path every other markdown post has, including the protected page now holding
       #2.4. This link is about intent consolidation, not crawlability.

6. **Register FAQs and add a parity test**
   - Add **three new** `BLOG_FAQS` entries keyed by the new slugs in `frontend/lib/blog-faqs.ts`,
     following the existing `Record<string, FAQ[]>` shape. Each `question` **and** `answer` must
     appear verbatim in the corresponding `.mdx` body — Google requires schema FAQ content be
     visible on the page.
   - ⚠️ **Do not modify any existing entry in this file.** It also holds
     `BLOG_FAQS['youth-soccer-levels-explained']` at `frontend/lib/blog-faqs.ts:958` — the 8 entries
     feeding the protected page's `FAQPage` JSON-LD. That entry has known question/answer
     drift against its rendered body (e.g. registry "two parallel sanctioning structures" vs body
     "two parallel structures"; "What is the difference…" vs "What's the difference…").
     **Leave it exactly as-is.** Fixing it is a separate, out-of-scope change — touching it here
     would silently rewrite the emitted JSON-LD on the page this plan exists to protect. (That
     JSON-LD no longer earns a rich result — see Pattern Survey (3) — but it is still parsed by
     Google for page understanding and by LLM answer engines, and check (3) of the `blog-faqs.ts`
     guard in Verification fails the build if it changes at all.)
   - ⚠️ **Differentiate the new FAQs from every question already registered anywhere in
     `BLOG_FAQS` — this is a hard-constraint issue, not a style note.** Existing registered
     questions that overlap the new pages, verified at the baseline:
     | Existing registered question | Registered under | Overlaps |
     |---|---|---|
     | "Is ECNL or MLS NEXT higher level?" | `youth-soccer-levels-explained` (`blog-faqs.ts:958`) | `/blog/ecnl-vs-mls-next` |
     | "What is the difference between ECNL and ECNL Regional League?" | `youth-soccer-levels-explained` | `/blog/what-is-ecnl` |
     | "What is NPL in soccer?" | `youth-soccer-levels-explained` | `/blog/ecnl-vs-npl` |
     | "What is the difference between ECNL and MLS NEXT?" | **`youth-soccer-tryouts-2026`** (`blog-faqs.ts:1023`) | `/blog/ecnl-vs-mls-next` |
     The fourth row is the one an earlier draft missed: it sits on a **different** page under a
     **different** slug, and it is almost verbatim the head question `/blog/ecnl-vs-mls-next` is
     being built to own. Scoping the duplicate check to the protected page alone would sail straight
     past it — hence assertion (d) below covers **all** registered slugs, not just one.
     **Do not reuse or lightly reword any of these four questions.** Give each new page FAQs that
     address a *distinct sub-question* its own content uniquely answers (e.g. entry routes,
     age-group coverage, postseason pathway, the National 1 League transition) rather than the head
     comparison.
     - **Why this matters — the correct reason, which is NOT rich results.** An earlier draft
       justified this rule as avoiding "competing FAQPage entities on competing canonical URLs".
       That rationale is void: Google stopped showing FAQ rich results on **2026-05-07** and removed
       the documentation on **2026-06-15** (see Pattern Survey (3)), so there is no rich result to
       compete for and no page on this site has one. The rule survives on two other grounds, both
       still fully in force: (i) **content duplication** — near-identical Q&A blocks across
       canonical URLs is a classic same-site cannibalization signal regardless of markup, and the
       protected page's live top-3 positions are what this plan exists to defend; and (ii) **AI
       extraction** — FAQ markup is still parsed for page understanding and is a primary surface for
       LLM answer engines, which is an explicit goal of this plan (ChatGPT referrals up 39% MoM).
       Keep the differentiation rule and the parity test; just do not describe either as protecting
       a rich result.
   - Add `frontend/lib/blog-faqs.test.ts` (new file, vitest) asserting, **for the three new slugs
     only**:
     (a) the slug has a `BLOG_FAQS` entry;
     (b) `frontend/content/blog/<slug>.mdx` exists;
     (c) **each registered question→answer PAIR appears as a pair** — the registered `answer` must
     occur in the MDX *within the FAQ section, immediately following its own registered `question`*.
     Do **not** merely assert that each question string and each answer string appears somewhere in
     the file: swapping the answers between two questions would still pass that weaker test, while
     `frontend/components/BlogFAQSchema.tsx` would emit each question with the wrong
     `acceptedAnswer`. Parse the `## Frequently Asked Questions` section into `###` question blocks
     and compare pairwise.
     **Direction matters: assert registered → rendered, not rendered → registered.** Every
     *registered* FAQ must have a matching `###` block, but the FAQ section may contain **additional
     unregistered `###` blocks** — that is expected and legal (see the headings-vs-registered-FAQs
     rule in Step 4, which lets a target query be an on-page heading without being registered). A
     test that requires every `###` block to be registered would forbid that and contradict Step 4;
     (d) **no new question duplicates any question registered under ANY key in `BLOG_FAQS`**
     (case- and punctuation-insensitive), excluding the three new slugs themselves — this is the
     automated form of the differentiation rule above. Build the forbidden set by iterating
     `Object.entries(BLOG_FAQS)` and skipping the three new keys; **do not hardcode a single slug**.
     Scoping this to `youth-soccer-levels-explained` alone would miss
     `'What is the difference between ECNL and MLS NEXT?'` under `youth-soccer-tryouts-2026`
     (`blog-faqs.ts:1023`), which is the closest existing question to the head intent of
     `/blog/ecnl-vs-mls-next`.
   - **Normalize before comparing**, or the test will fail on correctly-rendered pages: strip the
     frontmatter block; normalize curly vs straight apostrophes (`'` ↔ `’`, since existing FAQ data
     mixes both); strip markdown links (`\[([^\]]+)\]\([^)]+\)` → `$1`); and strip bold markers
     (`**`). Without the last two, any FAQ answer containing an inline citation or a bold span — both
     of which Step 4 and house style encourage — fails the pairwise assertion with an opaque
     "answer not found after its question" error despite the page being correct.
   - Also keep FAQ answers to **single plain-text paragraphs**, placing source citations elsewhere in
     the body. That keeps the registered string and the rendered string trivially comparable.
   - **Assertion (d) needs an explicit variant list on top of the all-slugs sweep**, not just
     exact-match. Case- and punctuation-normalized equality would still pass
     `"Which is higher, ECNL or MLS NEXT?"` against the protected page's
     `"Is ECNL or MLS NEXT higher level?"` — same intent, different string. Fail the test if a new
     **registered** question normalizes to any of these forbidden variants:
     - *ECNL vs MLS NEXT:* "is ecnl or mls next higher level", "which is higher ecnl or mls next",
       "which is better ecnl or mls next", "is mls next higher than ecnl",
       "is ecnl higher than mls next", "what is the difference between ecnl and mls next",
       "difference between ecnl and mls next", "is ecnl or mls next better for my child"
     - *ECNL vs ECNL RL:* "what is the difference between ecnl and ecnl regional league",
       "difference between ecnl and ecnl rl", "ecnl vs ecnl rl", "is ecnl rl the same as ecnl"
     - *NPL:* "what is npl in soccer", "what does npl stand for",
       "what does npl stand for in soccer", "what is the npl"

     ⚠️ The third NPL entry is not redundant. Step 5 directs `ecnl-vs-npl` to target the query
     `what does npl stand for in soccer`; under the plan's own case-and-punctuation normalization
     that string equals **neither** `what does npl stand for` **nor** the protected page's
     `what is npl in soccer`, so without it the prohibited question passes assertion (d). Prefer a
     prefix predicate (fail any registered question normalizing to `what does npl stand for…`) over
     chasing individual suffixes.

     The two new MLS-NEXT variants come from real registered/rendered strings at the baseline —
     `blog-faqs.ts:1023` and `youth-soccer-tryouts-2026.mdx:199` respectively — not from
     speculation.

     ⚠️ **This list constrains REGISTERED questions only.** Per Step 4, the same string is still
     allowed as an unregistered `###` heading on the page. Step 5 explicitly directs `what-is-ecnl`
     to target `difference between ecnl and ecnl rl` and `ecnl-vs-npl` to target
     `what does npl stand for in soccer`; those pages should absolutely answer those questions in
     their bodies — they just must not register them in `BLOG_FAQS`. Without this distinction the
     two steps contradict each other and the implementer trips their own test.

     This is a **backstop, not a substitute** for the human differentiation judgment above — a
     determined rewording will still slip past it, so the author must actually pick distinct
     sub-questions.
   - **Scope, precisely — assertions (a)-(c) and (d) differ and this distinction is load-bearing:**
     - **(a)-(c) parity: the three new slugs ONLY.** Do **not** assert question↔answer parity across
       the 32 existing slugs — `origin/main` already has known drift (e.g. the protected page's
       registry says "two parallel sanctioning structures" where its body says "two parallel
       structures"), and failing on that would be an unrelated, out-of-scope breakage.
     - **(d) duplication: READS all slugs, ASSERTS only on the new ones.** It iterates every
       registered question in `BLOG_FAQS` to build the forbidden set, then checks only the three new
       slugs' questions against it. Existing-vs-existing duplicates are not the new test's business
       and must not fail it.

7. **Regenerate `llms.txt`**
   - Confirm all three posts carry their dates per **the date contract in Step 4** before generating
     — the generator's `## Blog` ordering depends on it.
   - From the worktree's `frontend/`: `npm run generate-llms`. Leave the regenerated
     `frontend/public/llms.txt` in the working tree; `/finalize` stages it.
   - This is **mandatory** — CI job `frontend-llms-drift` (`.github/workflows/ci.yml:97-114`) runs
     `git diff --exit-code public/llms.txt` and fails the build otherwise. The local auto-regen hook
     does not exist inside the worktree.
   - Confirm the three new posts appear under `## Blog`.

## Verification

Run **from `C:/pitchrank-league-pages/frontend`** (the worktree) — never from the main checkout,
for the reasons in Pre-flight. `npm ci` must already have been run in Step 1.

⚠️ **All `git diff` guards below must use `git -C C:/pitchrank-league-pages` (the worktree ROOT).**
Pathspecs resolve relative to the current working directory, and these commands run from
`<worktree>/frontend` — so a repo-root-relative pathspec like `-- frontend/lib/blog-faqs.ts` would
search `frontend/frontend/lib/...`, match nothing, and **exit 0 with empty output**, passing
vacuously. Empirically confirmed: that form returned 0 lines for a file with 26 real deletions.

⚠️ **Every guard recomputes the merge-base INLINE. Do not carry it in a `$BASE` shell variable.**
Each Bash tool invocation starts a **fresh shell** — a variable assigned in one command does not
exist in the next. If a guard runs with `$BASE` unset it expands to the empty string, and
`git diff --quiet $BASE -- <path>` silently degrades to `git diff --quiet -- <path>`, which compares
the *working tree against the index*. Once the implementer's work is committed that is always empty,
so **the protected-page guard — the sole mechanism enforcing this plan's hard constraint — exits 0
no matter what was changed.** The `blog-faqs.ts` guard fails open the same way (`test -z ""` is
true). This is the identical fail-open class the plan already eliminated from the pathspec form; do
not reintroduce it through a variable.

Each guard below is therefore self-contained and safe to paste individually. Sanity-check the
baseline first:

```bash
git -C C:/pitchrank-league-pages merge-base HEAD origin/main
# expected: 2aba761a3 at time of planning
```

**Do not `cd` out of `frontend/`** — the worktree root has no `package.json` (only
`frontend/package.json` exists), so the npm commands below would all fail there. Every guard uses
`git -C` instead of changing directory, and every npm command carries its own `cd` prefix.

⚠️ **ORDERING — two groups, and getting this backwards can push a constraint violation to the remote.**

Guards split by what they actually compare, which is **not** uniform:

| Guard | Compares | Run |
|---|---|---|
| Protected-page guard | `git diff <base> -- path` = base vs **working tree** | **BEFORE** `/finalize` |
| Tryouts guard | same | **BEFORE** `/finalize` |
| Changed-file allow-list | `git diff --name-only` + `ls-files --others` = **working tree** | **BEFORE** `/finalize` |
| `blog-faqs.ts` guard | `git show HEAD:…` = **committed content only** | **AFTER** the commit |
| `llms.txt` drift check | bare `git diff` = worktree vs index | **AFTER** the commit |

The first three see uncommitted and untracked changes — verified: with an unstaged edit,
`git diff --quiet <base> -- <file>` exits 1 and `ls-files --others` surfaces the new `.mdx` files.
**Run them before `/finalize` so a hard-constraint violation is caught while it is still local.**

🚨 **At `/finalize` Phase 5 → `/ship` Step 1, choose "Commit only".** `/ship` recommends
"Commit, push, and create/update the PR" for PR-based repos like this one. Taking the recommendation
pushes the branch and opens a PR *before* the two post-commit guards have run — and if the
protected-page guard then fails, recovery needs a force-push, which is blocked in this environment.
Commit only → run the `blog-faqs.ts` and `llms.txt` guards → then push and open the PR.

⚠️ **Also choose "Ship together", not "Split".** `/split-and-ship` runs `git reset` followed by
`git stash --include-untracked`, and `--include-untracked` does **not** capture ignored files (only
`--all` does). The force-added `.turbo/seo/*` artifacts would be reset back to ignored+untracked and
then lost, unrecoverable from the stash. This changeset is one cohesive unit; ship it together.

⚠️ **Re-run the npm gates after `/finalize` settles.** `/polish-code` (Phase 1) and `/simplify-docs`
(Phase 2) both modify and stage code *after* the gates below have passed, and `/polish-code` re-runs
format/lint/test but **not** typecheck or build. Re-run `npm run typecheck` and `npm run build`
against the finalized commit before pushing.

⚠️ **Each guard runs in a `( … )` subshell.** The failure branches call `exit 1`, which would
terminate an interactive Git Bash session if pasted at top level. The subshell also scopes
`set -euo pipefail`, so a failing `merge-base`, `git diff`, or `comm` aborts instead of being masked
by a downstream `sort` or a no-match `grep` and reporting success.

These four mirror the CI jobs in `.github/workflows/ci.yml`; all must pass locally before pushing:

- `npm run test` — full vitest suite green, including the new `frontend/lib/blog-faqs.test.ts`
  (job `frontend-test`, `:81`).
- `npm run lint` — clean (job `frontend-lint`, `:33`).
- `npm run format:check` — clean (job `frontend-format`, `:49`, runs `npx prettier --check .`).
  **Expect this to fail until each new `.mdx` has been through `npx prettier --write` individually**
  — Prettier reformats hand-written GFM tables (column padding and `| ------ |` separator rows), and
  `.prettierignore` covers only `content/reports/`. Fix by formatting the **new files only**, never
  `prettier --write .`.
- `npm run typecheck` — clean (job `frontend-typecheck`, `:65`).

Then:

- `npm run build` — **must exit 0, AND all three new routes must appear in the prerender manifest.**
  Concrete non-zero-exiting assertion (Next 16.2.6, no custom `distDir`, so the manifest is at
  `.next/prerender-manifest.json` and route keys live under `routes`):
  ```bash
  node -e "const m=require('./.next/prerender-manifest.json');
    const want=['/blog/ecnl-vs-mls-next','/blog/ecnl-vs-npl','/blog/what-is-ecnl'];
    const missing=want.filter(r=>!Object.keys(m.routes).includes(r));
    if(missing.length){console.error('MISSING routes:',missing);process.exit(1)}
    console.log('all 3 routes prerendered')"
  ```
  Exit code alone is not a sufficient criterion here: without `.env.local` the build emits ~200 `[ISR] Failed to fetch teams…` warnings
  and ~200 `generateMetadata` errors from the rankings routes, because `frontend/lib/api.ts:9-13`
  builds the Supabase client from `NEXT_PUBLIC_SUPABASE_URL!` / `NEXT_PUBLIC_SUPABASE_ANON_KEY!`.
  Those call sites are try/catch-guarded and every affected route sets `revalidate = 3600`, so the
  build **degrades rather than fails** — but the noise would mask a real regression.
  **Preferred fix:** copy the env file into the worktree first —
  `cp C:/PitchRank/frontend/.env.local C:/pitchrank-league-pages/frontend/.env.local` (the two
  required vars are listed at `frontend/CLAUDE.md:324-325`). If you skip that, treat Supabase
  warnings as expected noise and rely on the manifest assertion. Note the new blog routes are
  filesystem-backed and env-independent, so a genuine frontmatter/MDX error surfaces distinctly as a
  `blog/[slug]` failure, not as a Supabase warning.
- `npm run generate-llms && git -C C:/pitchrank-league-pages diff --exit-code -- frontend/public/llms.txt`
  — must exit 0 (mirrors job `frontend-llms-drift`, `:97-114`). Non-zero means the regenerated
  artifact was never written back, **or** that two **non-pillar** markdown posts share an identical
  `date` timestamp and ordering is unstable (see the date contract in Step 4). Note this guard is
  run *after* `/finalize` commits, since `git diff` compares against the index/HEAD.
- **Protected-page guard — one line, genuinely fail-closed:**
  ```bash
  git -C C:/pitchrank-league-pages diff --quiet \
    "$(git -C C:/pitchrank-league-pages merge-base HEAD origin/main)" -- \
    frontend/content/blog/youth-soccer-levels-explained.mdx
  # exit 0 = untouched (REQUIRED). Any non-zero exit = constraint violation, stop.
  ```
  The protected page must not appear in the diff **at all**. `--quiet` is what makes this fail
  closed — it exits 1 on any difference, whereas a bare `git diff` exits 0 whether or not it printed
  anything. The merge-base is substituted inline so the command cannot silently lose its baseline.
- **`blog-faqs.ts` guard — strip-and-compare, two checks.** The intended change is three brand-new
  top-level keys and **nothing else anywhere in the file**. So: delete those three key blocks from
  the committed file and assert what remains is byte-identical to baseline.
  ```bash
  ( set -euo pipefail
    W=C:/pitchrank-league-pages
    BASE_SHA="$(git -C "$W" merge-base HEAD origin/main)"
    STRIP="/^  'ecnl-vs-mls-next': \[/,/^  \],\$/d;/^  'ecnl-vs-npl': \[/,/^  \],\$/d;/^  'what-is-ecnl': \[/,/^  \],\$/d"

    # (1) Everything outside the three new keys must be untouched.
    # grep -v strips blank lines on BOTH sides: every top-level key in this file is
    # blank-line separated (verified: :957 blank, :958 key), and the sed ranges delete the
    # key blocks but leave their separators, which would otherwise diff as spurious lines
    # and fail a CORRECT implementation.
    if ! diff <(git -C "$W" show "$BASE_SHA:frontend/lib/blog-faqs.ts" | grep -v '^[[:space:]]*$') \
              <(git -C "$W" show "HEAD:frontend/lib/blog-faqs.ts" | sed "$STRIP" | grep -v '^[[:space:]]*$'); then
      echo 'VIOLATION: blog-faqs.ts differs from baseline outside the three new keys'; exit 1
    fi

    # (2) All three new keys must actually exist (strip-and-compare passes vacuously otherwise).
    for s in ecnl-vs-mls-next ecnl-vs-npl what-is-ecnl; do
      git -C "$W" show "HEAD:frontend/lib/blog-faqs.ts" | grep -q "^  '$s': \[$" \
        || { echo "MISSING new FAQ key: $s"; exit 1; }
    done
    echo 'blog-faqs.ts OK'
  )
  ```
  **Why this shape rather than a deletions-only check plus a per-key extraction:**
  - A deletions-only check (`git diff | grep '^-'`) **cannot see an additive bypass.** Appending a
    question inside `BLOG_FAQS['youth-soccer-levels-explained']` removes no lines, yet that array is
    rendered directly by `frontend/app/blog/[slug]/page.tsx:101` — so the protected page's JSON-LD
    changes **without its `.mdx` ever entering the diff**, invisible to the protected-page guard
    above. Verified by reproduction: with such a line inserted, a deletions-only check reports
    "removed-line count: 0" and passes.
  - Extracting and comparing each existing key by name would **miss one entry entirely**:
    `frontend/lib/blog-faqs.ts:714` is `[texasReport.slug]: [`, a **computed** key. Verified counts
    at the baseline: 32 quoted-string keys, **1 computed key**, 33 `^  ],$` closers. Strip-and-compare
    is key-agnostic and therefore covers it — along with the imports, the `FAQ` interface, and the
    section-header comments, none of which a per-key sweep would guard.
  - It **fails closed.** If a `sed` anchor ever stops matching, the new block survives the strip and
    shows up as a diff — a loud failure, not the silent empty-vs-empty pass a `test -s` backstop was
    (incorrectly) meant to catch. *(Do not reintroduce `test -s <(…)`: process substitution yields a
    pipe whose `st_size` is always 0, so `test -s` is false even for non-empty output — verified in
    Git Bash 5.2.37. It would fire `VIOLATION` on every correct run.)*
  - No added false-positive risk: `blog-faqs.ts` is Prettier-managed via lint-staged
    (`*.{ts,tsx,js,jsx}`), but any reformat of an existing line is a removal+addition, which the old
    deletions-only check already failed on. `.prettierrc` sets `trailingComma: "es5"` and the file's
    last entry already ends `  ],` before `};`, so appending at the end rewrites no existing line.

  ⚠️ **Authoring constraint this guard imposes (Step 6 must honour it):** append the three keys as
  one contiguous block with **no new section-header comment or banner** around them. The file
  already contains such banners (e.g. `/* ─── State Data Reports ─── */` above `:714`), and one
  added outside the three `sed` ranges would survive the strip and fail check (1). If a banner is
  genuinely wanted, widen the `sed` ranges to include it.
- **`youth-soccer-tryouts-2026.mdx` guard — the ONE permitted edit outside the new files.** Step 5
  adds a single link plus a `modifiedDate` bump. Confirm the diff is that small and nothing else:
  ```bash
  git -C C:/pitchrank-league-pages diff --stat \
    "$(git -C C:/pitchrank-league-pages merge-base HEAD origin/main)" -- \
    frontend/content/blog/youth-soccer-tryouts-2026.mdx
  # expect a handful of changed lines, not a rewrite. Read the diff; confirm the existing
  # '### Is ECNL or MLS NEXT better for my child?' answer is intact apart from the added link.
  ```
- **Changed-file allow-list — nothing outside this set may appear:**
  ```bash
  ( set -euo pipefail
    W=C:/pitchrank-league-pages
    # mktemp, NOT "$W/../actual.txt" — that resolves to C:/actual.txt, and the drive root is
    # not writable by an ordinary user here. The redirect fails, set -e does NOT abort on it,
    # comm then errors, UNEXPECTED ends up empty, and the guard prints 'file set OK' having
    # checked nothing. Verified fail-open.
    T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
    BASE_SHA="$(git -C "$W" merge-base HEAD origin/main)"

    # Tracked changes UNION still-untracked files. git diff --name-only alone omits untracked
    # paths entirely — verified — which would hide the three new .mdx files and the new test file.
    { git -C "$W" diff --name-only "$BASE_SHA"
      git -C "$W" ls-files --others --exclude-standard
    } | sort -u > "$T/actual.txt"

    printf '%s\n' \
      .turbo/seo/league-comparison-firstparty.json \
      .turbo/seo/league-comparison-sources.md \
      frontend/content/blog/ecnl-vs-mls-next.mdx \
      frontend/content/blog/ecnl-vs-npl.mdx \
      frontend/content/blog/what-is-ecnl.mdx \
      frontend/content/blog/youth-soccer-tryouts-2026.mdx \
      frontend/lib/blog-faqs.test.ts \
      frontend/lib/blog-faqs.ts \
      frontend/public/llms.txt \
    | sort > "$T/allowed.txt"

    UNEXPECTED="$(comm -23 "$T/actual.txt" "$T/allowed.txt")"
    if [ -n "$UNEXPECTED" ]; then
      echo 'VIOLATION: unexpected file(s):'; echo "$UNEXPECTED"; exit 1
    fi
    echo 'file set OK'
  )
  ```
  ⚠️ **`printf`, not a heredoc — this is not a style choice.** The earlier draft used
  `cat <<'EOF' … EOF` indented two spaces to sit inside this bullet. `<<'EOF'` requires its
  terminator at **column 0**, so bash emits `warning: here-document at line N delimited by
  end-of-file`, then swallows `EOF`, the `comm` line, **and the violation branch** into the file —
  the guard never runs and the block exits 0 silently. Verified by execution. Dedenting only the
  terminator does not fix it either: the space-indented body lines then make `comm -23` flag every
  legitimate path as a violation. `<<-'EOF'` is no help — it strips leading **tabs**, not spaces.
  `printf '%s\n'` is immune to surrounding indentation, so the block survives copy-paste from either
  the raw file or a rendered view.
  - Add `.turbo/seo/league-pages-baseline-<date>.json` to the allowed list if the Appendix B baseline
    is captured on this branch (see Appendix B step 1) rather than in the follow-up PR.
  - Note both `.turbo/seo/*` entries appear here only because Step 2/Step 3 force-add them;
    `.turbo/` is gitignored, so `ls-files --others --exclude-standard` would not surface them.
- Manual smoke (`npm run dev`): load `/blog/ecnl-vs-mls-next`, `/blog/ecnl-vs-npl`, `/blog/what-is-ecnl`.
  Confirm each renders, the GFM comparison table is styled, and **exactly one `<h1>`** is present
  (`document.querySelectorAll('h1').length === 1`).
- View source on each new page: `BlogPosting`, `BreadcrumbList`, and `FAQPage` JSON-LD all present;
  `datePublished` and `dateModified` carry that post's **distinct-hour** timestamp
  (`T09:00:00Z` / `T10:00:00Z` / `T11:00:00Z`) per the date contract in Step 4.
  `frontend/components/BlogPostSchema.tsx:46-47` passes both values straight through without
  normalizing, so whatever is in the frontmatter is what ships.
- **Validate the JSON-LD at `https://validator.schema.org`** — paste each new page's rendered source;
  `BlogPosting`, `BreadcrumbList`, and `FAQPage` must all parse with no errors.
  ⚠️ **Do NOT use `search.google.com/test/rich-results` to assert "FAQPage eligible".** That
  assertion is unsatisfiable: Google removed FAQ rich results from Search on **2026-05-07** and
  deleted the feature documentation on **2026-06-15**, and the Rich Results Test no longer reports
  the type at all (see Pattern Survey (3)). The Rich Results Test remains useful for confirming
  `BlogPosting` and `BreadcrumbList`; just do not expect or require an FAQ verdict from it.
- **Head-term guard (decision 6) — the other hard constraint, now actually checked.** For each new
  file, dump the fields that determine what the page competes for and read them against decision 6:
  ```bash
  ( cd C:/pitchrank-league-pages/frontend
    for s in ecnl-vs-mls-next ecnl-vs-npl what-is-ecnl; do
      echo "=== $s ==="
      grep -nE '^(title|excerpt):|^#{2,3} ' "content/blog/$s.mdx"
    done
  )
  ```
  Confirm no `title`, `excerpt`, or heading **is** a bare head term, and none **leads with** one:
  `ecnl soccer`, `mls next`, `ecnl rl`, `edp soccer`. All four are live top-3 rankings held by the
  protected page. This is a read-and-judge check, not a regex — "MLS NEXT vs ECNL: which is higher?"
  is fine; a title of "MLS NEXT" or an H2 of "MLS NEXT Explained" is not.
- **Cross-link assertion — every required link must exist, with the `/blog/` prefix.** The build,
  sitemap, `llms.txt`, and FAQ checks all pass when these links are missing or malformed, so assert
  them directly:
  ```bash
  ( cd C:/pitchrank-league-pages/frontend
    fail=0
    LINK() { grep -qE "(^|[^!])\[[^]]*\]\(/blog/$2\)" "content/blog/$1.mdx"; }
    for s in ecnl-vs-mls-next ecnl-vs-npl what-is-ecnl; do
      for t in ecnl-vs-mls-next ecnl-vs-npl what-is-ecnl; do
        [ "$s" = "$t" ] && continue
        LINK "$s" "$t" || { echo "MISSING: $s -> /blog/$t"; fail=1; }
      done
      grep -qE "(^|[^!])\[[^]]*\]\(/rankings" "content/blog/$s.mdx" \
        || { echo "MISSING: $s -> /rankings"; fail=1; }
    done
    LINK youth-soccer-tryouts-2026 ecnl-vs-mls-next \
      || { echo 'MISSING: youth-soccer-tryouts-2026 -> /blog/ecnl-vs-mls-next'; fail=1; }
    [ "$fail" = 0 ] && echo 'all internal links present'
  )
  ```
  **The regex shape is load-bearing.** A plain `grep -q "(/blog/$t)"` reports success on text that
  renders no anchor at all — these files go through `react-markdown`
  (`frontend/components/BlogContent.tsx:32-35`), so inline code like `` `(/blog/ecnl-vs-npl)` `` and
  an image `![alt](/blog/ecnl-vs-npl)` both satisfy a bare substring match while producing zero
  links. Tested against six fixtures — real inline link, image, inline code, link in a blockquote,
  link in a GFM table cell, link at column 0 — the ERE above matches exactly the four real links and
  rejects the image and the code span. Note `[^!]` guards the `[`, **not** the `]`: in
  `![alt](/blog/…)` the `!` precedes the bracket, so the naive `](/blog/…)` form still passes images.
  Requiring `](` also catches a bare `(ecnl-vs-npl)` href, which resolves relative to the current URL
  and 404s.
  *(Deliberately shell, not a markdown-AST test: `frontend/package.json` declares only
  `react-markdown` and `remark-gfm` — no `unified`, `remark-parse`, or `mdast-util-*` — so an AST
  assertion would import a transitive dependency or add a new one, to guard a risk this one-liner
  already covers. `grep -P` is unavailable in this Git Bash build, hence plain ERE.)*
- Confirm `/blog` index and `/sitemap.xml` both list the three new slugs.
- **Fabrication spot-check — two sources, both required.** Re-read each page and confirm:
  (a) every league-structure claim traces to a URL recorded in
  `.turbo/seo/league-comparison-sources.md` (Step 2); **and**
  (b) every first-party figure and every rounding decision matches
  `.turbo/seo/league-comparison-firstparty.json` (Step 3). Check (b) is what validates the
  database-derived numbers — the URL table cannot, since those figures have no external source.
  A figure appearing in prose but not in that JSON is unsourced and must be removed or re-derived.
- Edge cases: no slug collides with an existing TSX post in `frontend/content/blog-posts.tsx`
  (`getAllBlogSlugs` silently prefers the TSX entry on collision); `readingTime` is set on all three
  (it feeds `wordCount` in JSON-LD); the three publish dates are distinct from each other and from
  every existing non-pillar post.

---

## Appendix A — Merge-Day Checklist

> ⚠️ **NOT part of implementation. Do not run any of this during `/implement-plan`.** These are
> manual steps for the maintainer immediately before merging the PR. `/finalize` owns staging and
> commit for the implementation itself; everything here happens later, by hand, on the open PR.

The three posts carry the **actual merge-day date**, but that date is unknown while the PR is
authored and reviewed (see the date contract in Step 4 — authoring uses *today's* date). If merge
slips, the frontmatter dates, `llms.txt`, and the monitoring baseline filename all go stale.
Skipping this is the most likely way a green PR turns red at merge time.

Immediately before merging:

1. **Sync with current `origin/main` FIRST — before regenerating anything.**
   ```bash
   cd C:/pitchrank-league-pages && git fetch origin && git merge origin/main
   ```
   This is not optional housekeeping. CI job `frontend-llms-drift` (`.github/workflows/ci.yml:97-114`)
   uses a bare `actions/checkout@v4` with **no `ref:`**, and the workflow triggers on
   `pull_request`, so GitHub checks out `refs/pull/<N>/merge` — a synthetic merge with **current**
   `main`. Meanwhile every guard in this plan pins to `merge-base HEAD origin/main`, the *branch
   point*, deliberately chosen to stay stable as main advances. If any blog post or FAQ change lands
   on main while this PR is open, locally-generated `llms.txt` reflects the branch's stale post set
   while CI regenerates from the merged set — and `git diff --exit-code public/llms.txt` fails.
   Resolve any `public/llms.txt` conflict by **regenerating**, never by hand-editing.
2. Set all three posts' `date` and `modifiedDate` to the true merge day, **preserving the distinct
   hours** — `T09:00:00Z` / `T10:00:00Z` / `T11:00:00Z`, quoted (Step 4). **Also bump
   `youth-soccer-tryouts-2026.mdx`'s `modifiedDate` to the merge day** — Step 5 edits that file too,
   and `frontend/CLAUDE.md:286-288` requires the current modification date. `BlogPostSchema.tsx:47`
   publishes it straight through, so a slipped merge would otherwise ship a stale `dateModified` on
   an already-indexed page. Its `date` is unchanged — it is an existing post, not a new one.
3. Re-run `npm run generate-llms` from `frontend/` and commit the regenerated
   `frontend/public/llms.txt`.
4. Re-run the llms drift check, the protected-page guard, the three-part `blog-faqs.ts` guard, the
   tryouts guard, and the changed-file allow-list — **recomputing the merge-base after the merge in
   step 1**, since it will have moved.
5. **Ensure the monitoring baseline exists, then align its date.**
   `.turbo/seo/league-pages-baseline-<merge-date>.json`.
   - **If it does not exist yet, CREATE it now** by running Appendix B step 1 — nothing in the
     Implementation Steps produces it, and `origin/main` has no prior `league-pages-baseline`
     artifact to inherit. Appendix B step 1 is the only creator.
   - If it already exists under an earlier authoring date, this is a **rename** — not a re-pull —
     unless the 28-day window has drifted materially, in which case re-pull.
   - Either way it is under `.turbo/`, so **force-add it** (`git add -f` + `git ls-files
     --error-unmatch`, as in Step 2) and add its path to the changed-file allow-list.
   - ⚠️ **Do not merge without it.** Rollback trigger (b) compares combined cluster clicks against
     this file; with no baseline there is nothing to compare at T+14/T+28, and the monitoring that
     actually protects the hard constraint silently becomes a no-op.

---

## Appendix B — Post-Deploy Monitoring and Rollback

> ⚠️ **NOT executable and NOT part of implementation.** No step here runs during `/implement-plan`.
> **Owner: Dallas (repo maintainer)** — it requires GSC access and human judgment, and is not
> delegable to CI. **Nothing else in this plan fires these checks, so they must be scheduled
> explicitly** via `/schedule` or a calendar entry. An unscheduled check does not happen.

Every check in Verification is **structural**. The hard constraint is about **rankings**, and
cannibalization is a post-index effect that no pre-merge check can observe. This is what actually
protects it.

1. **Before merge — record the baseline. THIS STEP IS THE FILE'S ONLY CREATOR**, and Appendix A
   step 5 will not find it unless this has run. Pull via the GSC API (`sc-domain:pitchrank.io`,
   query+page dimensions, 28-day window) and write to
   `.turbo/seo/league-pages-baseline-<merge-date>.json` (created at authoring time, renamed in
   Appendix A step 5). An artifact that lives only in a session's context cannot be compared against
   later. Capture **two groups**, not one:
   - **(i) The four protected head terms** — `ecnl soccer` (#2.4), `mls next` (#2.2), `ecnl rl`
     (#2.9), `edp soccer` (#2.9) — plus the protected page's totals, noting which URL ranks for each.
   - **(ii) The overlapping comparison queries the new pages actually target.** These are the ones
     genuinely exposed to cannibalization, and an earlier draft omitted them entirely:
     `is npl or ecnl better` (678 imp, #8.2), `national 1 league vs ecnl` (167 imp),
     `difference between ecnl and ecnl rl`, `mls next vs ecnl vs npl`, `ecnl vs npl`,
     `is ecnl rl better than npl`, `npl vs mls next`, `is usys better than ecnl`,
     `usys national league vs ecnl`, `is ecnl the highest level of soccer`, `what is after mls next`,
     `what does ecnl stand for`, `ecnl levels`, `ecnl meaning`.
     Record clicks, impressions, position, **and the ranking URL** for each.
2. **Schedule the two re-checks at merge time**, computing concrete calendar dates from the merge
   date (not "T+14" in the abstract).
   - **Indexing precondition — use real URL Inspection API fields.** The API returns **no `INDEXED`
     status**; `IndexStatusInspectionResult.verdict` is one of
     `VERDICT_UNSPECIFIED | PASS | PARTIAL | FAIL | NEUTRAL`
     (https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult).
     The correct gate for each new URL is:
     ```
     indexStatusResult.verdict === 'PASS'
       && /^(Submitted and indexed|Indexed)/.test(indexStatusResult.coverageState)
       && indexStatusResult.googleCanonical === '<the new URL>'
     ```
   - ⚠️ **The `googleCanonical` clause is doing real work, not belt-and-braces.** If Google folds a
     new comparison page into `/blog/youth-soccer-levels-explained` as its chosen canonical,
     `coverageState` reads `"Duplicate, Google chose different canonical than user"` — that is the
     cannibalization failure mode appearing **in the index before it appears in rankings**, i.e. the
     earliest possible warning this plan can get.
   - If the pages are not yet indexed at T+14, the comparison is not yet meaningful and the window
     shifts.
3. **Record each re-check** to `.turbo/seo/league-pages-check-T14-<date>.json` and
   `…-T28-<date>.json`, same shape as the baseline, so the three files are directly comparable.
   These land via a **small follow-up PR** — by then the feature branch and worktree are deleted, so
   an uncommitted file has nowhere to live and the T+28 comparison (and any rollback decision) would
   have nothing to read. A PR is required regardless: repo `CLAUDE.md:25` forbids committing to main
   directly.
4. **Rollback triggers, defined in advance — two of them.**
   - **(a) Head-term regression.** The protected page drops **more than ~1.5 positions** on any of
     the four head terms, **and** a new page is now ranking for that query, **and** it has not
     recovered by T+28.
   - **(b) Net traffic regression across the shared intent.** Combined clicks across the protected
     page **plus** the three new URLs, on the group (ii) queries, is **below baseline** at T+28.
     This second trigger exists because trigger (a) cannot detect the failure that matters most
     here: those queries earn **0 clicks today**, so the protected page *losing* position on them
     while a new page gains is the **intended** substitution, not a regression. Measuring only the
     protected page's position would read a successful hand-off as damage — and, worse, would read
     "both pages sank" as success on three of the four head terms. Judge the cluster, not the page.
5. **Rollback action — removal plus redirect. This is the ONLY supported path.**
   *Do not attempt `noindex`:* `generateMetadata` (`frontend/app/blog/[slug]/page.tsx:28-70`) emits no
   `robots` key and `BlogPost` (`frontend/lib/blog.tsx:6-17`) has no noindex field, so adding one
   would mean editing the shared `[slug]` metadata builder — affecting all 37 existing posts, exactly
   the shared-surface change this plan avoids everywhere else.
   The rollback change set is **eight items** (up to seven files), and omitting any of them breaks
   the rollback PR:
   1. Delete `frontend/content/blog/<offending-slug>.mdx`.
   2. Remove its key from `frontend/lib/blog-faqs.ts` (otherwise the Step 6 parity test fails).
   3. Remove that slug from the Step 6 test's slug list in `frontend/lib/blog-faqs.test.ts`.
   4. Add the redirect to `frontend/next.config.ts:42-69`, matching the shape of the three existing
      blog entries exactly:
      ```js
      { source: '/blog/<offending-slug>', destination: '/blog/youth-soccer-levels-explained', permanent: true }
      ```
   5. Remove the now-dead cross-links to that page from the **two surviving comparison pages**, and
      bump each of their `modifiedDate` values (per `frontend/CLAUDE.md:284-289`).
   6. **If — and only if — the offending slug is `ecnl-vs-mls-next`:** remove the inbound link added
      by Step 5 from `frontend/content/blog/youth-soccer-tryouts-2026.mdx` and bump its
      `modifiedDate`. The redirect in item 4 would keep the link working, but leaving it points a
      live page at a redirect for no reason. Rolling back either other slug leaves that file alone.
   7. Update the cross-link assertion in Verification to drop the removed slug, or it will fail the
      rollback PR by asserting links that no longer should exist.
   8. Regenerate `frontend/public/llms.txt` (otherwise `frontend-llms-drift` fails the rollback PR).
   **The protected page needs no change at all** — this plan never linked to the new pages from it,
   so there is no dead link to clean up there and the hard constraint stays intact through rollback.
6. If the protected page holds and the new pages accrue their own impressions, the change succeeded —
   record the closing numbers in `.turbo/seo/league-pages-check-T28-<date>.json` and close it out.

## Context Files

⚠️ **Read these from the WORKTREE, not `C:/PitchRank`.** The main checkout is 83 commits behind with
143 dirty files, and the drift is not theoretical: `blog-faqs.ts` there is 26 lines shorter and the
protected page's entry sits at **line 932, not the `:958`** cited below, while `lib/stats.ts` is
**untracked** there entirely. **All line numbers below are BASELINE line numbers** — if an anchor
looks wrong, confirm with:
```bash
git -C C:/pitchrank-league-pages show \
  "$(git -C C:/pitchrank-league-pages merge-base HEAD origin/main):<path>"
```

- `C:/pitchrank-league-pages/frontend/content/blog/ohio-youth-soccer-rankings-guide.mdx` — the
  structural template to mirror: frontmatter, section shape, GFM table, blockquote CTA, FAQ + About
  footer.
- `C:/pitchrank-league-pages/frontend/content/blog/youth-soccer-levels-explained.mdx` — the protected
  page. **Read only — this plan makes zero edits to it.** Read it to see which questions it already
  answers, so the new pages do not duplicate its coverage or its FAQs.
- `C:/pitchrank-league-pages/frontend/lib/blog.tsx` — `BlogPost` interface (`:6-17`), frontmatter
  defaults, unsorted filesystem discovery (`:54`), date-only sort (`:65`), slug de-dup behavior.
- `C:/pitchrank-league-pages/frontend/lib/blog-faqs.ts` — `FAQ` type and `BLOG_FAQS` shape to extend.
  The protected page's entry is at `:958` — read it (to differentiate the new FAQs), do not edit it.
  Also read `BLOG_FAQS['youth-soccer-tryouts-2026']` at `:1001`, whose question at **`:1023`**
  (`'What is the difference between ECNL and MLS NEXT?'`) is the closest existing registered question
  to `/blog/ecnl-vs-mls-next`'s head intent — the one Step 6 assertion (d) exists to catch.
- `C:/pitchrank-league-pages/frontend/content/blog/youth-soccer-tryouts-2026.mdx` — the **one**
  non-protected existing post this plan edits (Step 5: add one link + bump `modifiedDate`). Its
  visible `### Is ECNL or MLS NEXT better for my child?` FAQ is at `:199`.
- `C:/pitchrank-league-pages/frontend/app/blog/[slug]/page.tsx` — `generateMetadata` (`:28-70`),
  central schema wiring (`:83-101`), and the `PageHeader` call (`:103`) that drives decision 2.
- `C:/pitchrank-league-pages/frontend/lib/stats.ts` — `FALLBACK_STATS` (`:13`) and `getDbStats`
  usage; the sanctioned source for any sitewide team/game count appearing in prose (decision 3).
- `C:/pitchrank-league-pages/frontend/CLAUDE.md` — `dateModified` convention (lines 284-289) and
  derived-file regeneration procedure (lines 293-303).
- `C:/pitchrank-league-pages/frontend/scripts/generate-llms-txt.ts` — how posts are enumerated into
  llms.txt; `renderBlog` (`:60`), `renderStatePillars` (`:69`), `main` (`:89`).
