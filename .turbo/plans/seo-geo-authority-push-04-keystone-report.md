---
status: done
spec: C:/PitchRank/.turbo/specs/seo-geo-authority-push.md
---

# Plan: Keystone Report — "State of Texas Youth Soccer 2026"

## Context

The keystone report is the highest-leverage asset in the push: a first-party data report that is inherently link-worthy (earns backlinks from press) and citable as a primary source (lifts GEO). It draws real numbers from `rankings_full` and the state-cohort movers RPC, ships with a methodology disclosure and first-party framing, and is built on a templated pipeline so future states and Summer/Fall editions are cheap. A build-time credibility gate ensures the data is statistically defensible before it is pitched. This shell is independent of the outreach infra and can be built in parallel; its published output is consumed by the campaign shell for distribution.

**Resolved at expansion:**
- **Compute model:** a build-time Python generator (modeled on `scripts/marketing_pipeline.py`) emits a committed data module the static blog post imports. This matches the repo convention that all blog content is static JSX with no request-time data fetching, and keeps exact counts off the anon request path (the reason `homepage_stats_cache` exists).
- **Publish path:** a new programmatic TSX entry in `frontend/content/blog-posts.tsx` (cloned from the existing Texas guide), served at `/blog/state-of-texas-youth-soccer-2026` via `frontend/app/blog/[slug]/page.tsx`. No route wiring needed (adding a `BlogPost` auto-registers).
- **Structured data:** a new `DatasetSchema.tsx` (no `Dataset` schema exists yet) plus the existing `BlogPostSchema` (BlogPosting), both attached in `app/blog/[slug]/page.tsx`.
- **Credibility floor:** `>= 2,000` ranked teams AND `ECNL`/`NL`/`EA` each present (`>= 5` ranked teams). The generator hard-fails (`raise SystemExit`) if the requested `--state` is below the floor; the operator re-runs with a qualifying state. There is **no silent substitution** — the slug, title, data-module filename, methodology copy, and Dataset URL all derive from the emitted `--state`/`--year`, so output can never be mislabeled. TX clears the floor (8,014 ranked teams across 18 groups; ECNL 170 / ECNL_RL 774 / NL 29 / EA 7).
- **Content constraints:** first-party "we analyzed N matches" framing; "rating engine"/"PowerScore" (never "Glicko-2"); "group" not "cohort"; "Boys"/"Girls"; no PowerScore tier thresholds; no fabricated features. EA's thin TX footprint (7) gets a smaller callout.

## Pattern Survey

### Analogous Features
- `frontend/lib/cohort-seo.ts:28` — `computeCohortModules()`: derives per-cohort stats (total active teams, top-5 clubs by team count, risers/fallers via `rank_change_state_7d`, last-game/last-calculated, a `getPositioningHook()` size band) from a `RankingRow[]`. The existing pattern for turning raw `rankings_full` rows into a display-ready stats object; `buildCohortFAQ()` (line 145) emits FAQ pairs.
- `scripts/marketing_pipeline.py:194` — `fetch_ranking_highlights()` + `fetch_state_movers()` (line 811) + `fetch_age_group_movers()` (line 794): the canonical build-side stats generators (`create_client`, `supabase.table("rankings_full").select(...)`, the `teams` join for names at line 177 since `rankings_full` has no `team_name`, and `supabase.rpc("get_biggest_state_movers", {...})`); assembles a `data` dict consumed by `generate_blog_post()` (line 829).
- `frontend/app/api/infographic/state/route.tsx:21` — `getStateTopTeams()`: request-time fetch of a (state, age, gender) cohort via `supabase.rpc('get_state_rankings', ...)` (the request-time precedent, not chosen here).
- `frontend/content/blog-posts.tsx:1875` — the existing Texas guide (`texas-youth-soccer-rankings-guide`): fully static JSX with hardcoded numbers. No blog post currently fetches live data — the clone target for structure and voice.
- `supabase/migrations/20260615200000_homepage_stats_cache.sql` — `refresh_homepage_stats()` + `get_db_stats()`: precedent for precomputing slow exact counts into a cached singleton rather than counting on the request path.

### Reusable Utilities
- `frontend/lib/utils.ts:44` — `formatLeague(league)` (maps `teams.league` via `LEAGUE_DISPLAY`); `composeTeamDisplay()` (line 157) builds "{club} {league} {distinction}" with the `distinctionHasLeakage()` guard (line 136). For per-team league/distinction labels.
- `frontend/lib/constants.ts:163` — `formatGender(gender)` → "Boys"/"Girls".
- `frontend/lib/schema-utils.ts:6` — `safeJsonLd(data)`: XSS-safe JSON-LD serializer every schema component uses. The new `DatasetSchema` must use it.
- `frontend/lib/constants.ts:61,92,105` — `BASE_URL`, `PITCHRANK_TEAM_AUTHOR`, `PITCHRANK_PUBLISHER`: shared author/publisher entities for both Dataset and BlogPosting schema.
- RPC `get_biggest_state_movers(p_state, p_limit, p_direction, p_days, p_age_group, p_gender, p_max_state_rank)` — `supabase/migrations/20260605000001_create_get_biggest_state_movers.sql`; returns `{team_id, team_name, club_name, state_code, rank_change, current_rank}`, already filters Active + `games_played >= 8` + not-deprecated, ranks within the state cohort.
- `frontend/lib/api.ts:90,197,265` — `get_state_rankings` / `get_state_rankings_count` / `get_state_active_count` RPCs: timeout-safe cohort rows + exact counts.
- `frontend/lib/cohort-seo.ts:145,116,138` — `buildCohortFAQ()`, `STATE_PILLAR_SLUGS`, `getRelatedGuide()`: FAQ generation + state cross-link map.

### Convention Anchors
- **Blog post shape:** programmatic posts are objects in `blogPosts: BlogPost[]` in `frontend/content/blog-posts.tsx` (array starts line 27); the `BlogPost` interface is `frontend/lib/blog.tsx:6` (`slug, title, excerpt, content: React.ReactNode, date, modifiedDate?, author, readingTime?, tags?, image?`). `getAllBlogPosts()` (blog.tsx:60) merges TSX + MDX; `getAllBlogSlugs()` (line 78) feeds `generateStaticParams`. Adding a TSX entry auto-registers the route.
- **Schema component convention:** each `components/*Schema.tsx` takes typed props, builds a plain object with `'@context': 'https://schema.org'` + `'@type'`, returns `<script type="application/ld+json" dangerouslySetInnerHTML={{ __html: safeJsonLd(schema) }} />`. `DatasetSchema.tsx` mirrors `BlogPostSchema.tsx`.
- **Schema attachment:** `frontend/app/blog/[slug]/page.tsx:82-99` renders `<BlogPostSchema {...post}/>`, `<BreadcrumbSchema items=[Blog, post.title]/>`, and conditional `<BlogFAQSchema faqs={BLOG_FAQS[slug]}/>` (keyed by slug in `frontend/lib/blog-faqs.ts`). Add the Dataset schema here keyed by slug.
- **Build-time vs request-time:** two precedents — Python script writes a static artifact (`marketing_pipeline.py`, run by `.github/workflows/marketing-pipeline.yml`) vs route fetch via RPC (`infographic/state/route.tsx`). The blog system has no precedent for fetching data into a post, and there is no existing build-time credibility gate.
- **Brand voice:** "rating engine"/"PowerScore" (never "Glicko-2"); "group" not "cohort"; "Boys"/"Girls" via `formatGender`; no PowerScore tier thresholds; first-party "we're tracking N teams" framing.

### Proposed Alignment
Generate the report's numbers with a state-parameterized Python script modeled on `marketing_pipeline.py`'s fetch helpers (same `create_client` + `rankings_full` select + `teams` join + `get_biggest_state_movers` RPC), emitting a committed TS data module the static blog post imports — matching the static-JSX convention and keeping exact counts off the request path. Reuse the `computeCohortModules`/`buildCohortFAQ` shapes for derived stats and `formatGender`/`formatLeague`/`composeTeamDisplay` for labels. Add a new `DatasetSchema.tsx` mirroring `BlogPostSchema.tsx` (`safeJsonLd` + constants). The credibility gate is new: implement it as a `raise` in the generator before it writes the data module, not in the render path.

## Implementation Steps

1. **Build the state-parameterized report generator** (`scripts/generate_state_report.py`, modeled on `scripts/marketing_pipeline.py` `fetch_ranking_highlights`/`fetch_state_movers`/`fetch_age_group_movers`)
   - `argparse` CLI `--state TX --year 2026 --window-days {7,30}` (mirror the inline `load_dotenv(.env.local)`+`load_dotenv(.env)` + `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)` convention). **Constrain `--window-days` to `{7, 30}`** — `get_biggest_state_movers` only buckets `p_days <= 7` (uses `rank_change_state_7d`) vs `> 7` (uses `rank_change_state_30d`); any other value silently maps to the 30-day delta. The emitted provenance records the bucket actually used.
   - **Derive identifiers from `--state`/`--year`:** `state_name` (e.g. "Texas") and `year` drive the slug (`state-of-<state-slug>-youth-soccer-<year>`), title, data-module filename, and Dataset URL — nothing is hardcoded to Texas.
   - **Counts must not truncate (supabase-py caps a plain `.select()` at ~1,000 rows; TX has ~8,014).** Compute per-group (age x gender) and per-league counts with **server-side aggregation** — grouped SQL (`GROUP BY` via an RPC / `execute_sql`) or `count="exact"` per group — not by pulling all rows. Only fetch **bounded top-N lists** as rows (top movers via `supabase.rpc("get_biggest_state_movers", {"p_state", "p_limit", "p_direction", "p_days": bucket})` up and down; a top team per `ECNL`/`NL`/`EA` by joining `teams` on `team_id_master = rankings_full.team_id` reading `teams.league`). If any unbounded row pull is unavoidable, range-paginate explicitly.
   - **`matchesAnalyzed` (defined precisely, no fabrication):** count from the `games` table over the **ranking window** (~365 days, NOT the 7/30-day movers window), guarded by `is_excluded = false` AND futsal excluded (per the project's futsal-in-rankings gotcha), counting games involving a team from the target state. If a precise games count proves infeasible at implementation, fall back to **ranked-team-only** framing (drop the "N matches" claim) rather than invent a number.
   - Emit a committed TS data module `frontend/content/reports/<derived-slug>.ts` exporting `export const report = { ...stats } as const` (write JSON-serialized stats into the TS template), plus a provenance block (`generatedAt`, `windowBucket` in {7,30}, `temporalCoverage` ISO 8601 interval, `matchesAnalyzed`, `rankedTeams`) for the methodology line and Dataset schema.

2. **Implement the credibility gate** (in `scripts/generate_state_report.py`, before writing the data module)
   - Module constants `MIN_RANKED_TEAMS = 2000` and `REQUIRED_LEAGUES = {"ECNL", "NL", "EA"}` with `MIN_PER_REQUIRED_LEAGUE = 5`.
   - If the requested `--state` is below the floor, **`raise SystemExit` with a clear message naming the failed criterion** and write nothing. No silent substitution: the operator re-runs with a qualifying state. (This keeps the emitted state and all derived identifiers in lockstep, so a published report can never carry one state's title over another's data.)

3. **Write the report** (new `BlogPost` entry in `frontend/content/blog-posts.tsx`, cloned from the Texas guide at line ~1875; import the generated `report` data module)
   - `slug` = the derived `state-of-texas-youth-soccer-2026` (from `--state TX --year 2026`), `title`, `excerpt`, `author: PITCHRANK_TEAM_AUTHOR`-aligned byline, `date`, `tags`, `content` JSX (~2,000 words). All identifiers come from the data module's provenance, never hardcoded literals.
   - Sections built from the imported `report`: top movers, league/conference parity, age-group depth, `>= 1` callout per ECNL/NL/EA (EA framed as the smaller TX footprint), and a methodology disclosure built from the **defined** provenance ("Per PitchRank's analysis of {matchesAnalyzed} matches across {rankedTeams} ranked teams ..."; if `matchesAnalyzed` was dropped per Step 1, frame around `rankedTeams` only) plus first-party framing. Use `formatGender`/`formatLeague`/`composeTeamDisplay` for labels; "group" not "cohort"; "rating engine"/"PowerScore" not "Glicko-2"; no tier thresholds.
   - Add a `BLOG_FAQS["state-of-texas-youth-soccer-2026"]` entry in `frontend/lib/blog-faqs.ts` (methodology / "how are rankings calculated" / data-window questions), mirroring `buildCohortFAQ` phrasing.

4. **Publish with structured data** (`frontend/components/DatasetSchema.tsx` + wire-up in `frontend/app/blog/[slug]/page.tsx`)
   - New `DatasetSchema.tsx` mirroring `BlogPostSchema.tsx`: `@type: "Dataset"` with `name`, `description`, `creator`/`publisher` = `PITCHRANK_PUBLISHER`, `license` (the site content-license URL), `temporalCoverage` as an **ISO 8601 interval** from provenance (e.g. `2025-12-20/2026-01-19`) matching the bucket window, `dateModified`, `variableMeasured` (ranked teams, `matchesAnalyzed`, leagues covered), `isAccessibleForFree: true`, `url` = `${BASE_URL}/blog/<derived-slug>`, plus a `distribution` (a `DataDownload` with `contentUrl` = the page URL and `encodingFormat: "text/html"`) so the dataset advertises an accessible distribution rather than reading as "just the page"; serialize via `safeJsonLd`.
   - In `app/blog/[slug]/page.tsx`, render `<DatasetSchema>` for the report slug alongside the existing `<BlogPostSchema>` + `<BreadcrumbSchema>` (keyed by slug like `BlogFAQSchema`, so it only emits on report pages). Numbers are static (imported at build), so no async section / no SSR `animate-pulse` skeleton is needed; keep SEO content server-rendered before any client component.

## Verification

- **Generator + gate:** `python scripts/generate_state_report.py --state TX --year 2026 --window-days 30` writes `frontend/content/reports/state-of-texas-youth-soccer-2026.ts` with real numbers; spot-check that ranked-team total (~8,014), a top mover, and the ECNL/NL/EA callouts match direct `rankings_full` / `get_biggest_state_movers` queries against project `pfkrhmprwxtghtpinrot`. Confirm `matchesAnalyzed` equals a direct `games`-table count over the ranking window with the `is_excluded = false` + futsal-excluded guards. Run with a deliberately under-covered state and confirm the gate `raise SystemExit`s and writes nothing (no silent substitution, no mislabeled output).
- **Build + render:** `cd frontend && npm run build` succeeds; `/blog/state-of-texas-youth-soccer-2026` renders ~2,000 words, server-rendered SEO content appears before any client component, and there is no SSR `animate-pulse` (no Soft-404 risk).
- **Structured data:** view source shows valid `BlogPosting` + `Dataset` JSON-LD (passes a schema validator); `author` resolves to the `pitchrank-team` entity; `canonical` = `${BASE_URL}/blog/state-of-texas-youth-soccer-2026`.
- **Content rules:** grep the three committed surfaces — the new `BlogPost` entry in `frontend/content/blog-posts.tsx`, the generated `frontend/content/reports/<slug>.ts` data module, and the `frontend/lib/blog-faqs.ts` entry — for forbidden strings ("Glicko", "cohort") and confirm "Boys"/"Girls" labeling. Grep a positive anchor for the methodology line (literal prefix "Per PitchRank's analysis of"). The semantic rules (no PowerScore tier thresholds; first-party framing present; `>= 1` ECNL/NL/EA callout) are verified by **reading the rendered report section**, not by grep.
- **Template reuse (risk):** confirm the generator is genuinely state-and-window-parameterized (running `--state <other>` produces a parallel data module) so future editions are cheap; note in Risks if any TX-specific assumption leaked into the script or the TSX.

## Context Files

- `scripts/marketing_pipeline.py` — the build-time stats-generator pattern to model the new script on (`fetch_ranking_highlights` ~194, `fetch_state_movers` ~811, `fetch_age_group_movers` ~794, the `teams` join ~177, `generate_blog_post` ~829).
- `frontend/lib/cohort-seo.ts` — `computeCohortModules` (~28) + `buildCohortFAQ` (~145): the stats-shaping + FAQ patterns to reuse.
- `frontend/content/blog-posts.tsx` — the `blogPosts` array + the existing Texas guide (~1875) to clone for structure and voice.
- `frontend/lib/blog.tsx` — the `BlogPost` interface (~6) + `getAllBlogPosts`/`getAllBlogSlugs` merge.
- `frontend/app/blog/[slug]/page.tsx` — schema attachment + `generateMetadata` (~26-99) for wiring the Dataset schema.
- `frontend/components/BlogPostSchema.tsx` — the schema-component shape the new `DatasetSchema.tsx` mirrors.
- `frontend/lib/schema-utils.ts` + `frontend/lib/constants.ts` — `safeJsonLd`, `BASE_URL`, `PITCHRANK_TEAM_AUTHOR`, `PITCHRANK_PUBLISHER`.
- `frontend/lib/utils.ts` — `formatLeague` (~44), `composeTeamDisplay` (~157); `frontend/lib/constants.ts` `formatGender` (~163).
- `supabase/migrations/20260605000001_create_get_biggest_state_movers.sql` — the movers RPC contract.
- `supabase/migrations/20260615200000_homepage_stats_cache.sql` — the exact-count caching precedent (reference if any count must move off the build path).
