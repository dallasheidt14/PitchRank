---
name: GEO Week 5 Foundations
slug: geo-week5-foundations
status: draft
created: 2026-04-30
related:
  - .turbo/geo-playbook-2026-04-29.md
  - PR #697 (robots.txt — hour-zero veto fix, merged 2026-04-29)
---

# GEO Week 5 Foundations

## Why

Week 5 of the 4-month GEO playbook (`.turbo/geo-playbook-2026-04-29.md`). Three of the four hour-zero / Week-1 veto items remain after PR #697 (robots.txt) cleared the crawler-blocking veto. This spec covers the rest:

- **Author entity** — the GEO audit framework auto-caps a page's score at 60 if there's no identifiable author entity backing the JSON-LD author field. PitchRank's existing `BlogPostSchema` emits `author: { @type: Person, name: post.author }` where `post.author` is a string with no entity backing it. The methodology page emits no author at all.
- **dateModified** — the Princeton GEO paper measured a 3× citation rate for content edited within ~60 days. PitchRank's `BlogPostSchema` falls back to `datePublished` when `modifiedDate` is missing, so every existing blog post is treated as never-updated.
- **llms.txt** — a 2024-era proposal (~800 sites adopted as of mid-2025) where sites publish a markdown index of their best content for LLMs to discover. PitchRank's existing `frontend/public/llms.txt` is a 16-line stub listing 3 pages.

These three together unblock every other GEO move; until they ship, evidence-density rewrites in Month 2 land on content that AI engines either can't authoritatively attribute or treat as stale.

## Scope

A single PR titled `geo: Week 5 foundations (author entity, llms.txt, dateModified)` covering three deliverables. Each is independent of the others; the bundling is for review efficiency, not coupling.

### Deliverable 1 — Author entity launch

**Goal:** every authored page on pitchrank.io has an `Organization`-shaped `author` in its JSON-LD that points to a canonical entity URL with `sameAs` external linkage.

**Decisions made:**

- Author entity is `Organization`, name `"PitchRank Team"` (not `Person`). Tradeoff acknowledged: `Person` byline with named individual is slightly stronger for ChatGPT/Claude `sameAs` weighting; `Organization` is defensible (Economist, Bloomberg use this pattern) and matches how PitchRank operates (small team, founder + contributors).
- Canonical entity URL: `https://www.pitchrank.io/authors/pitchrank-team`. New Next.js App Router page with ~150-word team description, what PitchRank does, ranking-engine summary (no "Glicko-2" by name per established voice), branded layout matching existing pages.
- **Reuse existing site identity.** `frontend/components/StructuredData.tsx:10-22` already emits a sitewide `Organization` (name: `"PitchRank"`) with `sameAs` to twitter/instagram/facebook/linkedin/pitchrank. `frontend/app/layout.tsx:105-106` sets `@pitchrank` Twitter creator+site. `frontend/components/Footer.tsx:15-33` links the same four profiles. The new author entity must reuse the same `sameAs` array — diverging would fork PitchRank's identity into two inconsistent org records.
- **Implementation: extract a shared `PITCHRANK_SAMEAS` constant** (likely in `frontend/lib/constants.ts`) that both `StructuredData.tsx` and the new author entity reference. The two entities have different `@id` and different `name` (`"PitchRank"` for the homepage, `"PitchRank Team"` for the author entity), but identical `sameAs`. This is well-formed schema (two related Organization entities, both pointing to the same external profiles).
- `sameAs` array: twitter/instagram/facebook/linkedin/pitchrank — match `StructuredData.tsx` exactly.
- No new visible bylines on blog posts. Existing `app/blog/[slug]/page.tsx:104` already renders `<span>{post.author}</span>` with `post.author === "PitchRank Team"` for all 16 MDX posts and 6 of 7 TSX posts. The retrofit is JSON-LD-only on blog posts: schema author switches from `Person` to `Organization` with `@id` linking to the entity URL.
- Methodology page (`app/methodology/page.tsx`) gets an `Article`-style JSON-LD schema with `Organization` author, `datePublished`, and `dateModified`. **No visible byline** — matches the `/rankings/*` rule that visible bylines belong on dated editorial, not on data/system explainer pages. The audit-framework veto is cleared by JSON-LD alone.
- Ranking pages (`/rankings/*`) explicitly out of scope for visible byline. JSON-LD author there is deferred — not load-bearing for clearing the audit veto, and visible byline on data-display pages feels off.
- **`BlogPost.author` type stays a string** at `lib/blog.tsx:12`. Only the JSON-LD shape inside `BlogPostSchema` rewraps from `Person` to `Organization` with `@id` and `sameAs`. Visible byline at `app/blog/[slug]/page.tsx:104` (`<span>{post.author}</span>`) and OpenGraph metadata at `:51` (`authors: [post.author]`) continue to work unchanged.

**Components affected (concrete):**

- `frontend/lib/constants.ts` — add `PITCHRANK_SAMEAS` constant (string array of the four social URLs) AND a `PITCHRANK_TEAM_AUTHOR` constant exporting the entity object (`@type: Organization`, `@id: <entity URL>`, `name: 'PitchRank Team'`, `url`, `sameAs: PITCHRANK_SAMEAS`). Single source of truth for the author.
- `frontend/components/StructuredData.tsx` — refactor lines 17-22 to import `PITCHRANK_SAMEAS` from `lib/constants.ts` (so the two entities share the same array). No behavior change for the homepage Organization; just deduplicates.
- `frontend/components/BlogPostSchema.tsx` — change `author` field shape from `Person` to `Organization`, importing `PITCHRANK_TEAM_AUTHOR` from `lib/constants.ts`. The JSON-LD `author` field becomes the entity object directly. The component's `author: string` prop stays — it continues to feed the visible byline, but the schema emits the Organization entity instead of `{ @type: Person, name: author }`.
- `frontend/app/methodology/page.tsx` — add a new `ArticleSchema` (or reuse `BlogPostSchema` with appropriate props) that emits `Article`-style JSON-LD with `Organization` author + `datePublished` + `dateModified`. **No visible byline added.**
- `frontend/app/authors/pitchrank-team/page.tsx` — new file, new route. ~150-word team description. JSON-LD `Organization` schema for the entity itself (uses `PITCHRANK_TEAM_AUTHOR`). Page exists primarily as the `@id` target for blog/methodology authors and as a UX trust page.

**Not in scope of this deliverable:**

- Ranking pages and other non-authored content.
- Adding a `Person` entity for individual contributors (deferred until contributor pool exists).
- Restructuring `StructuredData.tsx`'s separate `Organization` and `SportsOrganization` entities (latent issue but out of scope).

### Deliverable 2 — llms.txt expansion

**Goal:** `frontend/public/llms.txt` becomes a real content map for AI engines, generated programmatically so it doesn't drift as content ships.

**Decisions made:**

- **Generator language: TypeScript**, executed via `tsx` (already in `frontend/package.json:85` as `"tsx": "^4.21.0"`, used by the existing `process:prospective:heuristic` script). Reasoning: the frontend already depends on `gray-matter` (used at `lib/blog.tsx:3` for MDX parsing), so a TS script reuses the same parsing path the live site uses. TypeScript types align with the `BlogPost` interface. Single-language tooling for the frontend. No new Python dependency. Easier to run alongside `next build` in CI.
- Script lives at `frontend/scripts/generate-llms-txt.ts`. Reads MDX frontmatter via gray-matter, reads TSX-source posts by importing `@/content/blog-posts`, references `STATE_PILLAR_SLUGS` from `frontend/lib/cohort-seo.ts:112-126` for state pillars (no duplicate hand-maintained list).
- **`STATE_PILLAR_SLUGS` must be exported.** Currently declared as `const` (module-private) at `lib/cohort-seo.ts:112`. Change to `export const STATE_PILLAR_SLUGS` so the generator can import it. No other consumer needs the symbol today, but exporting it is required for the generator to compile.
- Run manually after content changes. Documented in `frontend/CLAUDE.md`. CI enforces freshness via a non-mutating drift check (see acceptance criteria R10).
- llms.txt content sections (in order):
  1. Site name + one-paragraph description (preserved from current file)
  2. `## Core Content` — methodology, top ranking pages by impressions
  3. `## Blog` — non-pillar blog posts (MDX + TSX) with title + one-line summary from `excerpt`. **Excludes any post whose slug appears in `STATE_PILLAR_SLUGS`** — those go to State Pillars instead. Section intro line: "*State-specific guides are listed under State Pillars below.*" After exclusion, this section emits 10 posts (23 total − 13 state pillars).
  4. `## State Pillars` — canonical home for the 13 state-pillar pages, derived from `STATE_PILLAR_SLUGS` in `lib/cohort-seo.ts`. Of those 13, 11 are MDX files in `content/blog/` and 2 are TSX (CA, TX) from `content/blog-posts.tsx`. The generator resolves each slug against the merged `getAllBlogPosts()` set so MDX-vs-TSX origin is transparent.
  5. `## About` — `/`, `/authors/pitchrank-team`
- Generator inputs and authoritative sources:
  - Blog posts: `frontend/lib/blog.tsx::getAllBlogPosts()` (the same loader the live site uses; covers MDX + TSX)
  - State pillars: `frontend/lib/cohort-seo.ts::STATE_PILLAR_SLUGS` (importable map)
  - Methodology: hard-coded path (`/methodology`)
  - Ranking pages: explicit curated list at top of script (e.g., top 5 state ranking pages by GSC impressions; the curation tracks SEO strategy, not auto-derivable)
- Output is committed to `frontend/public/llms.txt`. Script is idempotent — running it twice produces identical output.
- **Fail-closed on parse errors.** If any expected content source can't be read or parsed, the script exits non-zero rather than emitting partial output. Silent partial output is worse than failure.

**Components affected:**

- `frontend/scripts/generate-llms-txt.ts` — new file. TypeScript executed via `tsx`. Imports from `@/lib/blog` and `@/lib/cohort-seo`. Emits llms.txt to stdout or to `frontend/public/llms.txt`.
- `frontend/lib/cohort-seo.ts` — change `STATE_PILLAR_SLUGS` declaration on line 112 from `const` to `export const`. No other behavior change.
- `frontend/public/llms.txt` — replaced (committed output of generator).
- `frontend/CLAUDE.md` — documents `npx tsx scripts/generate-llms-txt.ts > public/llms.txt` (or equivalent npm script) as part of the publish flow.
- `frontend/package.json` — npm script: `"generate-llms": "tsx scripts/generate-llms-txt.ts > public/llms.txt"`.
- `.github/workflows/<existing>.yml` — add a CI step that runs the generator and `git diff --exit-code public/llms.txt` to fail when the committed file is stale (see R10).

### Deliverable 3 — dateModified backfill + convention

**Goal:** every blog post and the methodology page emit a meaningful `dateModified`, and the codebase enforces a convention that any future edit bumps it.

**Decisions made:**

- One-time reset: set `dateModified` on **all 23 existing blog posts (16 MDX + 7 TSX)** to the spec-implementation date (the day this work ships). Tradeoff acknowledged: this is a uniform date, not historically accurate. The Princeton 3× recency lift fires on recent dates regardless of uniformity. Honest dates from `git log` would scatter across 2-4 months and offer little additional benefit since they all predate Week 5 evidence retrofits anyway.
- Going-forward convention: every blog post edit must bump `dateModified` to the current date. Document in `frontend/CLAUDE.md`. No automated enforcement (lint rule or pre-commit hook) in this spec — too much complexity for a convention that's checked at PR review.
- Schema location: `dateModified` already passes through `BlogPostSchema.modifiedDate` (line 49: `dateModified: modifiedDate || date`). Backfill happens in MDX frontmatter (new `modifiedDate` field) AND on TSX `BlogPost` objects (new `modifiedDate` property). Both are wired through `lib/blog.tsx` to the schema component.
- **`lib/blog.tsx` changes (one-line additions):**
  - `BlogPost` interface at lines 6-16: add `modifiedDate?: string`
  - `parseMarkdownFile` at lines 23-39: add `modifiedDate: data.modifiedDate` to the returned object
  - `getAllBlogPosts` at lines 60-63: no change needed; merged TSX + MD posts both surface `modifiedDate` if present
- **TSX-source author normalization.** `frontend/content/blog-posts.tsx:2885` has `author: 'PitchRank'` (the one outlier). Normalize to `'PitchRank Team'` so all 23 blog posts share the same byline string. The schema author entity is the same regardless (single Organization), but the visible byline string should be consistent.
- Methodology page: emits `datePublished` and `dateModified` in its new schema. Both set to spec-implementation date initially.

**Components affected:**

- All 16 MDX blog post files in `frontend/content/blog/` — add `modifiedDate: '2026-04-30'` to frontmatter.
- `frontend/content/blog-posts.tsx` — add `modifiedDate: '2026-04-30'` to each of 7 BlogPost objects (lines 33, 423, 908, 1200, 1876, 2570, 2885). Normalize line 2885's author from `'PitchRank'` to `'PitchRank Team'`.
- `frontend/lib/blog.tsx` — add `modifiedDate?: string` to `BlogPost` interface (lines 6-16); surface `data.modifiedDate` in `parseMarkdownFile` return (lines 23-39).
- `frontend/app/blog/[slug]/page.tsx` — pass `modifiedDate={post.modifiedDate}` prop to `BlogPostSchema`.
- `frontend/CLAUDE.md` — document the bump-on-edit convention.

## Out of scope (deferred to later weeks)

- gego measurement infrastructure (Week 6)
- Wikidata entry + Wikipedia article (Week 7)
- First quarterly first-party data report (Week 8 — "State of Texas Youth Soccer Spring 2026")
- Evidence retrofit on blog content (Month 2 — adding real expert quotes, external citations, named-entity density)
- Per-engine moves: Reddit/Quora authority work (Month 3), methodology essay rewrite for Claude (Month 3)
- Person-shaped `Author` entity for individual contributors (deferred until contributor pool exists)
- Pre-commit hook or lint rule enforcing `modifiedDate` bumps (CI drift check on llms.txt covers the higher-risk drift; per-post `modifiedDate` enforcement is a convention)
- GitHub Actions auto-regeneration / auto-commit of `llms.txt` (CI drift check is sufficient — fail PR rather than silently regenerate)
- Restructuring `StructuredData.tsx`'s separate `Organization` and `SportsOrganization` entities

## Open questions

All key decisions resolved during refine-spec. Methodology schema type committed to `Article`; author entity `@id` committed to the URL string (`https://www.pitchrank.io/authors/pitchrank-team`). Final validator follow-ups (Rich Results Tester pass on all changed schemas) belong in `/finalize`, captured by R9.

## Acceptance criteria (Requirements)

For the PR to be considered complete:

- [ ] **R1:** `/authors/pitchrank-team` route exists, renders the team description, and emits `Organization` JSON-LD (sourced from `PITCHRANK_TEAM_AUTHOR` constant in `lib/constants.ts`) with name `PitchRank Team`, the entity URL, and the shared `sameAs` array.
- [ ] **R2:** Shared `PITCHRANK_SAMEAS` constant in `lib/constants.ts` is consumed by both `StructuredData.tsx` (homepage Organization) and the author entity. Verified by reading both files: identical reference, no duplication.
- [ ] **R3:** All 23 blog posts (16 MDX + 7 TSX) emit `BlogPosting` JSON-LD with `author: { @type: Organization, @id: <entity URL>, name: 'PitchRank Team', sameAs: [...] }`. Verified by viewing source on at least 3 sampled posts (1 MDX, 1 TSX, 1 the previously-`'PitchRank'`-author post `what-is-powerscore-youth-soccer`).
- [ ] **R4:** All 23 blog posts emit `dateModified: '2026-04-30'` distinct from `datePublished`. Verified in JSON-LD on a sample MDX post and a sample TSX post.
- [ ] **R5:** `frontend/content/blog-posts.tsx:2885` normalized to `author: 'PitchRank Team'` (was `'PitchRank'`).
- [ ] **R6:** `/methodology` page emits an `Article`-style JSON-LD with `Organization` author + `datePublished` + `dateModified`. No visible byline added (matches /rankings rule).
- [ ] **R7:** `frontend/public/llms.txt` regenerated via `tsx scripts/generate-llms-txt.ts` and contains: intro, Core Content section, Blog section (10 non-pillar posts), State Pillars section (13 pillars from `STATE_PILLAR_SLUGS`), About section. State pillars appear only in the State Pillars section, never in Blog (see dedup rule in Deliverable 2).
- [ ] **R8a:** `frontend/CLAUDE.md` documents the bump-on-edit `dateModified` convention (every blog post edit must bump `modifiedDate` to the current date).
- [ ] **R8b:** `frontend/CLAUDE.md` documents the regeneration command for `llms.txt` (`tsx scripts/generate-llms-txt.ts > public/llms.txt`) and when to run it (after blog or state-pillar additions).
- [ ] **R9:** All schemas validate at https://search.google.com/test/rich-results without errors.
- [ ] **R10:** CI step runs `tsx scripts/generate-llms-txt.ts > public/llms.txt` followed by `git diff --exit-code public/llms.txt`, failing the build when the committed file is stale relative to current content. Generator hard-fails (non-zero exit) when an expected content source cannot be parsed, rather than skipping with a stderr warning.
- [ ] **R11:** No "Glicko-2" by name appears in any new user-facing content (per `feedback_no_glicko_in_content.md`). No "cohort" appears in any new user-facing content (per `feedback_group_not_cohort.md`).
- [ ] **R12:** `tsc --noEmit` passes; `next build` exits 0; CI green on PR.

## Risks and mitigations

- **Risk:** Switching JSON-LD `author` shape from `Person` to `Organization` may temporarily affect Google rich-result rendering for blog posts. *Mitigation:* validate at Rich Results Test before merging; both shapes are valid `BlogPosting.author` types so the change is well-defined.
- **Risk:** `modifiedDate` uniform across all 23 posts could be detected by AI engines as artificial recency. *Mitigation:* the GEO playbook's no-fabrication rule flags fabricated *content*; uniform `dateModified` from a one-time reset is a normal site-migration signal and not deceptive. Going forward, edits bump it naturally.
- **Risk:** llms.txt generator script depends on `lib/blog.tsx::getAllBlogPosts` and `lib/cohort-seo.ts::STATE_PILLAR_SLUGS`. Schema-breaking changes to either would crash the generator. *Mitigation:* fail-closed parse errors (R10) make this loud rather than silent — generator crashes, CI fails, fix lands before content drift.
- **Risk:** `/authors/pitchrank-team` page added to sitemap and indexed but content is thin (~150 words). Could be flagged as low-quality. *Mitigation:* page is functional first (entity target for `sameAs`), informational second. Length can be expanded in a later pass; thin-content penalty is unlikely for a single author page.
- **Risk:** Two `Organization` entities (homepage `"PitchRank"` at `BASE_URL` + author `"PitchRank Team"` at `/authors/pitchrank-team`) could confuse aggregators about which is canonical. *Mitigation:* shared `sameAs` keeps them linked to the same external profiles. The two entities serve different schema slots (site identity vs author byline) — this is the same pattern Bloomberg, Economist, and Reuters use.

## Implementation hint for plan-shells stage

Three natural shells:

1. **Shell 1 — Author entity** (covers R1, R2, R3, R5, R6) — extract `PITCHRANK_SAMEAS` + `PITCHRANK_TEAM_AUTHOR` constants in `lib/constants.ts`, refactor `StructuredData.tsx` to consume the shared constant, update `BlogPostSchema.tsx` to emit Organization author, normalize TSX outlier author string, build new `/authors/pitchrank-team` page, add Article schema to methodology page (no byline).
2. **Shell 2 — dateModified backfill + convention** (covers R4, R8a) — `BlogPost` interface field, `parseMarkdownFile` wiring, frontmatter additions on 16 MDX files, `modifiedDate` property on 7 TSX BlogPost objects, call-site wiring at `app/blog/[slug]/page.tsx` to pass `modifiedDate` prop, `frontend/CLAUDE.md` convention doc.
3. **Shell 3 — llms.txt generator** (covers R7, R8b, R10) — TS script via `tsx` using shared `getAllBlogPosts` + exported `STATE_PILLAR_SLUGS`, regenerated llms.txt output, npm script, CI drift check workflow step, `frontend/CLAUDE.md` regeneration doc.

Shell ordering: Shell 1 should land first because it modifies `BlogPostSchema.tsx` and the new `lib/constants.ts` exports that downstream callers depend on. Shells 2 and 3 are independent of each other and can run in parallel after Shell 1.

**Merge-friction risk:** Shells 2 and 3 both edit `frontend/CLAUDE.md` (R8a and R8b respectively). The two edits are in different sections of the file, but coordinate the diffs to avoid trivial conflicts. (`BlogPostSchema.tsx` already accepts `modifiedDate?: string` end-to-end at lines 13/31/49, so Shell 2 does NOT touch that component.)

R9, R11, R12 are cross-cutting verification gates handled in `/finalize`.
