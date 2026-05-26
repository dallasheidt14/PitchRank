# Methodology Page Rewrite + Parent Comparison Blog Post

**Status**: Approved
**Owner**: Dallas Heidt + Claude Code
**Date**: 2026-05-26
**Goal**: Close GEO methodology citation gap (Gemini 20% → target 60%+) and capture parent-04 query ("best app/website for tracking youth soccer performance")

---

## Context

### GEO Baseline (May 13 → May 26)
- Methodology category: weakest at 2/5 web visibility (Gemini 1/5, OpenAI 3/5 on May 13)
- Persistent misses: method-03 (sparse schedules), info-04 (cross-league comparison)
- The `/methodology` page already exists with ~400 lines, 11 FAQ items, Article + FAQPage JSON-LD, and nav links
- This is a rewrite, not a new page

### SEO Performance
- 3,235 clicks/mo (up from ~250/mo baseline, 65% of 5,000/mo target)
- 219 ranking pages now indexed (up from 71 one month ago)
- Indexation bottleneck still active: ~910 pages "Discovered, not indexed"

---

## Deliverable 1: Methodology Page Full Rewrite

### Approach
Single-page rewrite of `MethodologySection.tsx`. Same URL (`/methodology`), new information architecture with deeper content targeting GEO methodology gaps.

### New Information Architecture

**Section 1: Hero / Introduction**
- Heading: "How PitchRank Rankings Work" (more searchable than "PitchRank Methodology")
- Brief positioning: two-part rating system, fairest rankings in the country
- 2-3 sentences max

**Section 2: Where Our Data Comes From** *(new)*
- Game data sources: GotSport tournaments, league results, showcases, cross-state events
- How games are verified and deduplicated
- Coverage scope: 50 states, U10-U19, boys and girls
- Number of teams tracked (pull from DB at build time or use a rounded figure)
- Why broad data sourcing matters (vs platform-locked systems)
- Target: E-E-A-T evidence density for AI citation

**Section 3: The Core Rating Engine** *(expanded)*
- Same 6 factors: opponent quality, competitiveness, SOS, offense/defense, recency, stability
- Each factor gets 2-3 sentences instead of 1
- Add "why this matters" framing per factor
- Do NOT mention "Glicko-2" by name — use "rating engine" / "rating algorithm"

**Section 4: Cross-League Strength Calibration** *(new, targets method-02/04)*
- How teams from different leagues (ECNL, GA, state leagues, independent) are compared fairly
- League-strength multipliers concept (without exposing exact values)
- Tournament cross-pollination: how inter-league play tightens the network
- The network effect: more games = more accurate cross-league comparison
- Convergence: how the system gets sharper as the season progresses

**Section 5: How We Handle Teams With Few Games** *(expanded, targets method-03)*
- Current page has 2 sentences — expand to a full section
- Conservative starting point for new teams
- Confidence widening: uncertainty is high with few games, decreases with more data
- Minimum games threshold before ranked (MIN_GAMES=9, but don't expose the exact number — say "a minimum number of verified games")
- How uncertainty affects ranking position vs rating
- Why this prevents inflated or deflated placements

**Section 6: The Machine Learning Layer** *(restructured)*
- Same concept: overperformance vs underperformance detection
- Tighter copy, add concrete example of what "overperformance" means
- How the adjustment is bounded (intentionally small)
- What this catches that the core engine alone doesn't

**Section 7: How It All Comes Together**
- PowerScore composition (core + ML adjustment)
- Do NOT include tier thresholds
- The final ranking is a blend of statistical strength and trend detection

**Section 8: Update Cadence & Freshness** *(merged)*
- Monday refresh cycle
- What triggers recalculation
- How quickly new games flow in (daily scraping → Monday ranking run)
- Freshness signal for AI engines (dateModified updates)

**Section 9: Frequently Asked Questions** *(expanded to ~15)*
Keep existing 11 FAQs, add 4 new ones:
1. "How does PitchRank compare teams across different leagues?" — targets method-02/04
2. "How accurate are rankings for teams that have only played a few games?" — targets method-03
3. "Where does PitchRank get its game data?" — targets data sourcing queries
4. "Can teams from different states be compared fairly?" — targets cross-state queries

**Section 10: The PitchRank Promise** *(kept)*
- Closing CTA, same tone

### Structured Data Updates
- `FAQSchema.tsx`: Add 4 new questions (total: 15)
- `MethodologySchema.tsx`: Update `dateModified` to current date
- Consider adding `HowTo` schema for "how rankings are calculated" (targets method queries in Google featured snippets)

### Content Rules
- No "Glicko-2" by name anywhere
- No PowerScore tier thresholds
- No exact formula weights or parameters
- Use "rating engine" / "rating algorithm" / "our system"
- Use "group" not "cohort" in any user-facing text
- Tone: authoritative but accessible to parents, not academic

### Files Modified
- `frontend/components/MethodologySection.tsx` — full rewrite
- `frontend/components/FAQSchema.tsx` — add 4 new FAQ items
- `frontend/components/MethodologySchema.tsx` — update dateModified
- `frontend/app/methodology/page.tsx` — update metadata (title, description) if needed

---

## Deliverable 2: Parent Comparison Blog Post

### Target Query
- parent-04: "best app/website for tracking youth soccer performance"
- Related: "youth soccer ranking websites", "best youth soccer rankings"

### Format
- MDX blog post at `frontend/content/blog/best-youth-soccer-ranking-websites-2026.mdx`
- Register in `frontend/content/blog-posts.tsx`

### Title
"Best Youth Soccer Ranking Websites for Parents (2026)"

### Tone
Objective comparison — genuine pros/cons for each site. PitchRank is featured but not the only recommendation. Builds trust + E-E-A-T.

### Structure

**1. Introduction (2-3 paragraphs)**
- Why rankings matter for parents navigating club soccer
- What to look for in a ranking site (methodology transparency, data breadth, update frequency)
- Brief overview of the landscape

**2. Comparison Table**
Quick-scan table with columns: Site, What It Ranks, Methodology, Coverage, Cost, Best For

**3. Per-Site Breakdown (verified research)**

Each site gets a subsection with:
- What it does (1-2 sentences)
- How it works (methodology summary)
- Strengths (bulleted)
- Limitations (bulleted)
- Best for (1 sentence)

Sites to cover (in this order):

**PitchRank** (pitchrank.io)
- What: Individual team rankings, all competitive teams, all 50 states, U10-U19
- Methodology: Two-part rating engine (core algorithm + ML trend detection), head-to-head results, SOS-weighted
- Strengths: Algorithmic/head-to-head (not placement-based), broad data sourcing (not locked to one platform), weekly updates, free, transparent methodology page, cross-state comparison
- Limitations: Newer platform (smaller brand recognition), minimum games threshold means new teams take time to appear
- Best for: Parents who want data-driven, head-to-head rankings for any competitive team

**GotSport** (rankings.gotsport.com)
- What: Individual team rankings, 100K+ teams, U10-U19
- Methodology: Placement + bonus points from GotSport-hosted tournaments; flight value based on top-5 team percentile
- Strengths: Largest dataset, free, integrated with tournament registration, mobile apps (Team App + Live)
- Limitations: Only counts GotSport-hosted tournaments (platform lock-in); placement-heavy not head-to-head; rewards tournament quantity over quality; geographic advantage for areas with more GotSport events; community consensus is poor predictive accuracy
- Best for: Parents already using GotSport for tournament registration who want a quick glance at relative standing
- Sources: GotSport Support docs, SoccerWire analysis, SoCalSoccer/BigSoccer forum threads

**SoccerWire** (soccerwire.com)
- What: Top 100 club rankings (not individual teams), U13-U19
- Methodology: League PPG + playoffs + national team call-ups + pro signings; ECNL/MLS NEXT/GA only
- Strengths: Development-oriented philosophy, rewards clubs producing national-level players, free, news/recruiting content
- Limitations: Club-level only (can't find your U14 team's rank); only covers elite national leagues (irrelevant for state/USYS leagues); monthly updates; paid player profiles criticized as pay-to-promote on forums
- Best for: Parents at elite clubs (ECNL/MLS NEXT) who want to evaluate club-level development track record
- Sources: SoccerWire formula page, SoCalSoccer forum threads

**USARank** (usarank.com)
- What: Individual team rankings, all states, U08-U19, six color tiers
- Methodology: Proprietary algorithm, tournament-only data from SincSports-managed events, weekly updates
- Strengths: Broad state/age coverage, free, tier system for quick context
- Limitations: Tournament-only data (no league play — ECNL/MLS NEXT/GA excluded); SincSports platform lock-in (same structural flaw as GotSport, different silo); selective reporting (teams can omit losses); team identity fragmentation across tournaments; opaque methodology (about page returns 403); near-zero community discussion/adoption; team detail pages inaccessible
- Best for: Teams that play primarily in SincSports-managed tournaments
- Sources: SincSports service page, GA Soccer Forum, SoCalSoccer forum

**TopDrawerSoccer** (topdrawersoccer.com)
- What: National Top 25 team rankings per age group (U13-U18), plus player rankings
- Methodology: League results prioritized over tournaments; A/B tournament tiers; younger age groups are roster-based approximations
- Strengths: Strong college recruiting ecosystem (~2,500 coaches visit daily), no pay-to-rank for team rankings, monthly updates with transparent criteria
- Limitations: National Top 25 only (irrelevant for most club teams); ECNL bias in player evaluations (per forum users); younger age groups not results-driven; player rankings partially paywalled ($99/yr)
- Best for: High-school-aged players/families navigating college recruiting
- Sources: TDS methodology page, Wikipedia, SoCalSoccer forum

**4. How to Use Rankings Wisely (2-3 paragraphs)**
- Rankings are one input, not the final word
- No system captures coaching quality, player development trajectory, or team culture
- Use multiple sources and watch games yourself

**5. FAQ (3-4 items with JSON-LD)**
- "Which youth soccer ranking site is most accurate?"
- "Are youth soccer rankings free?"
- "Why do different ranking sites show different results?"
- "Should I choose a club based on rankings?"

### Structured Data
- `BlogPosting` JSON-LD with author entity
- `FAQPage` JSON-LD for the 4 FAQ items
- Internal links to `/methodology` and `/rankings`

### Content Rules
- All competitor claims must be verified from the research (no fabrication)
- Link to source material where appropriate (GotSport support docs, SoccerWire formula page, etc.)
- No "Glicko-2" by name
- No PowerScore tier thresholds
- Use "group" not "cohort"
- Tone: helpful parent resource, not marketing copy

### Files Created/Modified
- `frontend/content/blog/best-youth-soccer-ranking-websites-2026.mdx` — new MDX blog post
- `frontend/content/blog-posts.tsx` — register new post
- `frontend/scripts/generate-llms-txt.ts` — regenerate llms.txt after new content

---

## Out of Scope
- ECNL/NAL/MLS Next comparison landing page (info-05 gap) — separate future work
- `/authors/dallas-heidt` founder page (brand-04 gap) — separate future work
- Programmatic ranking page content changes
- Any ranking engine or database changes

## Success Criteria
- `/methodology` page passes Lighthouse SEO audit (90+)
- All 15 FAQ items render in FAQPage JSON-LD (validate via Rich Results Test)
- Blog post registers in sitemap and is submitted to GSC
- Re-run GEO 20-prompt panel 4 weeks after publish; methodology category improves from 2/5 to 3+/5
- Blog post appears in GSC impressions within 2 weeks for "best youth soccer ranking" queries
