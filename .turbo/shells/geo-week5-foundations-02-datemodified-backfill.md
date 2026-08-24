---
spec: .turbo/specs/geo-week5-foundations.md
depends_on: []
---

# Plan: dateModified backfill + bump-on-edit convention

## Context

The Princeton GEO paper measured a 3× citation rate for content edited within ~60 days. PitchRank's existing `BlogPostSchema` falls back to `datePublished` when `modifiedDate` is missing (`frontend/components/BlogPostSchema.tsx:49`: `dateModified: modifiedDate || date`). Today, no blog post passes a `modifiedDate` value through the pipeline, so every post is treated as never-updated by AI engines, killing the recency lift.

This shell backfills `modifiedDate` on all 23 existing blog posts (16 MDX in `frontend/content/blog/` + 7 TSX in `frontend/content/blog-posts.tsx`) to `'2026-04-30'` as a one-time clean reset. Going forward, the convention is documented in `frontend/CLAUDE.md`: every blog post edit must bump `modifiedDate` to the current date. No automated enforcement (lint rule or pre-commit hook) — convention checked at PR review.

The `BlogPostSchema` component already accepts `modifiedDate?: string` as a prop end-to-end (lines 13/31/49), so this shell does not edit the schema component itself. The wiring needed is upstream: add `modifiedDate?: string` to the `BlogPost` interface in `frontend/lib/blog.tsx`, surface it through `parseMarkdownFile`, populate it on TSX `BlogPost` objects, and pass `modifiedDate={post.modifiedDate}` at the call site in `frontend/app/blog/[slug]/page.tsx`. Note: Shell 1 separately edits `BlogPostSchema.tsx` lines 50-53 (author shape change from `Person` to `Organization`); Shells 1 and 2 are textually independent within this file.

This shell is independent of Shells 1 and 3 — no shared file edits except for `frontend/CLAUDE.md` (which Shell 3 also touches in a different section, R8b vs R8a). Coordinate the diffs to avoid trivial conflicts.

## Produces

- `BlogPost` interface extended with `modifiedDate?: string` field in `frontend/lib/blog.tsx`
- `parseMarkdownFile` surfaces `data.modifiedDate` on the returned object
- All 16 MDX blog posts in `frontend/content/blog/` carry `modifiedDate: '2026-04-30'` in frontmatter
- All 7 TSX `BlogPost` objects in `frontend/content/blog-posts.tsx` carry `modifiedDate: '2026-04-30'`
- `frontend/app/blog/[slug]/page.tsx` passes `modifiedDate={post.modifiedDate}` to `BlogPostSchema`
- `frontend/CLAUDE.md` documents the bump-on-edit convention (R8a)

## Consumes

- Existing `BlogPostSchema` component already accepts `modifiedDate?: string` prop (no edits needed) — from existing codebase
- Existing `parseMarkdownFile` (lines 23-39) and `getAllBlogPosts` (lines 60-63) in `frontend/lib/blog.tsx` — from existing codebase
- Existing 16 MDX files in `frontend/content/blog/` — from existing codebase
- Existing 7 TSX `BlogPost` objects in `frontend/content/blog-posts.tsx` (lines 33, 423, 908, 1200, 1876, 2570, 2885) — from existing codebase
- Existing `frontend/app/blog/[slug]/page.tsx` rendering `BlogPostSchema` — from existing codebase
- `gray-matter` already imported by `lib/blog.tsx:3` — from existing codebase

## Covers Spec Requirements

- R4
- R8a

## Implementation Steps (High-Level)

1. **Add `modifiedDate?: string` to the `BlogPost` interface**
   - In `frontend/lib/blog.tsx` lines 6-16, add the optional field
2. **Surface `data.modifiedDate` in `parseMarkdownFile`**
   - In `frontend/lib/blog.tsx` lines 23-39, add `modifiedDate: data.modifiedDate` to the returned object
3. **Backfill MDX frontmatter**
   - For each of the 16 `.mdx` files in `frontend/content/blog/`, add `modifiedDate: '2026-04-30'` to the YAML frontmatter
4. **Backfill TSX BlogPost objects**
   - For each of the 7 entries in `frontend/content/blog-posts.tsx` (at lines 33, 423, 908, 1200, 1876, 2570, 2885), add `modifiedDate: '2026-04-30'` property
5. **Wire `modifiedDate` at the blog post page call site**
   - In `frontend/app/blog/[slug]/page.tsx` (around the `<BlogPostSchema>` call), pass `modifiedDate={post.modifiedDate}` prop
6. **Document the bump-on-edit convention in `frontend/CLAUDE.md`**
   - Add a section explaining: every blog post edit (MDX or TSX) must bump `modifiedDate` to the current date in YYYY-MM-DD format
   - Note that this is checked at PR review (no automated enforcement)
   - Coordinate with Shell 3's R8b addition to the same file (different section)

## Open Questions

None.

## Expansion Deferred

The following are filled in when `/expand-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path` references with named functions or symbols for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
