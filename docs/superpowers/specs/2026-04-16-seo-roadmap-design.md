# SEO Roadmap: PitchRank April 16 – September 1, 2026

**Status**: In Progress — Week 1 partially complete
**Owner**: Dallas Heidt + Claude Code
**Capacity**: 15 hrs/week (~3 hrs/day), solo operator
**Tools**: GSC, PageSpeed Insights, Claude Code (no paid SEO tools)
**Target**: 5,000+ organic clicks/month by September 1 (baseline: ~165 clicks/month as of April 2026)
**Last updated**: 2026-04-16

---

## Strategic Approach: Foundation First

All four SEO pillars fire sequentially to maximize compound returns:

1. **Programmatic content enrichment** (Phase 1) — enrich 1,200+ ranking pages with unique, DB-driven text before writing any new blog posts
2. **Content scale** (Phase 2) — batch-publish state pillars for top-population states
3. **GSC-driven optimization** (Phase 3) — optimize what's working, write spokes only where data proves demand
4. **Authority building + GEO** (Phases 3–4) — outreach, data stories, AI citation optimization

---

## Current Baseline (April 16, 2026)

- **Organic performance**: 494 clicks / 6,707 impressions per 90 days (~165 clicks/month)
- **Blog posts**: 10 (7 state pillars: AZ, CO, FL, MI, NJ, NC, PA + 3 informational)
- **Ranking pages**: 1,200+ dynamic routes (`/rankings/{state}/{age}/{gender}`)
  - Primarily data tables with minimal text — intro paragraph + sr-only top-25 list
  - No FAQ blocks on ranking pages
  - JSON-LD present (RankingTable, BreadcrumbList) but no FAQPage schema
- **Structured data**: JSON-LD on ranking pages only — blog posts have none
- **Internal linking**: One-way (blog → rankings); ranking pages do NOT link back to blog posts
  - RelatedRankings component provides ~15-20 contextual links per ranking page (adjacent ages, genders, popular states)
- **Meta descriptions**: Curated for 10 high-CTR states; fallback template for remaining 40
- **Sitemap**: Covers all ranking pages + blog posts
- **Technical**: Soft-404 and SSR content-order issues previously fixed

---

## Phase 1: Foundation (Weeks 1–4 / Apr 16 – May 13)

**Goal**: Make 1,200+ ranking pages SEO-ready. No new blog posts — pure infrastructure.
**Estimated hours**: ~32 total (~8/week)

### Week 1 (Apr 16–22): Programmatic Content Design + Blog JSON-LD

| Task | Hours | Who | Status |
|---|---|---|---|
| Design dynamic content block for ranking pages — evolved to 5-module system: cohort summary w/ positioning hook, top clubs table, biggest movers (clickable), FAQ w/ JSON-LD, freshness signal | 3 | You + Claude | DONE (Apr 16) |
| Build modules + DB query — `frontend/lib/cohort-seo.ts` + `frontend/components/CohortSEOContent.tsx` + updated page.tsx (PR #633, merged) | 3 | Claude builds, you review | DONE (Apr 16) |
| Add `BlogPosting` + `FAQPage` JSON-LD to all 10 existing blog posts | 2 | Claude | TODO |
| Merge PR #629 (PA U10 Boys spoke) | 0.5 | You | TODO |

**Deliverable**: Content block template finalized and deployed. Blog JSON-LD still pending.

**Notes**: Week 1 + Week 2 were compressed — design AND implementation shipped on day 1 (PR #633). The 5-module system is more ambitious than originally planned: includes biggest movers (weekly-changing content), clickable team links with `?highlight=` params, and FAQPage JSON-LD. Remaining Week 1 items (blog JSON-LD, PR #629 merge) carry into the next session.

### Week 2 (Apr 23–29): QA + Cross-Linking + Ranking-to-Blog Bridge

*Week 2 scope updated: programmatic content already deployed (was originally Week 2). Replaced with cross-linking + meta work pulled forward from Week 3.*

| Task | Hours | Who | Status |
|---|---|---|---|
| QA: spot-check 10 ranking pages across states/ages for correct module rendering | 2 | You | TODO |
| Add "Related Guide" component to ranking pages — links to matching state pillar blog post if one exists | 3 | Claude | TODO |
| Add ranking page links INTO existing blog posts (each state pillar links to its top 5 ranking pages by age) | 2 | Claude | TODO |
| Implement `?highlight=` scroll-to-team behavior in RankingsTable for clickable movers | 2 | Claude | TODO |

**Deliverable**: Two-way blog<->ranking linking live. Movers fully interactive.

### Week 3 (Apr 30–May 6): Meta Descriptions + GSC Resubmission

*Cross-linking pulled forward to Week 2. This week focuses on meta descriptions + resubmission.*

| Task | Hours | Who | Status |
|---|---|---|---|
| Write curated meta descriptions for 20 more high-population states | 2 | Claude | TODO |
| Add `BlogPosting` + `FAQPage` JSON-LD to all existing blog posts (carried from Week 1) | 2 | Claude | TODO |
| Submit all enriched ranking page URLs to GSC for re-crawl (sitemap resubmission) | 0.5 | You | TODO |
| Write curated meta descriptions for remaining 20 states | 2 | Claude | TODO |

**Deliverable**: All 50 states with curated meta descriptions. Blog JSON-LD live.

### Week 4 (May 7–13): Technical SEO Audit + Remaining Meta

| Task | Hours | Who |
|---|---|---|
| Run PageSpeed Insights on 5 representative ranking pages — fix any CWV issues | 3 | Claude investigates, you verify |
| Write curated meta descriptions for remaining 20 states | 2 | Claude |
| Verify all 1,200+ pages are in XML sitemap and indexed in GSC (check coverage report) | 1 | You |
| Baseline GSC snapshot: record clicks, impressions, avg position for all ranking pages | 1 | Claude pulls via API |
| GSC strike-distance report: find all pages ranking position 5-20 | 1 | Claude |

**Deliverable**: All 50 states have curated meta descriptions. CWV clean. Baseline metrics recorded. Strike-distance list ready.

---

## Phase 2: Content Scale (Weeks 5–10 / May 14 – Jun 24)

**Goal**: Scale from 7 to 21 state pillars. Start authority outreach.
**Estimated hours**: ~60 total (~10/week)

### Week 5 (May 14–20): State Pillars Batch 1

| Task | Hours | Who |
|---|---|---|
| Pull GSC + DB data for TX, CA, NY, VA | 2 | Claude |
| Write + publish TX pillar | 2 | Claude writes, you review/merge |
| Write + publish CA pillar | 2 | Claude writes, you review/merge |
| Submit new URLs to GSC | 0.5 | You |
| First GSC check on Phase 1 programmatic pages | 1 | Claude |

**Deliverable**: 2 new state pillars live (TX, CA). First programmatic content signal check.

### Week 6 (May 21–27): State Pillars Batch 2

| Task | Hours | Who |
|---|---|---|
| Write + publish NY pillar | 2 | Claude |
| Write + publish VA pillar | 2 | Claude |
| Write + publish MD pillar | 2 | Claude |
| Cross-link all 5 new pillars to their ranking pages (both directions) | 1.5 | Claude |

**Deliverable**: 3 more state pillars (NY, VA, MD). 12 total.

### Week 7 (May 28–Jun 3): State Pillars Batch 3

| Task | Hours | Who |
|---|---|---|
| Write + publish GA, IL, OH pillars | 6 | Claude |
| Write 1 informational post (evergreen: "How Youth Soccer Rankings Work" or "Club vs Travel Soccer") | 3 | Claude writes, you review |

**Deliverable**: 15 total state pillars. 1 informational post.

### Week 8 (Jun 4–10): State Pillars Batch 4 + Outreach Begins

| Task | Hours | Who |
|---|---|---|
| Write + publish MA, CT, WA pillars | 6 | Claude |
| Draft outreach email template for state soccer associations | 1 | Claude drafts, you personalize |
| Send first 5 outreach emails (TX, CA, NY, VA, MD associations) | 2 | You |

**Deliverable**: 18 total state pillars. Outreach started.

### Week 9 (Jun 11–17): State Pillars Batch 5 + GSC Deep Review

| Task | Hours | Who |
|---|---|---|
| Write + publish MN, IN, SC pillars | 4 | Claude |
| Full GSC review (8 weeks since programmatic launch): clicks, impressions, new queries on enriched ranking pages | 2 | Claude |
| Identify "winner" ranking pages (jumped in position or impressions) — document for Phase 3 | 1 | Claude |
| Send 5 more outreach emails (GA, IL, OH, MA, WA associations) | 2 | You |

**Deliverable**: 21 total state pillars. 8-week performance review complete.

### Week 10 (Jun 18–24): Informational Content + Outreach Follow-ups

| Task | Hours | Who |
|---|---|---|
| Write 1 informational post (recruiting: "What College Coaches Look For in Youth Soccer Players") | 3 | Claude |
| Write 1 informational post (seasonal: "Fall Soccer Tryouts 2026") | 3 | Claude |
| Follow up on Week 8-9 outreach non-responders | 1.5 | You |
| Identify which state pillars are ranking and which need title/meta tweaks | 1.5 | Claude |

**Deliverable**: 26 total blog posts. Outreach pipeline warm.

---

## Phase 3: Optimize + Spokes (Weeks 11–15 / Jun 25 – Jul 29)

**Goal**: Stop publishing breadth. Optimize what's live based on GSC data. Spokes only where demand is proven.
**Estimated hours**: ~55 total (~11/week)

### Week 11 (Jun 25–Jul 1): Strike Distance Optimization

| Task | Hours | Who |
|---|---|---|
| Re-run strike-distance list with fresh GSC data (pages at position 5-20) | 1.5 | Claude |
| Top 15 strike-distance pages: improve titles, expand content blocks, add FAQ questions, strengthen internal links | 4 | Claude builds, you review |
| Top 5 blog posts by impressions: optimize titles + meta descriptions for CTR | 2 | Claude |
| 5 new outreach emails (non-responding associations + soccer media: SoccerWire, TopDrawerSoccer) | 2 | You |

**Deliverable**: 15 ranking pages optimized. 5 blog SERP snippets improved. Media outreach started.

### Week 12 (Jul 2–8): First Spokes (Data-Driven Only)

| Task | Hours | Who |
|---|---|---|
| GSC data pull: which ranking pages have most impressions + clicks? These earn spokes. | 1 | Claude |
| Write 2 spoke posts for top-performing ranking pages | 4 | Claude |
| Cross-link spokes to pillar + ranking page (both directions) | 1 | Claude |
| Check if Week 11 strike-distance optimizations moved positions | 1 | Claude |

**Deliverable**: 2 data-driven spokes live.

### Week 13 (Jul 9–15): Midpoint Review + GEO Push

| Task | Hours | Who |
|---|---|---|
| **Midpoint performance review**: full GSC comparison Apr 16 vs Jul 9. Save to `.turbo/seo-midpoint-review.md` | 3 | Claude |
| Identify which content types driving growth — double down on winners | 1 | You + Claude |
| GEO audit: search ChatGPT, Perplexity, Google AI Overview for "youth soccer rankings [state]" top 10 states. Document gaps. | 2 | You manually |
| Add `FAQPage` JSON-LD to all ranking pages with programmatic FAQ blocks | 2 | Claude |

**Deliverable**: Midpoint report. FAQ schema on all ranking pages. GEO baseline documented.

### Week 14 (Jul 16–22): Course Correction

| Task | Hours | Who |
|---|---|---|
| Write 2 more pieces of whatever content type is winning (pillars, spokes, or informational) | 4 | Claude |
| If programmatic content is the winner: expand content blocks with new sections | 3 | Claude |
| If outreach is working: follow-ups + new targets. If not: pivot to community seeding (Reddit, Facebook, forums) | 2 | You |
| Second round of strike-distance optimization (next 10 pages) | 2 | Claude |

**Deliverable**: Execution course-corrected based on real data. 10 more pages optimized.

### Week 15 (Jul 23–29): Authority Building Escalation

| Task | Hours | Who |
|---|---|---|
| Write data story: "The 10 Most Competitive U14 Boys States in America" (unique PitchRank data) | 4 | Claude |
| Pitch to 5 soccer media outlets + post on Reddit, Facebook groups | 3 | You |
| Write 2 more spokes for next-best GSC performers | 3 | Claude |
| Outreach status check: tally responses, document backlinks earned | 1 | You |

**Deliverable**: 1 data story published + pitched. 4 total spokes. Backlink pipeline documented.

---

## Phase 4: Scale + Close (Weeks 16–20 / Jul 30 – Sep 1)

**Goal**: Hit the 5,000 target. Time content for September fall-season search surge.
**Estimated hours**: ~50 total (~10/week)

### Week 16 (Jul 30–Aug 5): Fall Season Prep Content

| Task | Hours | Who |
|---|---|---|
| Write "Fall 2026 Youth Soccer Season Preview" (state-by-state seasonal magnet) | 4 | Claude |
| Update/write "2026 Fall Tryout Guide by State" | 2 | Claude |
| Refresh programmatic content on ranking pages with latest summer game data | 2 | Claude |
| 5 outreach emails to youth soccer bloggers/parent influencers | 2 | You |

**Deliverable**: 2 seasonal posts timed for September traffic. Ranking pages refreshed.

### Week 17 (Aug 6–12): Final State Pillars + Spoke Batch

| Task | Hours | Who |
|---|---|---|
| Write 3 more state pillars (pick from GSC data — states with ranking page impressions but no pillar) | 5 | Claude |
| Write 2 spokes for top-performing states from midpoint review | 3 | Claude |
| Cross-link everything | 1.5 | Claude |

**Deliverable**: 24+ state pillars. 6+ spokes.

### Week 18 (Aug 13–19): Technical Re-Audit + Second Data Story

| Task | Hours | Who |
|---|---|---|
| Full technical re-audit: CWV, sitemap, index coverage, crawl errors, soft-404 regression check | 3 | Claude |
| Fix anything found | 2 | Claude |
| Write second data story: "How We Rank 100,000+ Youth Soccer Teams" (methodology E-E-A-T piece) | 3 | Claude |
| Pitch data story + share in communities | 2 | You |

**Deliverable**: Technical health verified. Second data story pitched.

### Week 19 (Aug 20–26): GEO Optimization Sprint

| Task | Hours | Who |
|---|---|---|
| Re-check AI citations for top 15 state queries. Compare to Week 13 baseline. | 2 | You |
| Optimize pillar + ranking page FAQ for states where PitchRank ISN'T cited by AI | 3 | Claude |
| Add `Organization` schema to site-level layout if not present | 1 | Claude |
| Final strike-distance optimization: remaining pages at position 4-10 | 3 | Claude |

**Deliverable**: GEO gaps closed. Final position push.

### Week 20 (Aug 27–Sep 1): Performance Review + Q4 Planning

| Task | Hours | Who |
|---|---|---|
| **Final GSC report**: full comparison Apr 16 vs Sep 1. Save to `.turbo/seo-final-review.md` | 3 | Claude |
| Analyze: did we hit 5,000/month? Trendline? Which content types drove growth? | 1 | Claude + you |
| Document lessons learned for Q4 | 1 | You |
| Draft Q4 SEO plan based on data | 2 | Claude |

**Deliverable**: Final performance report. Q4 plan drafted.

---

## Expected Outcomes by September 1

### Content inventory
- 24–27 state pillars (up from 7)
- 6–8 data-driven spokes
- 7–9 informational/data-story posts
- 1,200+ ranking pages with unique programmatic content, FAQ, JSON-LD

### Technical SEO
- All 50 states with curated meta descriptions
- Two-way internal linking mesh (blog <-> ranking pages)
- `BlogPosting`, `FAQPage`, `RankingTable`, `Organization` structured data across entire site
- Two technical audits (Phase 1 + Phase 4)

### Authority
- 20+ outreach emails to state associations + soccer media
- 2 data stories pitched
- Community presence in Reddit, Facebook groups, parent forums
- Backlink pipeline documented

### Measurement
- Baseline snapshot (Week 4)
- Midpoint review (Week 13)
- Final report (Week 20)
- Q4 plan drafted

### Target
- **5,000+ organic clicks/month** (30x growth from ~165 baseline)
- **Stretch**: rank #1 for `{state} youth soccer rankings` in 10+ states
- **GEO**: PitchRank cited in AI answers for top-10 state queries

---

## Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Programmatic content triggers Google thin-content flags | Low | Each page gets unique data (different team counts, clubs, FAQ answers). QA spot-checks in Phase 1. |
| State pillars cannibalize ranking pages | Medium | Different intent: pillar is informational ("guide"), ranking page is navigational ("see the table"). Monitor GSC for cannibalization signals in Phase 3 midpoint review. |
| 5,000 clicks/month is too aggressive | Medium | Midpoint review at Week 13 is the checkpoint. If trendline says no, recalibrate target and shift effort to highest-ROI channel. |
| Outreach gets zero responses | High | Mitigated by community seeding fallback (Phase 3 Week 14). Data stories are inherently link-worthy even without outreach. |
| Solo operator burnout at 15 hrs/week for 20 weeks | Medium | Weekly hours average 10, never exceed 15. Phases 3-4 are lighter. Course correction week (14) is a natural breather. |

---

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-15 | PA is the first state cluster with spokes | Greenfield + existing ranking pages with 20%+ CTR |
| 2026-04-15 | No "Glicko-2" in user-facing content | Keep brand accessible; use "rating engine" / "rating algorithm" |
| 2026-04-16 | Approach A: Foundation First | Enriching 1,200 pages > writing 4 blog posts in first month |
| 2026-04-16 | Spokes are data-driven only | Only write a spoke when GSC proves the ranking page has demand |
| 2026-04-16 | Free tools only | GSC + PageSpeed + Claude. No Ahrefs/SEMrush budget. |
| 2026-04-16 | 5-module content block (upgraded from original 3-paragraph design) | Feedback: "give every rankings page a real job." Modules: summary w/ hook, top clubs, movers, FAQ, freshness. Movers = weekly-changing content that prevents staleness. |
| 2026-04-16 | Use "group" not "cohort" in user-facing content | Dallas preference — more accessible language |
| 2026-04-16 | Week 1+2 compressed — design + build shipped day 1 (PR #633) | Accelerated timeline means cross-linking pulls forward to Week 2 |

---

## Progress Log

| Date | What shipped | PR |
|---|---|---|
| 2026-04-15 | PA pillar blog post (keyword research + content) | #628 |
| 2026-04-15 | PA U10 Boys spoke post | #629 (open) |
| 2026-04-15 | Remove Glicko-2 from PA pillar | #630 |
| 2026-04-16 | 5-module programmatic SEO content on all 1,200+ ranking pages | #633 |

### Next session pickup

Start with these remaining Week 1-2 items:
1. **Merge PR #629** (PA U10 Boys spoke — still open, has Glicko removal committed)
2. **QA spot-check** 10 ranking pages for correct module rendering (deploy from PR #633 should be live)
3. **Add `BlogPosting` + `FAQPage` JSON-LD** to all 10 existing blog posts
4. **Implement `?highlight=` scroll-to-team** in RankingsTable (clickable movers)
5. **Add "Related Guide" component** — ranking pages link to matching state pillar blog
6. **Add ranking page links** into existing state pillar blog posts
