---
spec: .turbo/specs/geo-week5-foundations.md
depends_on: [geo-week5-foundations-01-author-entity, geo-week5-foundations-02-datemodified-backfill]
---

# Plan: llms.txt generator + CI drift check + cross-cutting verification

## Context

`llms.txt` is a 2024-era proposal (~800 sites adopted as of mid-2025) where sites publish a markdown index of their best content for LLMs to discover. PitchRank's existing `frontend/public/llms.txt` is a 16-line stub listing 3 pages — far too thin to act as a real content map. This shell replaces it with a TypeScript generator script that emits a structured map of all PitchRank content (blog posts, state pillars, methodology, about), executed via `tsx` (already in `frontend/package.json:85`).

The generator must reuse the same content sources the live site uses: `frontend/lib/blog.tsx::getAllBlogPosts()` for the merged MDX + TSX blog set, and `frontend/lib/cohort-seo.ts::STATE_PILLAR_SLUGS` for the canonical state-pillar list. Today `STATE_PILLAR_SLUGS` is module-private (`const`, line 112) — the export change is part of this shell. The generator de-duplicates: state pillars appear only in the State Pillars section, never in Blog (the Blog section emits the 10 non-pillar posts; State Pillars emits the 13 pillar entries).

To prevent drift, a CI step runs the generator and `git diff --exit-code public/llms.txt`. If a content PR doesn't regenerate the file, CI fails. The generator hard-fails (non-zero exit) on parse errors instead of silently emitting partial output — silent partial output is worse than failure for AI-engine discovery.

This shell also serves as the cross-cutting verification gate for the whole PR. By the time it ships:
- All schemas introduced in Shell 1 must validate at https://search.google.com/test/rich-results (R9)
- All new user-facing content (this shell + Shells 1-2) must be free of "Glicko-2" and "cohort" per `feedback_no_glicko_in_content.md` and `feedback_group_not_cohort.md` (R11)
- `tsc --noEmit` and `next build` must pass; CI green on PR (R12)

This shell is independent of Shells 1 and 2 — no shared file edits except for `frontend/CLAUDE.md` (R8b in this shell, R8a in Shell 2). Two diffs in different sections of the same file; coordinate to avoid conflicts.

## Produces

- New `frontend/scripts/generate-llms-txt.ts` script — generates `public/llms.txt` from the merged blog-post set + STATE_PILLAR_SLUGS, fails closed on parse errors
- `STATE_PILLAR_SLUGS` exported (changed from `const` to `export const` in `frontend/lib/cohort-seo.ts:112`)
- Regenerated `frontend/public/llms.txt` containing: site description, Core Content section, Blog section (10 non-pillar posts), State Pillars section (13 pillars), About section
- npm script in `frontend/package.json`: `"generate-llms": "tsx scripts/generate-llms-txt.ts > public/llms.txt"`
- New CI workflow step (added to an existing `.github/workflows/*.yml` such as the frontend lint/build workflow) — runs the generator and `git diff --exit-code public/llms.txt`, failing the build when stale
- `frontend/CLAUDE.md` documents the regeneration command and when to run it (R8b)

## Consumes

From Shell 1 (`geo-week5-foundations-01-author-entity`):
- `/authors/pitchrank-team` route — referenced as a URL in the llms.txt About section
- `MethodologySchema` component on `/methodology` — exercised by R9 validator pass
- Updated `BlogPostSchema` (Organization author shape) — exercised by R9 validator pass
- New user-facing content (author page text, methodology schema) — exercised by R11 content audit

From Shell 2 (`geo-week5-foundations-02-datemodified-backfill`):
- `frontend/CLAUDE.md` (R8a section already added) — Shell 3 appends R8b in a different section
- New user-facing content (CLAUDE.md convention text, MDX/TSX `modifiedDate` values) — exercised by R11 content audit

From existing codebase:
- `frontend/lib/blog.tsx::getAllBlogPosts()` (the merged MDX + TSX loader)
- `frontend/lib/cohort-seo.ts::STATE_PILLAR_SLUGS` (with the `export` change made in this shell)
- `frontend/package.json` `tsx ^4.21.0` devDependency at line 85
- Existing `frontend/public/llms.txt` (replaced)
- Existing CI workflow file structure under `.github/workflows/`

## Covers Spec Requirements

- R7
- R8b
- R9
- R10
- R11
- R12

## Implementation Steps (High-Level)

1. **Export `STATE_PILLAR_SLUGS` from `frontend/lib/cohort-seo.ts`**
   - Change line 112 declaration from `const STATE_PILLAR_SLUGS` to `export const STATE_PILLAR_SLUGS`
   - No other consumer needs the symbol today; this enables the generator import
2. **Build `frontend/scripts/generate-llms-txt.ts`**
   - Imports `getAllBlogPosts` from `@/lib/blog` and `STATE_PILLAR_SLUGS` from `@/lib/cohort-seo`
   - Computes the pillar slug set (`Object.values(STATE_PILLAR_SLUGS).map(p => p.slug)`)
   - Partitions all blog posts into pillars and non-pillars
   - Emits markdown sections: site description (preserved from current file's intro tone), `## Core Content` (methodology + curated top ranking pages), `## Blog` (10 non-pillar posts with titles + excerpts; intro line: "*State-specific guides are listed under State Pillars below.*"), `## State Pillars` (13 pillar pages grouped/ordered as decided at expand-shell), `## About` (`/`, `/authors/pitchrank-team`)
   - Hard-fails (non-zero exit) on any parse error or missing source — no silent partial output
3. **Add npm script to `frontend/package.json`**
   - `"generate-llms": "tsx scripts/generate-llms-txt.ts > public/llms.txt"`
4. **Regenerate `frontend/public/llms.txt`**
   - Run the generator and commit its output
   - Verify the output dedup rule: every slug in `STATE_PILLAR_SLUGS` appears in State Pillars and not in Blog
5. **Add CI drift check workflow step**
   - In an existing frontend CI workflow, add a step that runs `npm run generate-llms` then `git diff --exit-code public/llms.txt`
   - Fail the build if the committed `llms.txt` is stale relative to current content sources
6. **Document the regeneration command in `frontend/CLAUDE.md` (R8b)**
   - Add a section: "Run `npx tsx scripts/generate-llms-txt.ts > public/llms.txt` after blog or state-pillar changes"
   - Coordinate with Shell 2's R8a addition (different section of the same file)
7. **Cross-cutting verification (R9, R11, R12)**
   - **R9:** validate every JSON-LD schema introduced or modified in this PR at https://search.google.com/test/rich-results — sample a blog post, the methodology page, and the new author page
   - **R11:** grep all changes for `Glicko-2` and `cohort` in user-facing strings; remove or rephrase per `feedback_no_glicko_in_content.md` (use "rating engine") and `feedback_group_not_cohort.md` (use "group")
   - **R12:** run `tsc --noEmit` and `next build` locally; ensure CI is green on the PR

## Open Questions

None.

## Expansion Deferred

The following are filled in when `/expand-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path` references with named functions or symbols for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
- Final selection of the existing `.github/workflows/*.yml` file to extend with the drift check
- Curated top-N ranking pages list for the Core Content section (driven by SEO strategy at expansion time)
