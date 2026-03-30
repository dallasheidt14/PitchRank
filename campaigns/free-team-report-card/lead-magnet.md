---
title: "Free Team Report Card"
subtitle: "See How Your Team Stacks Up"
format: auto-generated PDF
hook: "Get your team's free season report card — rankings, trends, and insights powered by PitchRank's 13-layer algorithm."
bridge_to: "PitchRank Premium ($6.99/mo or $69.99/yr)"
target_audience: "Parents of competitive youth soccer players (U10-U19)"
estimated_consumption_time: "2 min to read, instant delivery"
status: draft
created_by: /lead-magnet
created_date: 2026-03-29
---

# Free Team Report Card — Full Specification

## Overview

A personalized, auto-generated PDF report card for any team in PitchRank's database (25,000+). Delivered instantly via email after the parent enters their team name, age group, and email address. Designed to be screenshot-worthy and shareable.

---

## Capture Form

### Fields
1. **Team name** (autocomplete search against PitchRank DB)
   - Placeholder: "Start typing your team name..."
   - Shows: team name, club, state, age group in dropdown
2. **Email address**
   - Placeholder: "Where should we send it?"
3. **Optional: Your role** (dropdown)
   - Parent / Coach / Club Director / Other
   - Used for email segmentation, not required

### Form Copy
**Headline:** "Your team's report card is ready."
**Subhead:** "Rankings, trends, and insights — powered by 25K+ teams and a 13-layer algorithm. Free. Delivered in seconds."
**CTA button:** "Send My Report Card"
**Below button:** "Free. No credit card. Unsubscribe anytime."

### Post-Submit
**Confirmation page:** "Check your inbox — your report card is on its way."
**Fallback:** "Don't see it? Check your spam folder or [click here to view online]."

---

## PDF Report Card — Layout Specification

### Page 1: The Report Card

**Design:** Clean, branded. Forest Green (#0B5345) + Electric Yellow (#F4D03F) accent. Oswald headlines, DM Sans body. White background. Feels like a premium sports analytics document.

**Dimensions:** US Letter (8.5" x 11") — also works on mobile as a single scroll.

---

#### HEADER

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  [PitchRank Logo]                                        │
│                                                          │
│  TEAM REPORT CARD                                        │
│  ─────────────────                                       │
│  {Team Name}                                             │
│  {Club Name} · {State} · {Age Group} · {Gender}          │
│                                                          │
│  Generated {Month Day, Year}                             │
│  Data through {last_game_date}                           │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

#### RANKING OVERVIEW (Hero section — biggest visual impact)

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│        NATIONAL RANK          STATE RANK                 │
│        ┌──────────┐          ┌──────────┐               │
│        │          │          │          │               │
│        │   #47    │          │   #12    │               │
│        │          │          │          │               │
│        └──────────┘          └──────────┘               │
│        of {N} teams           of {N} in {State}          │
│        {▲3 7d} {▲8 30d}      {▲1 7d} {▲4 30d}          │
│                                                          │
│        POWERSCORE                                        │
│        ┌──────────────────────────────────┐              │
│        │ ████████████████░░░░  0.72       │              │
│        └──────────────────────────────────┘              │
│        Top {percentile}% nationally                      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Data fields used:**
- `rank_in_cohort_final` (national rank)
- `rank_in_state_final` (state rank)
- `power_score_final` (PowerScore, displayed as 0.00-1.00)
- `rank_change_7d`, `rank_change_30d` (trend arrows)
- `rank_change_state_7d`, `rank_change_state_30d`
- Total teams in cohort (for "of N teams")
- Percentile calculation: `(1 - rank/total) × 100`

**Design notes:**
- Rank numbers are LARGE (48pt+ Oswald). This is the hero.
- Green arrows (▲) for rank improvements, red (▼) for drops
- PowerScore bar is Forest Green fill on gray background
- Percentile text: "Top 15% nationally" — this is the bragging stat

---

#### STRENGTH PROFILE (3-bar visual)

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  STRENGTH PROFILE                                        │
│                                                          │
│  Offense     ██████████████░░░░░░  0.71                  │
│  Defense     ████████████████░░░░  0.82                  │
│  Schedule    ██████████░░░░░░░░░░  0.54                  │
│                                                          │
│  Your team plays a harder schedule than {SOS_pct}%       │
│  of teams in your age group.                             │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Data fields used:**
- `off_norm` (offensive strength, 0-1)
- `def_norm` (defensive strength, 0-1)
- `sos_norm` (strength of schedule, 0-1)
- `sos_rank_national` (for percentile calculation)

**Design notes:**
- Bars are horizontal, filled proportionally
- Color: Forest Green for all bars, Electric Yellow for the highest bar
- SOS context sentence makes the number meaningful

---

#### SEASON RECORD

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  SEASON RECORD                                           │
│                                                          │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐       │
│  │  {GP}  │  │  {W}   │  │  {L}   │  │  {D}   │       │
│  │ Games  │  │  Wins  │  │ Losses │  │ Draws  │       │
│  └────────┘  └────────┘  └────────┘  └────────┘       │
│                                                          │
│  Win Rate: {win_pct}%                                    │
│  Career Record: {total_W}-{total_L}-{total_D}            │
│                                                          │
│  Form: {perf_centered indicator}                         │
│  {▲ Overperforming / ● On Track / ▼ Underperforming}    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Data fields used:**
- `games_played`, `wins`, `losses`, `draws` (30-day window)
- `win_percentage`
- `total_games_played`, `total_wins`, `total_losses`, `total_draws`
- `perf_centered` (form indicator: positive = overperforming)

**Design notes:**
- 4 big number boxes in a row
- Win rate as a bold percentage
- Form indicator uses color: green (overperforming), gray (on track), red (underperforming)

---

#### RECENT RESULTS (Last 5 games)

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  RECENT RESULTS                                          │
│                                                          │
│  {Date}  vs {Opponent}           {Score}  {W/L/D}       │
│  {Date}  vs {Opponent}           {Score}  {W/L/D}       │
│  {Date}  vs {Opponent}           {Score}  {W/L/D}       │
│  {Date}  vs {Opponent}           {Score}  {W/L/D}       │
│  {Date}  vs {Opponent}           {Score}  {W/L/D}       │
│                                                          │
│  ── See all {N} games at pitchrank.io/{team_slug} ──    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Data fields used:**
- Last 5 entries from `getTeamGames()` API
- `game_date`, opponent `team_name`, `home_score`/`away_score`, result (W/L/D)
- `competition` or `division_name` (shown as small text under opponent if space allows)

**Design notes:**
- W = green badge, L = red badge, D = gray badge
- Opponent names truncated if too long
- Link to full game list drives traffic to the site

---

#### PREMIUM TEASER (Bridge to paid)

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  WANT THE FULL PICTURE?                    [PitchRank]   │
│                                                          │
│  Your free report card shows the highlights.             │
│  Premium shows you everything:                           │
│                                                          │
│  ✓ Head-to-head team comparisons                        │
│  ✓ Predictive matchup analytics                         │
│  ✓ 90-day ranking trend charts                          │
│  ✓ Strength of schedule deep-dives                      │
│  ✓ Weekly ranking alerts for your team                  │
│  ✓ Club comparison tools                                │
│                                                          │
│  ┌──────────────────────────────────────────┐           │
│  │   Start Your Free Trial → pitchrank.io   │           │
│  └──────────────────────────────────────────┘           │
│                                                          │
│  7 days free · $6.99/mo · Cancel anytime                │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Design notes:**
- This is a soft pitch, not a hard sell
- Forest Green background with white text for the CTA section
- Electric Yellow CTA button
- "7 days free" is the key reassurance
- Keep it to 1/4 of the page max — this is a lead magnet, not a sales page

---

#### FOOTER

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  Rankings powered by PitchRank's 13-layer algorithm      │
│  25,000+ teams · Updated weekly · pitchrank.io           │
│                                                          │
│  Data through {last_calculated_date}                     │
│  © 2026 PitchRank. All rights reserved.                  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## Delivery Email

**Subject line variants:**

① "Your team's report card is inside"                    ★ recommended
→ Safe bet: Direct, matches expectation set at opt-in
→ Preview: "{Team Name} — rank, trends, and insights"

② "{Team Name} is ranked #{rank} nationally"
→ Bold play: Puts the ranking right in the subject line. Opens with the data parents crave.
→ Preview: "Your free report card is attached"

③ "here's how {Team Name} stacks up"
→ Personal: Lowercase, conversational, uses the team name
→ Preview: "Rankings, strength profile, and recent results"

**Recommended A/B test:** ① vs ②
**Reason:** Tests whether parents respond to the promise ("report card is inside") or the data ("ranked #47"). Result tells us whether to lead with curiosity or specificity in the welcome sequence.

---

**Email body:**

```
Your team's report card is ready.

[DOWNLOAD REPORT CARD — PDF]

Here's the quick version:

{Team Name} — {Age Group} {Gender}
National Rank: #{rank} (▲{change} this month)
State Rank: #{state_rank} in {State}
PowerScore: {score} (top {percentile}% nationally)
Record: {W}-{L}-{D}

The full report card has your strength profile,
recent results, and schedule difficulty breakdown.
It is attached above.

Over the next few days, I will send you a few
emails about what these numbers mean and how
to use them. Rankings are more useful when you
know what to look for.

Quick question: What are you most curious about —
how your team compares to others, or where
they are trending?

Hit reply and let me know.

— PitchRank


P.S. Want the full picture? Head-to-head comparisons,
predictive analytics, and weekly alerts are available
with Premium. Try it free for 7 days:
pitchrank.io/upgrade
```

---

## Shareability Features

The report card is designed to be shared. Key decisions:

1. **Screenshot-worthy layout:** The ranking overview section (national rank, state rank, PowerScore) fits cleanly in a phone screenshot crop
2. **No sensitive data:** Nothing on the report card is private — it is all publicly derivable from game results
3. **Brand watermark:** PitchRank logo and URL visible in every section so shares drive traffic
4. **Social preview image:** When the team profile URL is shared on social media, the OG image shows the team's rank and PowerScore — auto-generated from the same data
5. **"Share your report card" CTA** in the email: Direct links to share on Twitter/X ("My team is ranked #47 nationally on @PitchRank"), Facebook, and copy-link

---

## Data Requirements for Generation

### Minimum data to generate a report card:
- Team exists in PitchRank DB ✓
- Has a `power_score_final` (not null) ✓
- Has `rank_in_cohort_final` ✓
- Has at least 1 game in the system ✓

### Graceful degradation:
- **No recent games (30-day window empty):** Show career record only, note "No recent games in the ranking window"
- **No state rank:** Show national rank only
- **No SOS data:** Omit strength of schedule section
- **No predictive data:** Omit prediction section (this is Premium-only anyway)
- **Team is "Inactive":** Still generate, but note "This team has not played recently. Rankings reflect last known data."

### Teams that CANNOT get a report card:
- Team not in PitchRank DB (show "Team not found — [suggest adding]")
- Team has zero games (show "Not enough data yet — check back after their first game")

---

## Technical Implementation Notes

### PDF Generation Options
1. **React-PDF (@react-pdf/renderer)** — Already in the Next.js ecosystem. Generate server-side.
2. **Puppeteer/Playwright** — Render an HTML template, screenshot to PDF. More design flexibility.
3. **API route** — `POST /api/report-card/generate` accepts team_id + email, queries DB, generates PDF, sends via email service.

### Email Delivery
- **Transactional email** (not marketing) — use Resend, SendGrid, or Postmark
- PDF attached OR hosted link (hosted is better for tracking opens/clicks)
- Trigger: immediate on form submission
- Fallback: if email fails, show PDF inline on confirmation page

### Caching
- Report cards can be cached per team per week (since rankings update weekly)
- Invalidate cache on Monday after rankings recalculation
- Cache key: `report-card:{team_id}:{ranking_week}`

### Analytics to Track
- Form submissions (total captures)
- Email open rate on delivery email
- PDF download/view rate
- Click-through to pitchrank.io from PDF
- Click-through to Premium upgrade CTA
- Share actions (Twitter, Facebook, copy-link)
- Time from report card to trial start
- Time from report card to Premium conversion

---

## Funnel Integration

### How this feeds the 3 email sequences:

```
Parent downloads report card
  │
  ├── Already has PitchRank account?
  │   ├── Free user → FREE EMAIL SEQUENCE
  │   │   (nurture toward trial: show what Premium reveals)
  │   ├── Trial user → TRIAL EMAIL SEQUENCE
  │   │   (convert before 7 days: deepen engagement)
  │   └── Paid user → PAID EMAIL SEQUENCE
  │       (onboard, reduce churn, upsell annual)
  │
  └── No account yet → FREE EMAIL SEQUENCE
      (welcome → value → bridge → trial CTA)
```

### Email sequence entry points:
- **Email 1 (Day 0):** Report card delivery (this document)
- **Email 2 (Day 2):** "What your PowerScore actually means" (education)
- **Email 3 (Day 4):** "How your team compares to [rival]" (comparison teaser)
- **Email 4 (Day 6):** "3 things your report card doesn't show" (bridge to Premium)
- **Email 5 (Day 8):** "Try Premium free for 7 days" (soft pitch)

These will be built out fully in `/email-sequences`.
