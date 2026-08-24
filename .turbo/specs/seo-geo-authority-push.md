# SEO/GEO Authority Push

## Overview

PitchRank has won the SEO/GEO foundation phase: organic traffic is ~5,175 clicks / 28 days (past the 5,000/mo goal ~11 weeks early), indexation has climbed 8× to ~45%, and a fresh 264-URL inspection found zero technical SEO defects. The single remaining ceiling on growth is **domain authority** — most of the 900 programmatic ranking pages sit in Google's "Discovered – currently not indexed" bucket (a crawl-budget/trust gate, not a code gate), the head term "youth soccer rankings" is stuck at position 7–10, and AI engines mention PitchRank but still lean on SoccerWire/TopDrawer for some queries.

This project is a deliberate **authority push** that earns off-site trust signals — backlinks and AI citations — which lift both blue-link rankings (SEO) and generative-engine citations (GEO) at once. It leads with a **tiered outreach program** (mostly segment-templated, plus a hand-personalized high-touch tier; ~150–250 verified sends/week) run from a dedicated sending domain, supported by a **keystone first-party data report** ("State of Texas Youth Soccer 2026") that is inherently link- and citation-worthy, and a lighter **Organization E-E-A-T** strengthening pass. The target is a measurable lift in referring domains and AI-citation rate by the **September 1, 2026** SEO+GEO scorecard. Operated solo at ~15 hrs/week.

## Users

This is an internal growth program; its "users" are the operator and the downstream audiences the assets serve.

- **Operator (Dallas, solo, ~15 hrs/wk):** needs a repeatable, low-manual-overhead system to send outreach at volume without damaging the main domain, and to know what's working.
- **Outreach recipients (link sources):** state soccer association webmasters, club directors/DOCs, youth-soccer media editors (SoccerWire, TopDrawer, SBNation desks), and parent-audience bloggers/influencers. They link when given something genuinely useful to their audience (data, a story, a resource).
- **End beneficiaries (PitchRank's audience):** competitive youth-soccer parents who find PitchRank via the higher-authority pages and AI answers the push unlocks.

## Requirements

### Outreach program (lead workstream)

- **R1.** Where cold outreach is sent, the system shall send it from a dedicated secondary domain (e.g. `getpitchrank.com`), never from `pitchrank.io`, to protect the primary domain's sender reputation and deliverability.
- **R2.** When the sending domain is provisioned, the operator shall configure SPF, DKIM, and DMARC and run an automated warmup (via the chosen cold-email tool) for at least 2–3 weeks before batched sending begins.
- **R3.** The system shall ramp send volume gradually (start ≤20/day, increase as warmup/reputation allow) toward the batched target of ~150–250 verified sends/week (the tiered mix in R7), rather than blasting 50+/day from a cold domain on day one.
- **R4.** While batched sending is active, the system shall monitor bounce rate, spam-complaint rate, and inbox placement (via the Instantly warmup pool and/or a seed-list inbox test), and auto-pause the campaign when bounce exceeds ~3% or spam complaints exceed ~0.1%, resuming only after the offending list/segment is remediated. This is the observed-health stop that makes R3's ramp safe rather than a guess.
- **R5.** The system shall maintain a target list sourced via the existing ZenRows/Scrapy stack plus email enrichment, segmented into at least: (a) state associations, (b) clubs/DOCs, (c) youth-soccer media, (d) parent bloggers/influencers.
- **R6.** Before any address enters a send batch, the system shall verify it in real time (e.g. NeverBounce/ZeroBounce/Hunter verifier); a batch ships only when its invalid/unverifiable rate is below ~2–3%. Enrichment alone (pattern-guessed addresses) is not sufficient — verification is a gating step on the list, because scraped club/association domains routinely carry 10–30% invalid addresses that would otherwise burn the domain via R4.
- **R7.** As the operator, I want each segment to have its own templated sequence with real personalization tokens (not `{{FirstName}}`-only swaps) so that emails connect to the recipient's situation and avoid spam/AI-template patterns.
  - Acceptance: each template's personalized opening, if removed, would break the email's logic (personalization is load-bearing).
  - Acceptance: templates avoid the banned-phrase list ("leverage", "synergy", "best-in-class", "I hope this finds you well", "Glicko-2", "cohort") per `.agents/product-marketing.md`.
  - Tiering (resolves the batched-vs-personalization tension on a 15-hr/wk budget): the ~150–250 verified sends/week split roughly **80% segment-templated** (associations, clubs, bloggers — personalized via scraped tokens) and **~20% hand-personalized high-touch** for media and top-value targets. The Sept-1 +15–25 referring-domain target (R21) is sized to this throughput.
- **R8.** Each outreach sequence shall be 3–5 emails with increasing gaps, each adding a new angle (no "just checking in"), ending in a breakup email, with a single low-friction interest-based CTA per email.
- **R9.** The system shall lead with three offer angles: (a) **editorial data stories** (newsworthy cuts journalists can cite), (b) a **static data snippet** (copy-paste HTML block or branded image — e.g. "Top 10 [State] U14 teams, via PitchRank" — carrying an attribution backlink), and (c) **resource-page listing** requests.
- **R10.** Where the static data snippet (R9b) and resource-page asks (R9c) are used, the system shall use branded or varied anchor text (not exact-match keyword anchors), prefer editorial in-content links over identical templated embeds, and cap the share of total earned links that come from identical snippet markup — to stay within Google's link-scheme guidance and avoid links being discounted or triggering a manual action.
- **R11.** If the outreach program's reply rate stays below ~1–2% after the first ~3–4 weeks of batched sending (~600 verified sends — a large enough sample to judge a ~1–2% reply rate), then the operator shall pivot effort to community seeding (r/youthsoccer, parent Facebook groups, forums) and rely on the report's inherent link-worthiness.

### Keystone report

- **R12.** The system shall publish "State of Texas Youth Soccer 2026" (~2,000 words) drawing real numbers from `rankings_full`: top movers, conference/league parity analysis, age-group depth comparison, and ≥1 callout per ECNL/NL/EA division.
- **R13.** The report shall include a methodology disclosure and first-party-data framing ("Per PitchRank's analysis of N competitive matches…") so it is citable as a primary source by both press and AI engines.
- **R14.** Before publishing, the system shall verify — by querying the database at build time — that Texas coverage clears a defined credibility floor (minimum analyzed-match count, ranked-team count, and league coverage spanning ECNL/NL/EA), and shall fall back to a better-covered state if Texas does not clear it. A thin report pitched to soccer editors damages credibility rather than building it, so the floor is a publish gate.
- **R15.** The report's data pipeline and page structure shall be templated so future editions (other states; Summer/Fall updates) can be produced cheaply, per the quarterly cadence in the GEO playbook.
- **R16.** When the report is live, the system shall pitch it to the media segment and seed it (neutral, data-first tone) on r/youthsoccer under a named PitchRank account.

### Entity / E-E-A-T

- **R17.** The system shall strengthen the existing `pitchrank-team` **Organization** entity's E-E-A-T signals (founding facts, methodology linkage, scale proof points, `sameAs` to Wikidata) without introducing a personal Person entity, per the operator's privacy choice.
- **R18.** Where the report and outreach assets carry a byline, the byline shall attribute to the Organization, consistent with the no-fabrication rule. (A named credentialed contributor was considered and explicitly deferred out of MVP; the GEO author-veto ceiling is accepted for now.)

### Measurement

- **R19.** The system shall track the full funnel — pitches sent → replies → links/citations earned — in a Supabase table (or equivalent owned store), one row per target with status transitions.
- **R20.** The system shall measure backlink growth via the GSC Links report and AI-citation rate via the existing GEO recheck script (`.turbo/geo/_recheck_geo.py`), captured as a baseline at **week 0 before any sending begins** and re-measured for the Sept 1 scorecard.
- **R21.** The system shall define the Sept 1 scorecard with explicit targets for net-new referring domains, indexation rate, and per-engine AI-citation rate (OpenAI/Gemini), and shall count referring domains such that outreach-attributable links (tracked in R19's `outreach_targets`) are distinguished from organically acquired ones — otherwise the scorecard cannot tell whether the program worked versus natural authority growth already underway.

## Design

### Architecture / workstream split

Three loosely-coupled workstreams, sequenced so the report becomes ammunition for the highest-value outreach:

1. **Outreach engine** (infra + list + templates + cadence + tracking) — starts first; low-tier targets (resource pages, associations) can be pitched with existing pillars/methodology as the hook while the report is built.
2. **Keystone report** — built in parallel; on publish, becomes the lead asset for the media/blogger segments and the GEO primary-source play.
3. **Organization E-E-A-T** — smallest; a JSON-LD/content pass that runs independently.

### Sending infrastructure (R1–R4)

- Secondary domain (suggested `getpitchrank.com`; final name TBD at implementation), DNS/auth (SPF/DKIM/DMARC) configured, routed through **Instantly** (~$37+/mo) for built-in auto-warmup and inbox rotation. Primary `pitchrank.io` mail untouched.
- Warmup 2–3 weeks; volume ramp ≤20/day → batched target. This is what makes "automated/batched" safe for a young brand.
- **Deliverability guardrail (R4):** Instantly's reporting (plus a periodic seed-list inbox-placement test) feeds a hard pause — if bounce >~3% or spam complaints >~0.1%, sending halts until the segment is cleaned/re-verified. This bounds the blast radius of a bad list.

### Target list + verification (R5–R6)

- Reuse the owned ZenRows/Scrapy scraping stack to crawl: state association sites (all 50), large clubs, and media/blog mastheads. Enrich emails (Hunter or manual).
- **Real-time verification gate (R6):** every enriched address is verified (NeverBounce/ZeroBounce/Hunter verifier) before it enters a batch; a batch with >~2–3% invalid is held and cleaned first. Store all targets in the Supabase tracking table (R19) with a `segment` column and a verification status.

### Outreach content (R7–R11)

- Per-segment sequences authored in PitchRank brand voice (expert-peer, anti-hype, "you"-focused) per `.agents/product-marketing.md`. Personalization tokens pull from scraped signals (state, league mix, a specific team/standing). CTAs are interest-based ("Worth a look for your members?").
- **Tier split (R7):** of ~150–250 verified sends/week, ~80% is segment-templated-with-tokens (associations, clubs, bloggers) and ~20% is hand-personalized high-touch (media, top-value targets). This keeps the program inside the 15-hr/wk budget while preserving load-bearing personalization where it matters most.
- Offer assets: (a) editorial data-story angles derived from the report and weekly movers; (b) a static data-snippet generator (lightweight — a copy-paste HTML block and/or a branded PNG per state with an attribution link, reusing existing OG/infographic tooling rather than a new interactive embed); (c) a short resource-page pitch.
- **Link-scheme guardrail (R10):** snippet/embed links use branded anchors ("via PitchRank") or natural variation, never exact-match keyword anchors; editorial in-content links are preferred over identical embeds, and identical-snippet links are kept a minority of the earned-link mix.

### Keystone report (R12–R16)

- Content + light code. Data extracted from `rankings_full` and the existing state-cohort **movers RPC** (`get_biggest_state_movers`, shipped via #873/#878) for TX. Published as a report page (not a leaderboard) with methodology disclosure and structured data. Pipeline parameterized by state + window so re-runs are cheap.
- **Credibility gate (R14):** a build-time query confirms TX clears the analyzed-match / ranked-team / league-coverage floor; if not, the pipeline targets a better-covered state. This keeps the press-pitched asset statistically defensible.
- Distribution: media-segment pitch (SoccerWire, TopDrawer, SBNation TX desk, AZ/TX beat reporters) + neutral r/youthsoccer seed.

### Entity / E-E-A-T (R17–R18)

- Enrich the homepage/author `Organization` JSON-LD: `foundingDate`, `knowsAbout`/methodology link, scale proof points, and `sameAs` (Wikidata Q139785143, social profiles). No personal `Person` node, and no contributor byline in MVP. The known GEO author-veto ceiling is an accepted MVP limitation.

### Measurement (R19–R21)

- **Tracking store:** Supabase table `outreach_targets` (segment, org, contact, verification_status, status enum: queued → verified → sent → replied → linked/declined, link_url, notes, timestamps). Owned, queryable, no SaaS cost.
- **Baseline at week 0 (R20):** capture GSC Links + the GEO `_recheck_geo.py` panel before the first send, so the Sept 1 delta is valid.
- **Backlinks:** GSC Links report (primary); optionally a free webmaster-tools tier later.
- **AI citations:** existing `_recheck_geo.py` panel (OpenAI + Gemini).
- **Attribution (R21):** referring domains are split into outreach-attributable (cross-referenced against `outreach_targets`) vs organic, so the program's effect is isolated from authority growth already in motion.
- **Scorecard (confirmed targets):** +15–25 net-new referring domains by Sept 1; indexation ≥60%; OpenAI citation ≥75% and Gemini ≥75% on the 20-prompt panel.

### Key flow (baseline → report → outreach → measurement)

1. Capture week-0 baseline (GSC Links + GEO panel). Provision sending domain + warmup (background, weeks 1–3).
2. Scrape → enrich → **verify** → segment target list → `outreach_targets`.
3. Build TX report; run the credibility gate; publish with methodology + structured data.
4. Launch sequences with deliverability + link-scheme guardrails: low-tier segments early (pillar/methodology hook), media/blogger segments on report publish (report hook + data snippet).
5. Log every transition; re-measure GSC Links + GEO panel at midpoint and Sept 1, splitting attributable vs organic links.

## MVP Scope

**In:** sending infra + warmup + deliverability guardrail; scraped/segmented/**verified** target list; per-segment templated sequences with the 3 offer angles and link-scheme guardrail; the TX keystone report (credibility-gated, templated to repeat); Organization E-E-A-T enrichment; the Supabase tracking table + week-0 baseline and Sept 1 scorecard with attribution split.

**Deferred:** interactive embeddable widget (start with static snippet, upgrade only if uptake is strong); additional state reports and Summer/Fall editions (pipeline ready, content later); Wikipedia article (gated on ≥3 secondary sources the press push must generate first); paid backlink tooling (Ahrefs/Semrush) unless free stack proves insufficient; any personal Person entity or named contributor byline; final sending-domain name (resolve at implementation).
