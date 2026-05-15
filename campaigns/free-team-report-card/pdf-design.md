# Team Report Card — PDF Design Brief

**Status:** PR 3 — implementing now
**Reference:** `frontend/components/ReportCardPreview.tsx` (the HTML mock from PR 2)
**Source PDF:** `frontend/lib/pdf/TeamReportCard.tsx`

## Goals

1. **Sharper hierarchy.** The current PDF treats National Rank, State Rank, PowerScore, Offense, Defense, SoS, W/L/D, and the career line as roughly equal visual weight. The one number a parent actually wants to see — **PowerScore + National Rank** — should dominate the top of the page, baseball-card style.
2. **Add a Last 5 form strip.** Five colored circles (W=green, L=red, D=gray) replace the tiny "▲12 30d" microtext. This is the single most-scannable bit of season summary; the HTML mock landing page already promises it.
3. **Strip stale stats and internal naming.** Footer currently reads "13-layer algorithm · 25,000+ teams" — both violate brand voice rules and contradict the landing page (1.1M+ games · 126K+ teams). Replace.
4. **Tighten copy.** Generic "WANT THE FULL PICTURE?" CTA → loss-framed match to the upgrade-page voice ("Don't make a $10K club decision on a hunch.").

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
│  14-2-3   .763         │  [W][W][L][W][W]              │ ← colored circles
└────────────────────────┴──────────────────────────────┘
─── divider ────────────────────────────────────────────
STRENGTH PROFILE
Offense   [bar=====       ]   0.71
Defense   [bar========    ]   0.82
Schedule  [bar=====       ]   0.68
─── divider ────────────────────────────────────────────
RECENT RESULTS
Nov 9    Tucson Soccer Academy 14B          3-1   [W]
Nov 2    AZ Arsenal SC ECNL                 2-2   [D]
Oct 26   SC del Sol Premier                 4-0   [W]
... (up to 5)
─── divider ────────────────────────────────────────────
┌───────────────────────────────────────────────────────┐
│  [forest green CTA box]                                │
│  DON'T MAKE A $10K CLUB DECISION ON A HUNCH.           │
│  PitchRank+ unlocks: team comparisons · AI insights ·  │
│  weekly rank alerts · matchup predictions.             │
│  [yellow button: START FREE 7-DAY TRIAL]               │
│  7 days free · $6.99/mo · Cancel anytime               │
└───────────────────────────────────────────────────────┘
┌───────────────────────────────────────────────────────┐
│  Powered by PitchRank · 1.1M+ games · Weekly updates   │ ← footer
│                                          pitchrank.io  │
└───────────────────────────────────────────────────────┘
```

## What's removed

- Career-record sub-line (`Career: 23-7-4 (34 games)`) — too granular for a one-page summary; if we keep it, demote to a tiny right-aligned caption under Record
- Form indicator (▲ Overperforming / ▼ Underperforming) — replaced by the Last 5 strip which is more honest and intuitive
- "13-layer algorithm" mention anywhere
- "25,000+ teams" — bumped to 1.1M+ games

## What's kept

- Brand fonts (Oswald + DM Sans) and colors (forest green `#0B5345`, electric yellow `#F4D03F`)
- Strength Profile bars (Offense / Defense / Schedule)
- Recent Results table with result badges
- Premium CTA box with clickable upgrade link
- Footer with site URL
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
