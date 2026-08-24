---
status: done
spec: .turbo/specs/geo-week5-foundations.md
---

# Plan: Author entity (Organization JSON-LD + /authors/pitchrank-team + methodology Article schema)

## Context

The GEO audit framework auto-caps a page's score at 60 if there's no identifiable author entity backing the JSON-LD `author` field. PitchRank's existing `BlogPostSchema` emits `author: { @type: Person, name: post.author }` — a string with no entity behind it. The methodology page emits no author at all. This shell clears the audit veto by emitting an `Organization`-shaped author entity ("PitchRank Team") on every authored page, and by giving that entity a canonical home page at `/authors/pitchrank-team`.

The site already has a sitewide `Organization` entity at `frontend/components/StructuredData.tsx:10-22` with `sameAs` to twitter/instagram/facebook/linkedin. To avoid forking PitchRank's identity into two inconsistent org records, this plan extracts a shared `PITCHRANK_SAMEAS` constant that both the homepage `Organization` and the new author entity consume. The two entities have different `@id` and `name` (`"PitchRank"` for the site, `"PitchRank Team"` for authored content) but identical `sameAs` — well-formed schema, the pattern Bloomberg/Economist/Reuters use.

Methodology page also gets an `Article`-style JSON-LD schema in this shell (no visible byline added, matching the `/rankings/*` "data-display pages don't get bylines" rule). The byline-on-blog already renders via `<span>{post.author}</span>` at `app/blog/[slug]/page.tsx:104` — this plan does not change visible bylines on blog posts; it only changes the JSON-LD shape.

## Pattern Survey

### Analogous Features

- `frontend/components/StructuredData.tsx:8-88` — Sitewide `Organization` + `WebSite` + `SportsOrganization` JSON-LD; rendered once from root layout. Defines the canonical `sameAs` list (lines 17-22) that the new `PITCHRANK_SAMEAS` constant must source from.
- `frontend/components/BlogPostSchema.tsx:23-76` — `BlogPosting` schema; emits `Person` author at lines 50-53, `Organization` publisher at 54-61, and `mainEntityOfPage` with self-`@id` URL at 63-66. Pattern the new Organization-author shape needs to slot into. Publisher logo path: `${BASE_URL}/logos/pitchrank-wordmark.svg` (line 59).
- `frontend/components/FAQSchema.tsx:7-111` — Methodology page's existing FAQ schema; takes no props (entirely static), lives next to where `MethodologySchema` will sit.
- `frontend/components/BlogFAQSchema.tsx:14-36` — Schema component with structured props (`faqs: FAQ[]`); shows the prop-based shape used when content is dynamic.
- `frontend/components/RankingsSchema.tsx:25-114` — Multi-schema component returning a fragment with multiple `<script>` tags; pattern for emitting more than one JSON-LD block from a single component.
- `frontend/components/BreadcrumbSchema.tsx:19-32` — Breadcrumb pattern; already wired into `app/methodology/page.tsx:41`. Methodology uses a single-item breadcrumb (`[{ name: 'Methodology', href: '/methodology' }]`); the new `/authors/pitchrank-team` page should mirror that single-item shape rather than inventing a parent route.
- `frontend/app/blog/[slug]/page.tsx:104` — Visible byline rendered as plain `<span>{post.author}</span>` (no `<Link>`). Per spec, this stays unchanged; only JSON-LD shape changes.
- `frontend/app/blog/[slug]/page.tsx:51` — `openGraph.authors: [post.author]`. Per spec, this stays unchanged; the spec explicitly preserves OG metadata as-is in this iteration.
- `frontend/app/methodology/page.tsx` and `frontend/app/privacy-policy/page.tsx:1-25` — Idiomatic flat static-page shape: `metadata` export + default page renders `BreadcrumbSchema` + `PageHeader` + content. Closest precedent for `app/authors/pitchrank-team/page.tsx`.

### Reusable Utilities

- `frontend/lib/schema-utils.ts:5-7` — `safeJsonLd(data: unknown): string` — `JSON.stringify(data)` followed by `.replace(/</g, '\u003c')` (the source literal is the four-character escape `<`, written here with a leading backslash escape so it round-trips through markdown) — replaces every `<` with its Unicode escape so an inline JSON-LD payload can't terminate the surrounding `</script>` tag. Used by every existing schema component. The new `MethodologySchema` and the author-page JSON-LD MUST go through `safeJsonLd`.
- `frontend/lib/schema-utils.test.ts:1-25` — Vitest test for `safeJsonLd`. Confirms vitest is the test runner; provides a template for any new schema-utility tests.
- `frontend/lib/constants.ts:61` — `BASE_URL` (env-overridable, defaults to `https://www.pitchrank.io`). Already imported by every schema component for absolute URLs. The new `PITCHRANK_TEAM_AUTHOR.url` must be `${BASE_URL}/authors/pitchrank-team`.
- `frontend/components/PageHeader.tsx` — Standard page header with `showBackButton`/`backHref`. Use on `/authors/pitchrank-team` for visual consistency.
- `frontend/lib/blog.tsx:34` — `author: data.author || 'PitchRank Team'` — MDX-loader default fallback already canonicalizes to `'PitchRank Team'`. Fixing `blog-posts.tsx:2885` to `'PitchRank Team'` is consistent with this default.

### Convention Anchors

- **Schema components are server components by default.** None of the existing schema components declare `'use client'`. Render only a `<script type="application/ld+json">` and have no client-side behavior. New `MethodologySchema` is a server component.
- **JSON-LD output shape.** Every schema component returns `<script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(schema) }} />`. Single tag for one schema, fragment of multiple `<script>` tags when multiple are needed. Never a JSON literal in JSX.
- **Schema component file location and naming.** All live at `components/*Schema.tsx`. Named exports preferred; some also re-export as default. New: `components/MethodologySchema.tsx`.
- **Prop shape.** Static-content schemas take no props (`FAQSchema`, sitewide schemas in `StructuredData`). Dynamic schemas declare `interface FooSchemaProps {…}` and destructure in the signature. The new `MethodologySchema` will be prop-based (`datePublished`, `dateModified`) per spec — Shell 1 step 5b passes initial values from the page, and the convention going forward is to bump dates without touching the component.
- **`@id` precedent.** Used exactly once today: `BlogPostSchema.tsx:65` uses `'@id': postUrl` inside `mainEntityOfPage`. There is no existing pattern of standalone `@id` for a JSON-LD entity URL elsewhere. The new author entity adopts `'@id': '${BASE_URL}/authors/pitchrank-team'` — a new convention extending the existing usage.
- **`lib/constants.ts` organization.** Section banner comments (`// --- Site URL ---` line 58, `// --- Age Groups ---` line 69, `// --- Gender ---` line 96). Each section: typed export (`as const` for tuples, explicit `Record<>` for maps). JSDoc `/** … */` precedes each export. New `PITCHRANK_SAMEAS` and `PITCHRANK_TEAM_AUTHOR` go in a new `// --- Brand / Author ---` section near `BASE_URL`.
- **App Router page conventions.** `metadata` is `export const` for static pages. All metadata blocks include `alternates.canonical: \`${BASE_URL}/<route>\`` plus `openGraph.{title,description,url,siteName,type}`; `twitter` block when shareable. Route uses `<BreadcrumbSchema>` + `<PageHeader>` + content wrapper (`<div className="container mx-auto py-8 px-4">` then `<div className="max-w-4xl mx-auto">`).
- **Sitemap registration.** `app/sitemap.ts:25-52` enumerates static pages explicitly. The new `/authors/pitchrank-team` is NOT auto-included — it must be added to the `staticPages` array.
- **No tests for any schema component today.** `lib/schema-utils.test.ts` is the only test in the JSON-LD area. This plan adds a vitest test for `MethodologySchema` (Step 8) to set the precedent — the test is small (~30 lines) and the entity-URL contract is load-bearing for SEO, so it earns the precedent rather than deferring it.
- **No existing `/authors/` route or links.** The route is genuinely greenfield — no Footer link, no Navigation link, no other JSON-LD reference. Only consumers of the new entity URL will be the JSON-LD `@id` references this plan introduces (BlogPostSchema, MethodologySchema, the author-page Organization itself) plus the sitemap addition.

### Proposed Alignment

Follow existing patterns exactly. New `MethodologySchema.tsx` mirrors `BlogPostSchema.tsx`'s prop-based shape (because dates need to bump without component edits), but emits a single `Article` schema with `Organization` author from `PITCHRANK_TEAM_AUTHOR`. New `app/authors/pitchrank-team/page.tsx` mirrors `app/methodology/page.tsx`'s static-page shape (export `metadata` + default page renders `BreadcrumbSchema` + `PageHeader` + content), including the single-item breadcrumb pattern methodology uses. Constants go in a new `// --- Brand / Author ---` section in `lib/constants.ts` next to `BASE_URL` with JSDoc + `as const`. The new `@id` at top level of the author entity is a deliberate new convention extending the existing `mainEntityOfPage.@id` usage. Add `/authors/pitchrank-team` to `app/sitemap.ts` `staticPages` array. Ship a vitest test for `MethodologySchema` to set the schema-component test precedent. **OG `authors` at `app/blog/[slug]/page.tsx:51` stays unchanged** — the spec explicitly preserves OG metadata in this iteration; any upgrade is out of scope.

## Implementation Steps

1. **Add `PITCHRANK_SAMEAS` + `PITCHRANK_TEAM_AUTHOR` constants to `frontend/lib/constants.ts`**
   - Add a new section banner `// --- Brand / Author ---` near `BASE_URL` (line 61).
   - Export `PITCHRANK_SAMEAS` as `as const` array of the four social URLs that currently live at `StructuredData.tsx:17-22`: `https://twitter.com/pitchrank`, `https://instagram.com/pitchrank`, `https://facebook.com/pitchrank`, `https://linkedin.com/company/pitchrank`.
   - Export `PITCHRANK_TEAM_AUTHOR` as a typed object literal: `@type: 'Organization'`, `@id: \`${BASE_URL}/authors/pitchrank-team\``, `name: 'PitchRank Team'`, `url: \`${BASE_URL}/authors/pitchrank-team\``, `sameAs: PITCHRANK_SAMEAS`.
   - JSDoc precede each export per the convention used by other constants in this file.

2. **Refactor `frontend/components/StructuredData.tsx` to consume `PITCHRANK_SAMEAS`**
   - Replace the inline `sameAs` array literal at lines 17-22 with `sameAs: PITCHRANK_SAMEAS` (spread-from-constant if `as const` requires it; cast to mutable string array if Schema.org typing rejects readonly).
   - Add the import at the top: `import { PITCHRANK_SAMEAS } from '@/lib/constants';`.
   - Verify the homepage Organization schema still emits identical content (Rich Results Test or `next dev` view-source).

3. **Update `frontend/components/BlogPostSchema.tsx` to emit `Organization` author**
   - Import `PITCHRANK_TEAM_AUTHOR` from `@/lib/constants`.
   - Replace the current `author: { '@type': 'Person', name: author }` (lines 50-53) with `author: PITCHRANK_TEAM_AUTHOR`.
   - Keep the `author: string` prop (still feeds the visible byline at the call site `app/blog/[slug]/page.tsx:104` and OG metadata at `:51`).
   - Confirm the `BlogPosting` schema still validates by re-reading the assembled object; the `Organization` shape with `@id`/`name`/`url`/`sameAs` is a valid `BlogPosting.author` value.

4. **Build the `/authors/pitchrank-team` page route**
   - New file: `frontend/app/authors/pitchrank-team/page.tsx`.
   - Mirror `app/methodology/page.tsx` shape: `export const metadata: Metadata = {...}` with `title`, `description`, `alternates.canonical: \`${BASE_URL}/authors/pitchrank-team\``, `openGraph` (title/description/url/siteName/type='website'), `twitter` block.
   - Default-export server component renders `<BreadcrumbSchema items={[{ name: 'PitchRank Team', href: '/authors/pitchrank-team' }]} />` (single-item, mirroring `app/methodology/page.tsx:41` rather than inventing a non-existent parent route), `<PageHeader title="PitchRank Team" description="..." showBackButton backHref="/" />`, and a `max-w-4xl` content wrapper with ~150 words about the team. No "Glicko-2" by name; use "rating engine" / "rating algorithm" per `feedback_no_glicko_in_content.md`. No "cohort"; use "group" per `feedback_group_not_cohort.md`.
   - Embed `<script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(PITCHRANK_TEAM_AUTHOR) }} />` for the entity's own Organization schema (so the `@id` URL has a self-referential JSON-LD block when crawlers fetch the page).

5a. **Build new `MethodologySchema` component**
   - New file: `frontend/components/MethodologySchema.tsx`.
   - Server component (no `'use client'`).
   - Prop shape: `interface MethodologySchemaProps { datePublished: string; dateModified: string; }`.
   - Imports: `BASE_URL`, `PITCHRANK_TEAM_AUTHOR` from `@/lib/constants`; `safeJsonLd` from `@/lib/schema-utils`.
   - Emits a single `<script type="application/ld+json">` with `Article` schema: `@type: 'Article'`, `headline`, `description`, `url: \`${BASE_URL}/methodology\``, `datePublished`, `dateModified`, `author: PITCHRANK_TEAM_AUTHOR`, `publisher` matching `BlogPostSchema.tsx:54-61` (Organization "PitchRank" with logo `${BASE_URL}/logos/pitchrank-wordmark.svg`), `mainEntityOfPage: { '@type': 'WebPage', '@id': \`${BASE_URL}/methodology\` }`.
   - Named export + default re-export per `BlogPostSchema.tsx:79` convention.

5b. **Wire `MethodologySchema` into `frontend/app/methodology/page.tsx`**
   - Render `<MethodologySchema datePublished="2026-04-30" dateModified="2026-04-30" />` alongside the existing `<BreadcrumbSchema>` (around line 41).
   - **No visible byline added** per spec (`/methodology` follows the `/rankings/*` data-display rule).

6. **Normalize TSX outlier author at `frontend/content/blog-posts.tsx:2885`**
   - Change `author: 'PitchRank',` to `author: 'PitchRank Team',` (one-character change; brings the `what-is-powerscore-youth-soccer` post in line with all other 22 posts).

7. **Register `/authors/pitchrank-team` in the sitemap**
   - In `frontend/app/sitemap.ts:25-52`, add `{ url: \`${baseUrl}/authors/pitchrank-team\`, lastModified: new Date(), changeFrequency: 'monthly' as const, priority: 0.4 }` to the `staticPages` array (priority lower than methodology since this is a thinner entity page).

8. **Vitest test for `MethodologySchema`**
   - New file: `frontend/components/MethodologySchema.test.tsx` (or `.test.ts`).
   - Render the component with a known prop pair, parse the `<script>` body, assert: `@type === 'Article'`, `author['@id']` matches `${BASE_URL}/authors/pitchrank-team`, `datePublished` and `dateModified` match the props, `publisher.name === 'PitchRank'`. Sets the precedent for schema-component testing.

## Verification

- **TypeScript build**: `cd C:/PitchRank/frontend && npx tsc --noEmit` exits 0. Catches type drift in `BlogPostSchema` author shape and `MethodologySchema` props.
- **Next.js build**: `cd C:/PitchRank/frontend && npx next build` exits 0. Catches App Router config errors on the new route.
- **Vitest**: `cd C:/PitchRank/frontend && npx vitest run lib/schema-utils.test.ts components/MethodologySchema.test.tsx`. Both targets must pass — the second is required, not optional, per Step 8.
- **Schema validation manual smoke**:
  1. Run `npm run dev` (or `next dev`) locally.
  2. View source on `http://localhost:3000/blog/arizona-youth-soccer-rankings-guide` — confirm `<script type="application/ld+json">` contains `"author":{"@type":"Organization","@id":"https://www.pitchrank.io/authors/pitchrank-team","name":"PitchRank Team","url":"https://www.pitchrank.io/authors/pitchrank-team","sameAs":[...]}`.
  3. View source on `/methodology` — confirm new `Article` schema present with `author` matching above and `datePublished`/`dateModified` both `'2026-04-30'`.
  4. View source on `/authors/pitchrank-team` — confirm `Organization` self-schema present with the same `@id`.
  5. View source on `/` — confirm sitewide `Organization` (`name: 'PitchRank'`) still emits with the four `sameAs` URLs.
  6. Paste each schema into https://search.google.com/test/rich-results — all four pass without errors. Spot-check that `@id` cross-references resolve cleanly.
- **Sitemap**: `curl http://localhost:3000/sitemap.xml | grep authors/pitchrank-team` returns the new URL.
- **Edge cases**:
  - Run `grep -rn "Glicko" frontend/app/authors/` — must return zero hits (R11 enforcement on new content).
  - Run `grep -rn "cohort" frontend/app/authors/ frontend/components/MethodologySchema.tsx` — must return zero hits.
  - Confirm `frontend/content/blog-posts.tsx:2885` now shows `author: 'PitchRank Team',` and grep `grep -n "author: 'PitchRank'" frontend/content/blog-posts.tsx` returns zero hits.
  - Confirm `app/blog/[slug]/page.tsx:104` byline still renders unchanged (`<span>{post.author}</span>`); no functional change to visible bylines.

## Context Files

- `frontend/components/StructuredData.tsx` — sitewide Organization JSON-LD; sameAs array refactor anchor (lines 17-22)
- `frontend/components/BlogPostSchema.tsx` — author block to convert from Person to Organization (lines 50-53); publisher pattern to mirror in MethodologySchema (lines 54-61)
- `frontend/components/FAQSchema.tsx` — sample static-content schema component shape; reference for component file layout
- `frontend/components/BreadcrumbSchema.tsx` — breadcrumb pattern + named-and-default-export convention to mirror
- `frontend/lib/constants.ts` — section organization (banners + JSDoc + `as const` / `Record<>`); BASE_URL anchor (line 61)
- `frontend/lib/schema-utils.ts` — `safeJsonLd` usage pattern and contract
- `frontend/lib/schema-utils.test.ts` — vitest precedent for any new schema test
- `frontend/app/methodology/page.tsx` — static page shape to mirror for `/authors/pitchrank-team` route
- `frontend/app/blog/[slug]/page.tsx` — OG `authors` upgrade site (line 51); visible byline preservation context (line 104)
- `frontend/app/layout.tsx` — Metadata `Author` object form precedent (line 61)
- `frontend/app/sitemap.ts` — staticPages array (lines 25-52) where `/authors/pitchrank-team` registers
- `frontend/content/blog-posts.tsx` — outlier author normalization site (line 2885)
- `.turbo/specs/geo-week5-foundations.md` — source spec; covers R1, R2, R3, R5, R6 in this plan
