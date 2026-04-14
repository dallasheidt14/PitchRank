# Rankings Row Interactivity Design

## Problem

Users visit the rankings table, see rank + score, and leave — treating it as a static information display. They don't realize each team row is a gateway to deeper analysis (game history, rank charts, AI insights) and ultimately the premium upgrade flow. The table needs to shift from "here's a list of numbers" to "here's a taste — the good stuff is one click away."

## Goal

Increase click-through rate from rankings table rows to team detail pages by making rows feel like interactive entry points into premium value, without making the table feel pushy or cluttered.

## Scope

Changes are limited to `RankingsTable.tsx` and its row rendering. No changes to the team detail page, upgrade page, or data layer.

## Design

### Full-Row Clickable Link

The entire row becomes an `<a>` tag wrapping the row content, linking to the existing team detail URL:

```
/teams/${team.team_id_master}?region=${region}&ageGroup=${ageGroup}&gender=${gender}
```

Currently only the team name text is a link (an `<a>` tag inside the row). That inner link is removed — the outer row-level `<a>` replaces it. Nested `<a>` tags are invalid HTML so there must be exactly one link element: the row wrapper. The team name retains its visual styling (primary color, hover color shift) but is now a `<span>` instead of an `<a>`.

### New Action Column

A new column is added as the rightmost column in the grid. It contains two elements:

1. **Persistent chevron (›)** — always visible at low opacity (~50% on desktop, ~35% on mobile). Uses `muted` color. Signals "there's more" without being loud.
2. **"View team" microcopy** — desktop only, visible only on hover. Hidden on mobile.

The column is a fixed width (does not flex) to prevent layout shift. Space is always reserved whether the microcopy is visible or not.

### Desktop Hover Interaction

On row hover, the following effects apply simultaneously:

| Effect | Detail | Timing |
|--------|--------|--------|
| Background highlight | Subtle shift to `primary/4%` (or `accent/12%` for top-3 rows) | 200ms ease |
| Box shadow | `0 2px 8px rgba(0,0,0,0.06)` | 200ms ease |
| "View team" fade/slide | Opacity 0→1, translateX 8px→0 | 180ms ease, 100ms delay |
| Chevron brightens | Color shifts from `muted` to `primary`, opacity to 100% | 200ms ease |
| Chevron nudge | translateX 0→2px | 200ms ease |
| Other rows dim | Non-hovered rows drop to 55% opacity | 300ms ease |

The 100ms delay on the microcopy filters out accidental mouse passes and makes the reveal feel intentional.

### Mobile Behavior

- No hover effects (no hover on touch devices)
- Persistent chevron visible at 35% opacity on every row
- "View team" text is hidden (`display: none` on mobile)
- Tap feedback via background color pulse (brief highlight on touch)
- Full row is tappable as a link

### Existing Behavior Preserved

- Top-3 rows keep their 4px gold (`accent`) left border and `accent/5%` background
- Ranks 4-10 keep their 4px `primary/30%` left border
- Rank change indicators (▲/▼) unchanged
- Sort buttons in header unchanged
- Tooltips on PowerScore and SOS unchanged
- Virtual scrolling (TanStack React Virtual) unchanged
- All existing analytics tracking preserved (`trackTeamRowClicked`)

### Accessibility

- Full row is an `<a>` tag, making it keyboard-navigable and screen-reader accessible
- `aria-label` on each row link: "View {team_name} team details"
- Focus-visible ring uses existing `ring-primary` style
- Color contrast ratios maintained (chevron and microcopy meet WCAG AA against white/accent backgrounds)

## Colors

All colors come from the existing PitchRank design tokens. No new colors introduced.

| Element | Token | Value |
|---------|-------|-------|
| Chevron (resting) | `muted` | `oklch(0.5 0.04 163)` / #7D9591 |
| Chevron (hover) | `primary` | `oklch(0.38 0.1 163)` / #0B5345 |
| "View team" text | `primary` | `oklch(0.38 0.1 163)` / #0B5345 |
| Row hover bg | `primary` at 4% | rgba(11, 83, 69, 0.04) |
| Top-3 row hover bg | `accent` at 12% | rgba(244, 208, 63, 0.12) |
| Row shadow (hover) | — | rgba(0,0,0,0.06) |

## Typography

- "View team" microcopy: DM Sans, 500 weight, ~0.72rem
- Chevron: 1rem (desktop), 0.85rem (mobile)

## Files Changed

- `frontend/components/RankingsTable.tsx` — row rendering, grid columns, hover states, link wrapping

## What This Does NOT Include

- No changes to team detail page content or layout
- No changes to upgrade page or paywall logic
- No inline row expansion or teaser data
- No first-visit nudge, tooltip, or banner
- No shimmer animations
- No new analytics events (existing `trackTeamRowClicked` covers the interaction)

## Success Criteria

- Click-through rate from rankings table to team detail pages increases (measurable via existing `trackTeamRowClicked` event)
- No layout shift or visual jank during hover interactions
- Mobile tap target covers entire row
- No regression in virtual scrolling performance
