# Infographic Redesign — Design Spec

**Date:** 2026-06-03
**Status:** Approved (hero prototype signed off); ready for implementation plan
**Branch:** `redesign/infographics`

## Goal

The three `@vercel/og` social infographics that the Postiz pipeline drafts
(`/api/infographic/{movers,spotlight,state}`) look bland and "pasted": a flat dark
gradient, a logo PNG with a baked-in green box that reads like a sticker, harsh
`#FFD700` gold, Top-5 only, a 0–1 PowerScore ("0.8"), and no W-L-D.

A much better design already exists in the codebase — `frontend/components/infographics/`
(`canvasRenderer.ts` / `Top10Infographic.tsx`) — but it renders to a **client-side
canvas**, which the Postiz pipeline can't fetch as a URL. So the pipeline fell back to
the bland og routes.

**This redesign ports that good canvas design language onto the og routes** (the path
Postiz uses), so we keep server-side edge rendering + CDN caching + the 0-byte smoke
test, and get the polished look. A hero prototype (state Top-10) was rendered and
approved.

## Visual system (shared `_shared/`)

Factor the design into one place so all three graphics share it and a change is one edit.

- **`theme.ts`** — design tokens:
  - Colors: `forestGreen #0B5345`, `darkGreen #052E27`, `electricYellow #F4D03F`,
    `brightWhite #FDFEFE`, plus muted greens for date/club/labels and a row divider.
    (Adopt the canvas palette; retire the og routes' `#1B4D3E`/`#FFD700`.)
  - Fonts: Oswald (display: logo title, rank numbers, team names) / DM Sans (body).
  - Spacing, radii, platform dimensions (instagram 1080², story 1080×1920, twitter 1200×675).
- **`<Frame>`** — gradient background + subtle scan-line texture (faint ~2% white lines
  for depth) + the divider-line footer (`pitchrank.io/rankings`). Texture must be
  Satori-safe (validate; drop if it breaks rendering).
- **`<Header>`** — integrated logo + title + date line.
- **`<RankRow>`** — the medal row (rank #, team name, club, right-side stats); top-3 get
  gold/silver/bronze left border + tint.
- **`assets.ts`** — keep `loadBrandFonts` + add the transparent logo URL.

All multi-child `<div>`s set `display:flex`; all numeric/interpolated children are single
string children (template literals) — the Satori 0-byte rules from PR #862 still apply.

## Logo (de-stickered, same asset)

The "sticker" is a solid `#052E27`-ish box baked into `logo-primary.png`. Fix: ship a
**transparent wordmark** — `logo-primary.png` run through GIMP-style color-to-alpha
(key `(5,46,39)`), producing `frontend/public/logos/logo-wordmark.png` (white PITCH +
yellow RANK, no box). The og routes use that asset, sized to the header and sitting
directly on the gradient. (Generation is a one-time asset build; the PNG is committed.)

## The three graphics

All share `<Frame>`/`<Header>` (logo + title + "Rankings as of {date}").

- **State (hero — prototyped & approved):** `TOP 10 {U14 BOYS} IN {STATE}`, 10 `<RankRow>`s:
  rank #, **TEAM NAME** (Oswald, uppercase), club, right side **W-L-D** + **SCORE**
  (`power_score_final × 100`, **2 decimals**, e.g. `71.67`). Data via `get_state_rankings`,
  Active-ranked only, deep-state + weekly cohort rotation unchanged.
- **Movers:** same chrome; two sections (Climbers / Fallers) of `<RankRow>`s showing the
  `+N / −N` rank change instead of SCORE. Data via `get_biggest_movers` (unchanged).
- **Spotlight (team of the week):** same chrome; single featured team — rank badge, team
  name, club, record, and the ×100 2-decimal score. Data via `get_biggest_movers` (limit 1).

## Score + data

- **SCORE = `power_score_final × 100`, `.toFixed(2)`** → `71.67` (0–100 scale, 2 decimals).
- **W-L-D** from `total_wins/losses/draws ?? wins/losses/draws` (both RPCs return them).
- Null-safety: nullable text joined from non-null parts (PR #862 fix) carried into `<RankRow>`.

## Preserved / unchanged

Edge runtime, `Cache-Control` CDN caching, the 0-byte smoke test + workflow, the
ranked-only + deep-state spotlight guards, and the weekly cohort rotation in
`marketing_pipeline.py`.

## Open refinements (confirm in review)

- **Scan-line texture:** include (subtle) vs omit. Default: include if Satori-safe.
- **Club line:** show club only (state is already in the title) vs append `| ST` to match
  the old reference exactly. Default: club only.

## Out of scope

- The existing client-side canvas infographic system (`components/infographics/`) stays as
  the in-app generator; this work only touches the og/Postiz routes. (A later unification
  could share `theme.ts`, but not now.)
- No PowerScore tier thresholds or "Glicko" naming in the public graphic.

## Verification

- Render all three routes locally (instagram + story) across several states/cohorts incl.
  small-data edge cases; confirm non-empty PNGs and correct logo/score/record.
- `tsc --noEmit`, ruff, and the existing 0-byte smoke test stay green.
- Re-run `marketing_pipeline.py --postiz-only` (drafts) as the end-to-end check.
