# Team Report Card — PDF Design Brief

**Status:** PR 3 — implementing now
**Reference:** `frontend/components/ReportCardPreview.tsx` (the HTML mock from PR 2)
**Source PDF:** `frontend/lib/pdf/TeamReportCard.tsx`

## Goals

The PDF is a **lead magnet**, not a deliverable. Give the parent just enough to (a) trust the data is real and (b) feel they got fair value for the email, while leaving the *interpretation* — the part premium answers — visibly locked.

1. **Sharper hierarchy.** PowerScore + National Rank dominate the top of the page, baseball-card style. The current PDF gives them equal visual weight to Offense/Defense/SoS/W/L/D, which dilutes the headline.
2. **Add a Last 5 form strip.** Five colored circles (W/L/D shape only, no opponents or scores) — aggregate visual, not detailed per-game data.
3. **Replace data-rich sections with locked previews.** Strength Profile values, full Recent Results, win probability, and 90-day trend chart are all premium-gated features. Show them as locked cards with brief teasers, not actual data.
4. **Strip stale stats and internal naming.** Footer currently reads "13-layer algorithm · 25,000+ teams" — both violate brand voice rules and contradict the landing page (1.1M+ games · 126K+ teams).
5. **Tighten copy.** Generic "WANT THE FULL PICTURE?" CTA → loss-framed match to the upgrade-page voice ("Don't make a $10K club decision on a hunch.").

## Layout (single LETTER page)

```
┌───────────────────────────────────────────────────────┐
│  [forest green strip]                                  │
│  PITCHRANK · TEAM REPORT CARD          [yellow accent] │
└───────────────────────────────────────────────────────┘
┌───────────────────────────────────────────────────────┐
│  Phoenix Rising FC 2014B                               │ ← Oswald 22, forest green
│  FC Tucson · Phoenix, AZ · U12 Boys · 2026 Season      │ ← meta line
└───────────────────────────────────────────────────────┘
┌────────────────────────┬──────────────────────────────┐
│  POWERSCORE            │  NATIONAL RANK                │
│  0.847                 │  #47  ▲12                     │ ← huge Oswald
│  Top 4% nationally     │  #3 in Arizona                │
└────────────────────────┴──────────────────────────────┘
┌────────────────────────┬──────────────────────────────┐
│  RECORD                │  LAST 5                       │
│  14-2-3   .763         │  [W][W][L][W][W]              │ ← shape only
└────────────────────────┴──────────────────────────────┘
─── divider ────────────────────────────────────────────
WHAT'S INSIDE PITCHRANK+ (2×2 locked grid, yellow left-border)
┌──────────────────────────┬──────────────────────────────┐
│  [PREMIUM] RECENT RESULTS│  [PREMIUM] STRENGTH PROFILE  │
│  Every game — opponents, │  Offense, defense, SoS scored│
│  scores, results.        │  against your peer group.    │
│  ▮▮▮▮ ▮▮▮ ▮▮            │  ▮▮▮▮ ▮▮▮ ▮▮                │
├──────────────────────────┼──────────────────────────────┤
│  [PREMIUM] WIN PROBABILITY│ [PREMIUM] 90-DAY RANK TREND │
│  Predictions for next    │  Climbing or sliding —       │
│  opponents + comparisons │  weekly change alerts.       │
│  ▮▮▮▮ ▮▮▮ ▮▮            │  ▮▮▮▮ ▮▮▮ ▮▮                │
└──────────────────────────┴──────────────────────────────┘
┌───────────────────────────────────────────────────────┐
│  [forest green CTA box]                                │
│  DON'T MAKE A $10K CLUB DECISION ON A HUNCH.           │
│  Unlock the four sections above plus team comparisons, │
│  AI Insights, and watchlist alerts.                    │
│  [yellow button: START FREE 7-DAY TRIAL]               │
│  7 days free · $6.99/mo · Cancel anytime               │
└───────────────────────────────────────────────────────┘
┌───────────────────────────────────────────────────────┐
│  Powered by PitchRank · 1.1M+ games · Weekly updates   │ ← footer
│                                          pitchrank.io  │
└───────────────────────────────────────────────────────┘
```

## What's removed from the free PDF

- **Strength Profile bars** with actual values — interpretation of offense/defense/SoS is the premium product. Replaced by a locked card.
- **Full Recent Results table** with opponents, scores, results — game-level data is premium-gated (per `gotcha_team_detail_premium_gated`). Replaced by a locked card.
- Career-record sub-line (`Career: 23-7-4 (34 games)`) — too granular for a one-page summary.
- Form indicator (▲ Overperforming / ▼ Underperforming) — replaced by the Last 5 shape strip.
- "13-layer algorithm" mention anywhere.
- "25,000+ teams" — bumped to 1.1M+ games.

## What's kept (the lead-magnet payload)

- Brand fonts (Oswald + DM Sans) and colors (forest green `#0B5345`, electric yellow `#F4D03F`)
- Team identity block (confirms "your team is real to us")
- PowerScore hero (the one number they came for)
- National + state rank with 30-day delta
- W-L-D record + win rate (aggregate, no per-game leak)
- Last 5 form strip (shape only — W/L/D, no opponents or scores)
- 2×2 locked previews of: Recent Results, Strength Profile, Win Probability, 90-Day Trend
- Premium CTA box backed by the locked items directly above it
- Footer
- LETTER page size, react-pdf renderer

## What's not in scope

- Multi-page reports
- Embedded charts (current PDF has no charts — keep it simple)
- Watermark / signature design
- Team logos (we don't store club crests)

## Acceptance

- The PDF renders without errors via `POST /api/reports/team-card` for a real Arizona U12 Boys team
- Visual matches the HTML mock from PR 2 for the hero (PowerScore + Rank big, then Record + Last 5)
- All stale stats removed, all loss-framed CTA copy in place
- Single page, no overflow
