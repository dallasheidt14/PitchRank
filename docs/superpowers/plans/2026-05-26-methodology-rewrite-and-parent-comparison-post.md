# Methodology Rewrite + Parent Comparison Blog Post Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the `/methodology` page to close GEO methodology citation gaps and publish a "Best Youth Soccer Ranking Websites" blog post to capture parent-04 queries.

**Architecture:** Two independent deliverables sharing no code. Deliverable 1 rewrites three existing components (`MethodologySection.tsx`, `FAQSchema.tsx`, `MethodologySchema.tsx`) and updates page metadata. Deliverable 2 adds a new MDX blog post, registers its FAQs, and regenerates `llms.txt`.

**Tech Stack:** Next.js 16, React 19, TypeScript 5.9, Tailwind v4, MDX, JSON-LD structured data

**Spec:** `docs/superpowers/specs/2026-05-26-methodology-rewrite-and-parent-comparison-post.md`

---

## File Map

### Deliverable 1: Methodology Page Rewrite
| Action | File | Responsibility |
|--------|------|---------------|
| Rewrite | `frontend/components/MethodologySection.tsx` | Full page content (10 sections) |
| Rewrite | `frontend/components/FAQSchema.tsx` | FAQPage JSON-LD (11 → 15 questions) |
| Modify | `frontend/components/MethodologySchema.tsx` | Update headline + description |
| Modify | `frontend/app/methodology/page.tsx` | Update metadata title/description + dateModified |

### Deliverable 2: Blog Post
| Action | File | Responsibility |
|--------|------|---------------|
| Create | `frontend/content/blog/best-youth-soccer-ranking-websites-2026.mdx` | Blog post content |
| Modify | `frontend/lib/blog-faqs.ts` | Add 4 FAQ entries for the new post |
| Run | `frontend/scripts/generate-llms-txt.ts` | Regenerate `public/llms.txt` |

---

## Task 1: Rewrite MethodologySection.tsx

**Files:**
- Rewrite: `frontend/components/MethodologySection.tsx`

This is the largest task — a full rewrite of the methodology page content. The new component keeps the same export name and signature but replaces the entire body with 10 sections per the spec.

- [ ] **Step 1: Read current file and surrounding components**

Read these files to understand the current patterns:
```
frontend/components/MethodologySection.tsx
frontend/components/FAQSchema.tsx
frontend/components/MethodologySchema.tsx
frontend/app/methodology/page.tsx
frontend/components/ui/card.tsx (for Card, CardHeader, CardContent, CardDescription variants)
```

- [ ] **Step 2: Rewrite MethodologySection.tsx**

Replace the entire component body. Keep the same export (`export function MethodologySection()`), same `FAQSchema` import and render. Use the same Card/icon pattern as the existing code.

**New section order and content:**

**Section 1 — Hero: "How PitchRank Rankings Work"**
- Card variant="primary"
- Heading: "How PitchRank Rankings Work" (more searchable than old "PitchRank Methodology")
- 2-3 sentence positioning: two-part rating system, fairest rankings, data-driven

**Section 2 — "Where Our Data Comes From" (NEW)**
- Icon: `Database` from lucide-react
- Cover: game data from tournaments (GotSport and others), league results, showcases, cross-state events
- How games are verified and deduplicated
- Coverage scope: all 50 states, U10 through U19, boys and girls
- Approximate teams tracked: "thousands of teams across 50 states" (do NOT query DB)
- Why broad data sourcing matters vs platform-locked systems
- Use 4 bullet items in the same `flex items-start gap-3 p-4 rounded-lg bg-muted/50` pattern as existing factor cards

**Section 3 — "The Core Rating Engine" (EXPANDED)**
- Icon: `Brain` (keep)
- Same 6 factors: opponent quality, competitiveness, SOS, offense/defense, recency, stability
- Each factor gets 2-3 sentences (currently 1 sentence each)
- Add "why this matters" angle per factor. Examples:
  - Opponent Quality: "A win against a top-10 team in your state carries far more weight than a win against an unranked opponent. This prevents teams from inflating their record against weak competition."
  - SOS: "Two teams can have identical records, but if one earned theirs against nationally-ranked opponents and the other played only local recreation teams, their ratings will reflect that difference."
- Keep the same `CheckCircle`/`Activity`/`TrendingUp`/`Shield`/`Clock`/`Anchor` icon grid
- Keep the summary callout box at the bottom

**Section 4 — "Cross-League Strength Calibration" (NEW, targets method-02/04)**
- Icon: `Scale` from lucide-react
- Explain: teams from different leagues (ECNL, GA, state leagues, independent clubs) are compared fairly
- League-strength calibration: the system recognizes that leagues vary in overall competitiveness and adjusts accordingly
- Tournament cross-pollination: when teams from different leagues meet at tournaments, those results directly calibrate cross-league strength
- The network effect: "The more cross-league games played, the more accurate comparisons become. By mid-season, even teams that have never played each other can be compared through chains of shared opponents."
- Convergence: the system gets sharper as the season progresses — early-season rankings have wider uncertainty
- Do NOT expose exact multiplier values

**Section 5 — "How We Handle Teams With Few Games" (EXPANDED, targets method-03)**
- Icon: `UserPlus` (keep)
- Currently 2 sentences — expand to a full section with 4 bullet points:
  - Conservative starting point: new teams begin with a neutral rating, not inflated or penalized
  - Confidence and uncertainty: with fewer games, the system assigns wider uncertainty — the rating exists but carries less confidence
  - Minimum games threshold: "Teams need a minimum number of verified games before appearing in official rankings. This prevents a single fluky result from producing a misleading placement."
  - Gradual convergence: "As a team plays more games against rated opponents, their rating stabilizes and their ranking becomes increasingly reliable."
- Do NOT expose MIN_GAMES=9

**Section 6 — "The Machine Learning Layer" (RESTRUCTURED)**
- Icon: `Cpu` (keep)
- Same core concept: overperformance vs underperformance detection
- Add concrete example: "If a team rated #30 in their state consistently beats teams rated #10-#15, the ML layer detects that pattern and adjusts their rating upward — even before they've played enough games for the core engine to catch up."
- How the adjustment is bounded: "The ML adjustment is intentionally small — it fine-tunes rather than overrides. A massive upset in a single game won't swing a rating, but a consistent pattern of exceeding expectations will."
- What this catches that the core engine alone doesn't: "The core engine measures where a team has been. The ML layer anticipates where they're going."

**Section 7 — "How It All Comes Together"**
- Icon: `Link` (keep)
- Card variant="accent"
- PowerScore composition: core performance + ML trend adjustment
- "The final PowerScore is a single number that captures both proven strength and emerging trajectory."
- Keep the 2-column grid (Core Performance / ML Trend Adjustment) and the 5-item checklist
- Do NOT include tier thresholds

**Section 8 — "Update Cadence & Data Freshness" (MERGED)**
- Icon: `Calendar` (keep)
- Merge existing "Updated Every Monday" content with new data freshness info
- Monday refresh cycle: entire network recalculates
- Daily data ingestion: "Game results flow into our system daily as tournaments and leagues report scores. Every Monday morning, the entire ranking network recalculates with the latest data."
- What triggers recalculation: new results, strength of schedule updates, cross-state comparisons tighten, ML picks up new trends
- Keep the 4-item checklist format

**Section 9 — "Frequently Asked Questions" (EXPANDED)**
- Icon: `HelpCircle` (keep)
- Keep existing 4 visible FAQ items (manipulation, winning by a lot, one game swing, missing games)
- Add 4 new visible FAQ items:
  - "How does PitchRank compare teams across different leagues?" — "Our system calibrates league strength automatically. When teams from different leagues meet at tournaments, those head-to-head results anchor cross-league comparisons. The more inter-league games played, the more accurate these comparisons become."
  - "How accurate are rankings for teams that have only played a few games?" — "Rankings for newer teams carry wider uncertainty. We require a minimum number of verified games before a team appears in official rankings, and even then, their rating stabilizes further with each additional game. Early-season rankings should be treated as directional, not definitive."
  - "Where does PitchRank get its game data?" — "We collect verified game results from tournaments, leagues, showcases, and cross-state events across all 50 states. Our data pipeline pulls from multiple sources — we are not locked to any single tournament platform, which gives us broader coverage than platform-specific ranking systems."
  - "Can teams from different states be compared fairly?" — "Yes. Cross-state tournaments and national events create direct connections between state ecosystems. A team from Arizona that plays in a California tournament creates a bridge that links both states' rankings. The more cross-state play, the more accurate interstate comparisons become."

**Section 10 — "The PitchRank Promise" (KEPT)**
- Icon: `Target` (keep)
- Card variant="primary"
- Same content: "Smart rankings. Fair rankings. Real rankings."

**Content rules for all sections:**
- No "Glicko-2" — use "rating engine" / "rating algorithm" / "our system"
- No PowerScore tier thresholds
- No exact formula weights or parameters
- Use "group" not "cohort"
- Tone: authoritative but accessible to parents

- [ ] **Step 3: Verify the component compiles**

Run:
```bash
cd C:/PitchRank/frontend && npx tsc --noEmit --pretty 2>&1 | head -30
```
Expected: No errors in MethodologySection.tsx

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank && git add frontend/components/MethodologySection.tsx && git commit -m "feat(seo): rewrite methodology page content for GEO coverage

Expand from 9 sections to 10 with deeper content targeting GEO
methodology gaps: data sourcing, cross-league calibration, sparse
schedule handling. Each rating factor expanded from 1 to 2-3 sentences."
```

---

## Task 2: Expand FAQSchema.tsx with 4 new questions

**Files:**
- Modify: `frontend/components/FAQSchema.tsx`

- [ ] **Step 1: Read current FAQSchema.tsx**

Read `frontend/components/FAQSchema.tsx` to see current 11 questions.

- [ ] **Step 2: Add 4 new FAQ items to the mainEntity array**

Append these 4 items after the existing 11 (before the closing `]`):

```typescript
      {
        '@type': 'Question',
        name: 'How does PitchRank compare teams across different leagues?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'PitchRank calibrates league strength automatically using cross-league game results. When teams from different leagues (ECNL, GA, state leagues, independent clubs) meet at tournaments, those head-to-head results anchor cross-league comparisons. The more inter-league games played, the more accurate these comparisons become across the entire ranking network.',
        },
      },
      {
        '@type': 'Question',
        name: 'How accurate are rankings for teams that have only played a few games?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Rankings for newer teams carry wider uncertainty. PitchRank requires a minimum number of verified games before a team appears in official rankings. Even after that threshold, a team\'s rating stabilizes further with each additional game against rated opponents. Early-season rankings should be treated as directional rather than definitive.',
        },
      },
      {
        '@type': 'Question',
        name: 'Where does PitchRank get its game data?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'PitchRank collects verified game results from tournaments, leagues, showcases, and cross-state events across all 50 states. The data pipeline pulls from multiple sources and is not locked to any single tournament platform, providing broader coverage than platform-specific ranking systems. Results are ingested daily and rankings recalculate every Monday.',
        },
      },
      {
        '@type': 'Question',
        name: 'Can teams from different states be compared fairly?',
        acceptedAnswer: {
          '@type': 'Answer',
          text: 'Yes. Cross-state tournaments and national events create direct connections between state ecosystems. When an Arizona team plays in a California tournament, that result bridges both states\' rankings. The more cross-state play occurs, the more accurate interstate comparisons become throughout the season.',
        },
      },
```

- [ ] **Step 3: Verify no TypeScript errors**

Run:
```bash
cd C:/PitchRank/frontend && npx tsc --noEmit --pretty 2>&1 | grep -i "FAQSchema"
```
Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank && git add frontend/components/FAQSchema.tsx && git commit -m "feat(seo): add 4 GEO-targeted FAQ items to methodology schema

Cross-league comparison, sparse schedules, data sourcing, and
cross-state fairness. Total FAQ items: 15."
```

---

## Task 3: Update MethodologySchema.tsx and page.tsx metadata

**Files:**
- Modify: `frontend/components/MethodologySchema.tsx`
- Modify: `frontend/app/methodology/page.tsx`

- [ ] **Step 1: Read both files**

Read `frontend/components/MethodologySchema.tsx` and `frontend/app/methodology/page.tsx`.

- [ ] **Step 2: Update MethodologySchema headline and description**

In `frontend/components/MethodologySchema.tsx`, update the schema object:

```typescript
  const schema = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: 'How PitchRank Youth Soccer Rankings Work',
    description:
      'How PitchRank calculates youth soccer team rankings using opponent quality, cross-league strength calibration, schedule strength, and machine-learning trend detection. Updated weekly with verified game data from all 50 states.',
    url: pageUrl,
    datePublished,
    dateModified,
    author: PITCHRANK_TEAM_AUTHOR,
    publisher: PITCHRANK_PUBLISHER,
    image: `${BASE_URL}/opengraph-image.png`,
    mainEntityOfPage: {
      '@type': 'WebPage',
      '@id': pageUrl,
    },
  };
```

- [ ] **Step 3: Update page.tsx metadata and dateModified**

In `frontend/app/methodology/page.tsx`:

Update the `metadata` export:
```typescript
export const metadata: Metadata = {
  title: 'How Our Rankings Work',
  description:
    'How PitchRank calculates youth soccer team rankings using opponent quality, cross-league strength calibration, and machine-learning trend detection. Updated weekly with game data from all 50 states.',
  alternates: {
    canonical: `${BASE_URL}/methodology`,
  },
  openGraph: {
    title: 'How PitchRank Youth Soccer Rankings Work',
    description:
      'How PitchRank calculates youth soccer team rankings using data-driven analytics, cross-league calibration, and ML trend detection.',
    url: `${BASE_URL}/methodology`,
    siteName: 'PitchRank',
    type: 'website',
    images: [
      {
        url: '/logos/pitchrank-wordmark.svg',
        width: 1200,
        height: 630,
        alt: 'How PitchRank Rankings Work',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'How PitchRank Youth Soccer Rankings Work',
    description: 'How PitchRank calculates youth soccer rankings with cross-league calibration and ML trend detection.',
    images: ['/logos/pitchrank-wordmark.svg'],
  },
};
```

Update the `dateModified` prop on `MethodologySchema`:
```typescript
<MethodologySchema datePublished="2026-04-30T00:00:00Z" dateModified="2026-05-26T00:00:00Z" />
```

Update the `PageHeader` title:
```typescript
<PageHeader
  title="How Our Rankings Work"
  description="Understanding how PitchRank calculates team rankings and power scores"
  showBackButton
  backHref="/"
/>
```

- [ ] **Step 4: Verify no TypeScript errors**

Run:
```bash
cd C:/PitchRank/frontend && npx tsc --noEmit --pretty 2>&1 | head -20
```
Expected: No errors

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add frontend/components/MethodologySchema.tsx frontend/app/methodology/page.tsx && git commit -m "feat(seo): update methodology page metadata and schema for GEO

Title: 'How Our Rankings Work', description adds cross-league
calibration. dateModified bumped to 2026-05-26."
```

---

## Task 4: Build and visually verify methodology page

**Files:**
- None (verification only)

- [ ] **Step 1: Run the dev server and verify the page renders**

```bash
cd C:/PitchRank/frontend && npm run dev
```

Open `http://localhost:3000/methodology` in a browser and verify:
- Page title shows "How Our Rankings Work"
- All 10 sections render without errors
- New sections (Data Sources, Cross-League Calibration, Sparse Schedules) are present
- FAQ section has 8 visible questions (4 original + 4 new)
- No console errors

- [ ] **Step 2: Validate structured data**

View page source and search for `application/ld+json`. Verify:
- FAQPage schema has 15 questions
- Article schema has updated headline "How PitchRank Youth Soccer Rankings Work"
- dateModified is "2026-05-26T00:00:00Z"

- [ ] **Step 3: Check mobile rendering**

Resize browser to 375px width. Verify:
- All cards stack properly
- No horizontal overflow
- Text is readable

---

## Task 5: Create the comparison blog post MDX file

**Files:**
- Create: `frontend/content/blog/best-youth-soccer-ranking-websites-2026.mdx`

- [ ] **Step 1: Read an existing MDX blog post for format reference**

Read `frontend/content/blog/colorado-youth-soccer-rankings-guide.mdx` to confirm frontmatter format and markdown conventions.

- [ ] **Step 2: Create the MDX file**

Create `frontend/content/blog/best-youth-soccer-ranking-websites-2026.mdx` with this frontmatter:

```yaml
---
title: 'Best Youth Soccer Ranking Websites for Parents (2026)'
slug: 'best-youth-soccer-ranking-websites-2026'
excerpt: 'An honest comparison of youth soccer ranking sites — PitchRank, GotSport, SoccerWire, USARank, and TopDrawerSoccer. What each one does, how they work, and which is right for your family.'
author: 'PitchRank Team'
date: '2026-05-26'
readingTime: '10 min read'
tags: ['Rankings', 'Educational', 'Parents', 'Comparison']
keywords:
  [
    'best youth soccer rankings',
    'youth soccer ranking websites',
    'gotsport vs pitchrank',
    'youth soccer rankings comparison',
    'best youth soccer ranking site',
  ]
---
```

**Content structure (write the full markdown body):**

**Heading:** `# Best Youth Soccer Ranking Websites for Parents (2026)`

**Introduction (3 paragraphs):**
- Hook: Your kid's coach mentions a ranking, another parent cites a different number from a different site — which one should you trust?
- What to look for in a ranking site: methodology transparency, data breadth (does it cover only one tournament platform or many?), update frequency, cost, and whether it ranks individual teams or just clubs
- Brief overview: we reviewed five ranking sites to help parents navigate the landscape

**Comparison table:**

```markdown
| Site | What It Ranks | Data Source | Coverage | Cost | Best For |
|------|--------------|-------------|----------|------|----------|
| [PitchRank](https://pitchrank.io) | Individual teams | Multiple sources | U10-U19, 50 states | Free | Data-driven head-to-head rankings for any competitive team |
| [GotSport](https://rankings.gotsport.com) | Individual teams | GotSport tournaments only | U10-U19, 100K+ teams | Free | Quick look if you already use GotSport |
| [SoccerWire](https://www.soccerwire.com) | Clubs (Top 100) | ECNL/MLS NEXT/GA leagues | U13-U19, elite only | Free | Club-level development track record |
| [USARank](https://usarank.com) | Individual teams | SincSports tournaments only | U08-U19, all states | Free | Teams in SincSports tournaments |
| [TopDrawerSoccer](https://www.topdrawersoccer.com) | National Top 25 | ECNL/MLS NEXT leagues | U13-U18, national only | Partial ($99/yr) | College recruiting ecosystem |
```

**Per-site sections:** Use `##` headings. Each site gets:
- `### [Site Name]` heading
- 1-2 sentence description
- `**How it works:**` — methodology summary (2-3 sentences)
- `**Strengths:**` — bulleted list (3-5 items)
- `**Limitations:**` — bulleted list (3-5 items)
- `**Best for:**` — 1 sentence

Write the full content for each site using the verified research from the spec. Key content per site:

**PitchRank:**
- How it works: Two-part rating engine evaluates every game result through opponent quality, strength of schedule, competitiveness, and consistency. A machine learning layer detects trending teams. Rankings update every Monday.
- Strengths: Head-to-head results (not tournament placement), data from multiple sources (not locked to one platform), transparent methodology, free, cross-state comparison, weekly updates
- Limitations: Newer platform with growing brand recognition, teams need a minimum number of games before appearing in rankings
- Best for: Parents who want data-driven, result-based rankings for any competitive team in any state

**GotSport:**
- How it works: Teams earn points based on tournament placement. Each tournament flight gets a "Flight Value" based on the national ranking percentile of its top teams. Champions earn 100% of that value, finalists 50%, semifinalists 25%.
- Strengths: Largest dataset (100K+ teams), free to view, integrated with tournament registration parents already use, mobile apps available
- Limitations: Only counts GotSport-hosted tournaments (non-GotSport events excluded), placement-based not head-to-head (teams earn points from finishing above opponents they never played), rewards tournament quantity — teams near more GotSport events accumulate more points, community consensus on forums is poor predictive accuracy
- Best for: Parents already using GotSport for tournament registration who want a quick relative comparison
- Sources to reference inline: [GotSport Support](https://support.gotsport.com/what-are-the-gotsoccer-rankings)

**SoccerWire:**
- How it works: Top 100 club rankings (not individual teams) using league points-per-game, playoff results, national team call-ups, and pro signings within 3 years. Only counts ECNL, MLS NEXT, and Girls Academy.
- Strengths: Development-oriented — rewards clubs producing national-level players, not just tournament wins. Free to view. Strong youth soccer news coverage.
- Limitations: Club-level only (you cannot find your specific U14 team's rank), only covers elite national leagues (irrelevant for state leagues, USYS, or smaller platforms), monthly updates
- Best for: Parents at ECNL or MLS NEXT clubs evaluating club-level development track record

**USARank:**
- How it works: Proprietary algorithm ranking teams from tournament results collected exclusively through SincSports-managed events. Teams are placed into six color tiers (Gold through Green). Updated weekly.
- Strengths: Broad state and age group coverage (U08-U19), free, tier system gives quick competitive context
- Limitations: Tournament data only — no league play (ECNL, MLS NEXT, GA results excluded), only SincSports-managed events count (same platform lock-in problem as GotSport but a different silo), methodology page is inaccessible (returns 403), teams can selectively report results (report wins, omit losses), team identity fragmentation across tournaments, near-zero community discussion or independent reviews
- Best for: Teams that play primarily in SincSports-managed tournaments

**TopDrawerSoccer:**
- How it works: National Top 25 team rankings per age group (U13-U18) prioritizing league results over tournaments. Younger age groups (U13-U15) are roster-based approximations rather than result-driven. Monthly updates.
- Strengths: Strong college recruiting ecosystem (player rankings, commitment tracker, ~2,500 college coaches visit daily), no pay-to-rank for team rankings, transparent ranking criteria
- Limitations: National Top 25 only (irrelevant for most club teams), ECNL bias in player evaluations noted on forums, younger age group rankings not results-driven, player rankings partially paywalled ($99/yr)
- Best for: High-school-aged players and families navigating the college recruiting process

**"How to Use Rankings Wisely" section (`## How to Use Rankings Wisely`):**
- Rankings are one data point, not the final word on a team's quality
- No ranking system captures coaching quality, player development culture, team chemistry, or the intangibles that make a club the right fit for your child
- Use multiple ranking sources to triangulate — if a team ranks well across multiple independent systems, that signal is stronger than any single ranking
- Watch games yourself. Talk to other parents. Rankings can tell you who's winning, but not how they're developing players.

**Closing CTA:**
```markdown
> **Want to see where your team stands?** [Check your team's ranking on PitchRank](/rankings) — updated every Monday with real game results.
```

- [ ] **Step 3: Verify the MDX file parses correctly**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit --pretty 2>&1 | head -10
```

And verify the blog post appears in the blog listing by checking the dev server at `/blog`.

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank && git add frontend/content/blog/best-youth-soccer-ranking-websites-2026.mdx && git commit -m "feat(blog): add 'Best Youth Soccer Ranking Websites for Parents (2026)'

Objective comparison of PitchRank, GotSport, SoccerWire, USARank, and
TopDrawerSoccer with verified research. Targets parent-04 GEO query."
```

---

## Task 6: Register blog post FAQs and regenerate llms.txt

**Files:**
- Modify: `frontend/lib/blog-faqs.ts`
- Run: `frontend/scripts/generate-llms-txt.ts`

- [ ] **Step 1: Read blog-faqs.ts to find insertion point**

Read `frontend/lib/blog-faqs.ts` and find the section pattern (state pillars are alphabetical, others follow).

- [ ] **Step 2: Add FAQ entries for the new blog post**

Add this entry to `BLOG_FAQS` in `frontend/lib/blog-faqs.ts`. Place it after the state pillar section, in the general/educational section (follow existing ordering pattern):

```typescript
  'best-youth-soccer-ranking-websites-2026': [
    {
      question: 'Which youth soccer ranking site is most accurate?',
      answer:
        'Accuracy depends on data breadth and methodology. Sites that use head-to-head game results and strength-of-schedule weighting (like PitchRank) tend to be more predictive than placement-based systems. The most reliable approach is to cross-reference multiple ranking sources — if a team ranks well across independent systems, that signal is stronger than any single ranking.',
    },
    {
      question: 'Are youth soccer rankings free?',
      answer:
        'Most youth soccer ranking sites offer free access to team rankings. PitchRank, GotSport, SoccerWire, and USARank are all free to view. TopDrawerSoccer offers free team rankings but charges $99/year for detailed player rankings and recruiting tools.',
    },
    {
      question: 'Why do different ranking sites show different results?',
      answer:
        'Each ranking site uses a different methodology and data source. GotSport only counts its own tournaments, SoccerWire ranks clubs not teams, and TopDrawerSoccer covers only the national Top 25. Different inputs and algorithms produce different outputs. This is why cross-referencing multiple sources gives a more complete picture.',
    },
    {
      question: 'Should I choose a club based on rankings?',
      answer:
        'Rankings should be one factor among many. They can tell you about competitive strength and schedule quality, but they cannot measure coaching philosophy, player development culture, playing time, or whether a club is the right fit for your child. Use rankings to narrow your search, then visit practices, talk to coaches, and speak with other families.',
    },
  ],
```

- [ ] **Step 3: Regenerate llms.txt**

```bash
cd C:/PitchRank/frontend && npx tsx scripts/generate-llms-txt.ts
```

Verify `public/llms.txt` now includes the new blog post.

- [ ] **Step 4: Verify no TypeScript errors**

```bash
cd C:/PitchRank/frontend && npx tsc --noEmit --pretty 2>&1 | head -10
```
Expected: No errors

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/blog-faqs.ts frontend/public/llms.txt && git commit -m "feat(seo): add blog FAQs for ranking comparison post + regenerate llms.txt

4 FAQ entries for 'best-youth-soccer-ranking-websites-2026' slug.
llms.txt updated with new blog post."
```

---

## Task 7: Visual verification of blog post

**Files:**
- None (verification only)

- [ ] **Step 1: Verify blog post renders on dev server**

Open `http://localhost:3000/blog/best-youth-soccer-ranking-websites-2026` and verify:
- Title renders correctly
- Comparison table renders (check all 5 rows)
- All per-site sections render with proper headings
- Internal links to `/methodology` and `/rankings` work
- No console errors

- [ ] **Step 2: Verify structured data**

View page source and check:
- `BlogPosting` JSON-LD is present with correct title, date, author
- `FAQPage` JSON-LD is present with 4 questions
- `BreadcrumbList` JSON-LD shows Blog > Best Youth Soccer Ranking Websites for Parents (2026)

- [ ] **Step 3: Verify blog listing page**

Open `http://localhost:3000/blog` and verify the new post appears in the listing with correct title, excerpt, and date.

- [ ] **Step 4: Check mobile rendering**

Resize to 375px. Verify:
- Comparison table scrolls horizontally or stacks (depending on existing blog table styles)
- All sections readable
- No overflow
