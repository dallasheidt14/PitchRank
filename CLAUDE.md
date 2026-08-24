# CLAUDE.md — PitchRank AI Assistant Guide

PitchRank is a **youth soccer ranking platform** that scrapes game data from multiple providers, calculates rankings with a two-pass Glicko-2 rating engine plus an XGBoost residual layer (ML Layer 13), and serves results through a Next.js frontend. This file is the primary reference for AI assistants working in this codebase.

---

## Quick Reference

| Item | Value |
|------|-------|
| **Backend** | Python 3.11, Supabase (PostgreSQL) |
| **Frontend** | Next.js 16.2, React 19, TypeScript 5.9, Tailwind CSS v4 |
| **ML** | XGBoost, scikit-learn, pandas, numpy |
| **Database** | Supabase (hosted PostgreSQL + PostgREST) |
| **Deployment** | Vercel (frontend), GitHub Actions (backend automation) |
| **Package manager** | pip (backend), npm (frontend) |
| **Primary branch** | `main` |
| **Rankings recalculation** | Weekly (Monday) via GitHub Actions |

---

## Git Discipline
- Never commit to main directly; verify the branch before every commit. `main` requires a PR and the `ci.yml` checks (squash only, no force-push).
- `.claude/hooks/` (wired by `.claude/settings.json`) refuses commit/push on main, blanket staging, force-push, `reset --hard`, whole-file `ruff format`, and `.env` edits. A `BLOCKED:` message is the hook, not a transient error.
- When creating a new branch, use `git checkout -b <branch> origin/main` only when no staged/WIP work exists. If unsure, run `git status` and `git stash list` first.
- After merging a PR, do NOT perform additional merges or git operations unless explicitly asked.
- Sync before analyzing repo state. Work lands on `origin/main` via PRs merged from several machines and agent runs, so this checkout routinely sits weeks behind (38 commits / 4 days, as of 2026-08-22). Any audit, inventory, or "does X exist" question answered against a stale tree will be wrong in both directions: it reports merged work as missing, and flags already-fixed problems as live. Run `git fetch --all --prune` and fast-forward before measuring anything.

## Verification & Regeneration
- After any change to blog content, metadata, or site structure, always regenerate derived files (e.g., llms.txt) before committing.
- When running verification/audit scripts, ensure the script does not match its own output files (exclude report files from scans).

## Scope & Approach Discipline
- Do NOT make changes beyond what was explicitly requested. If you see opportunities for improvement, mention them but wait for approval.
- When diagnosing issues, verify your initial hypothesis with data before proposing or implementing a fix. Do not jump to implementation.
- If the user redirects or corrects your diagnosis, fully abandon the prior theory and start fresh from their correction.
- When estimating data sizes (row counts, backfill scope), query the actual database for counts rather than estimating.
- Automated pipelines and manual operator tools are separate concerns. Do not modify a scheduled, hands-off job to improve a manually-triggered one — fix the manual tool in its own script.
- When a change needs different behavior from a database function shared by several callers, prefer a direct PostgREST query in the calling script. Adding parameters to a Postgres function creates an overload rather than replacing it, so every existing call fails with "function is not unique" until the old signature is dropped, and the drop also wipes its GRANTs.

## Data Accuracy
- Never fabricate or guess external identifiers (Wikidata Q-numbers, API entity IDs, etc.). Always look them up.
- When querying analytics APIs (GSC, GA4), be aware of privacy thresholds and dimension limitations. If numbers seem low, check whether the query dimension is causing undercounting and try aggregate queries.
- When referencing project status from memory, verify against actual current state before reporting. Flag if your info may be stale.

---

## Repository Structure

```
PitchRank/
├── src/                    # Core Python backend (rankings, ETL, matching)
│   ├── api/                # REST API endpoints
│   ├── etl/                # ETL pipelines + Glicko-2 ranking engine (v53e legacy)
│   ├── models/             # Game/team matching (fuzzy, provider-specific)
│   ├── rankings/           # Ranking orchestration, ML Layer 13, data adapter
│   ├── scrapers/           # Web scrapers (GotSport, SincSports, AthleteOne, Surf)
│   ├── providers/          # External API clients
│   ├── predictions/        # ML match prediction (XGBoost)
│   ├── identity/           # Team identity resolution
│   ├── utils/              # Merge resolver, club normalizer, validators
│   └── base/               # Abstract base classes
│
├── frontend/               # Next.js web application
│   ├── app/                # App Router pages + API routes
│   ├── components/         # React components (shadcn/ui + custom)
│   ├── lib/                # API client, types, utilities, Supabase clients
│   │   ├── api/            # Shared route utilities (requirePremium, parseJsonBody, rateLimit)
│   ├── hooks/              # Custom React hooks
│   ├── types/              # TypeScript type definitions
│   ├── e2e/                # Playwright E2E tests
│   └── middleware.ts       # Auth + route protection
│
├── scripts/                # 158 Python scripts + SQL (import, ranking, hygiene)
├── scrapers/               # Scrapy-based scrapers (Modular11/MLS NEXT)
├── config/                 # Centralized settings.py (299 lines)
├── data/                   # Cache, master data, raw imports, backtests
├── models/                 # ML model artifacts
├── supabase/               # Database migrations (141 files)
├── tests/                  # Python test suite
├── docs/                   # 80 documentation files
├── memory/                 # Investigation notes & working logs
├── .claude/                # Claude agent configs + skills
│   ├── agents/             # Sub-agents: ranking-engine + read-only reviewers
│   ├── hooks/              # Claude Code hooks wired by .claude/settings.json (git guard, secrets, ruff, dry-run, replace-all advisory, session sync)
│   └── skills/             # Domain skills (ranking, scraping, SEO, etc.)
├── .github/workflows/      # 41 automated workflows
├── dashboard.py            # Streamlit admin dashboard (6,180 lines)
└── agent_skills/           # Standalone agent skill packages
```

---

## Domain Knowledge (CRITICAL)

### Age Groups (2026-27 Season)

> Rolled over on 2026-08-01. US youth soccer runs on an Aug 1 – Jul 31 window, so
> every cohort moved up one and 2006 aged out. 2007 now sits at the top of U19,
> which is what the table below says and what
> `calculate_age_group_from_birth_year(2007)` returns. A birth year maps to a different
> cohort than it did last season — check the season before trusting any older
> mapping you find in code comments or docs.

| Birth years (Aug 1 - Jul 31) | Real-world | PitchRank |
|---|---|---|
| 2018 / 2017 | U9  | u9 |
| 2017 / 2016 | U10 | u10 |
| 2016 / 2015 | U11 | u11 |
| 2015 / 2014 | U12 | u12 |
| 2014 / 2013 | U13 | u13 |
| 2013 / 2012 | U14 | u14 |
| 2012 / 2011 | U15 | u15 |
| 2011 / 2010 | U16 | u16 |
| 2010 / 2009 | U17 | u17 |
| 2009 / 2008 | U18 | **u19** (merged) |
| 2008 / 2007 | U19 | u19 |

A cohort's birth window runs Aug 1 - Jul 31 and so spans two calendar years,
which is why TGS writes divisions like `U12G (AUG 1, 2014 - JULY 31, 2015)`.
A band is named by its **younger** year: that division is U12 because
`2026 - 2015 + 1 = 12`. Reading it from the leading year, 2014, gives U13 and is
wrong. `normalize_team_names._resolve_band` and `scrape_tgs_event.extract_age_group`
both take the younger year. The one parser that still takes the older year,
`scripts/fix_team_age_groups.extract_birth_year`, is gated off in both of its
callers by `AGE_DERIVATION_ENABLED` and says so in its own docstring.

PitchRank deliberately files U18 into U19 rather than running a separate U18
board, so 2009 resolves to `u19`. There are 0 `u18` teams and 26,442 `u19`.
Do not "fix" this by splitting the cohort.

- `14B` = 2014 birth year, Boys = **U13 Male** (NOT U14!)
- `U14B` = U14 age group, Boys = **U14 Male**
- `G2016` = Girls, 2016 birth year = **U11 Female**
- **B/G = Gender (Boys/Girls), NOT part of age number**

The season is derived from the wall clock, not configured:
`src/utils/team_utils.py` `_soccer_season_year()` returns `now.year` from August
onward and `now.year - 1` before it, so `calculate_age_group_from_birth_year`
re-maps itself every Aug 1 with no code change.

**`config/settings.py` `_BIRTH_YEARS` has NOT rolled and now disagrees with that
derivation on all nine entries** — it still says U12 is 2014, and `AGE_GROUPS` is
built from it. The table above documents the wall-clock derivation, which is what
ingestion and matching use. Treat `_BIRTH_YEARS` as stale for cohort questions;
see `.turbo/improvements.md`.

### Gender Normalization

`B/Boys/Boy/Male/M` → `Male` | `G/Girls/Girl/Female/F` → `Female`

### Division Tiers — NEVER merge across tiers

- **ECNL** (Elite) ≠ **ECNL-RL** (Regional League)
- **HD** (High Division) ≠ **AD** (Academy Division)
- Other leagues: DPL, NPL, GA, Premier, Elite, Select, Classic

### Data Providers

| Provider | Code | Method | Scale |
|----------|------|--------|-------|
| GotSport | `gotsport` | REST API | 25K+ teams (primary) |
| TGS | `tgs` | Event scraping | Tournament data |
| Modular11 | `modular11` | Scrapy spider | MLS NEXT/HD leagues |
| SincSports | `sincsports` | HTML scraping | Supplementary |
| AthleteOne | `athleteone` | API client | Conference schedules |

#### TGS U-age divisions are only resolvable from 2026-08-01

Both label styles appear throughout the scrape range: birth year (`B2015`) and
U-age (`BU11`, `GU18/19`). A birth year names the same players forever, so it is
resolvable without knowing the season — though the U-age it maps to still shifts
every Aug 1 (2014 was U12 last season, U13 now). A U-age
names one only against the season that wrote it, and TGS does not say which
season that was, so the label alone is not enough.

2026-08-01 is the date from which a U-age becomes *resolvable*, not the date
those labels start existing. On or after it, the event's own game dates identify
the labelling season. Before it, they do not: event 3430 (Apr 2025) and event
3967 (Sep 2025) both carry U-age divisions whose labels sit two seasons behind
their play dates, which their own team names confirm.

So `scrape_tgs_event.py` resolves a post-cutover U-age against the season its
games fall in, and skips a pre-cutover one rather than guess.
`--u-format-before-cutover` reads the skipped ones as the cutover season for a
manual backfill, and is only safe when the event's team names confirm the cohort.

Resolve against the event, never the wall clock. The weekly chain rescans a fixed
id range indefinitely, so a clock-derived cohort would re-file the same
historical event one group higher every Aug 1.

### Adding a new scraper

When planning a new provider, audit what per-team metadata the source exposes (state_code, club_name, coach, gender, age) BEFORE locking in match/create policy. `state_code` availability is load-bearing — without it, auto-created canonical teams land with NULL state and cannot benefit from location-scoped fuzzy matching downstream.

- If state is only on a per-team detail page (not on the index/flight pages), a two-pass scrape (flights → unique team enrichment) is acceptable when the team count is bounded (~hundreds, not tens of thousands).
- Default to auto-create with full metadata (mirrors SincSports/Affinity-WA/PlayMetrics matchers). Strict review-queue-only is only appropriate when meaningful canonical fields cannot be sourced.
- The matcher subclass writes the alias in its overridden `_match_team` via `self._create_alias(...)`, NOT in the `_create_new_<provider>_team` helper. See `src/models/sincsports_matcher.py:555-640` for the canonical pattern.

---

## Ranking Algorithm (Glicko-2 + ML Layer 13)

Production runs the Glicko-2 engine: `calculate-rankings.yml` calls
`scripts/calculate_rankings.py --ml --force-rebuild --engine glicko`, and `glicko` is the
default everywhere. v53e
(`src/etl/v53e.py`) is the legacy engine, reachable only via `--engine v53e`; nothing in the
Glicko path calls it. Parameters and feature flags live in `src/etl/glicko_config.py` and
`src/rankings/constants.py`; the `rankings-algorithm` skill documents them.

### Pipeline Flow

```
Games (Supabase; 365-day window + 28-day grace taper)
  → Merge Resolution (deprecated → canonical team IDs)
  → Pass 1: Glicko-2 convergence per (age, gender) cohort, no cross-age knowledge
  → Global strength map {team_id: mu} from Pass 1
  → Pass 2: re-run each cohort warm-started from Pass 1; cross-age opponents rated
            from the global map + anchor offset
  → Per cohort, post-convergence: OFF/DEF → SOS (repeat cap + trim) → SCF dampening
            → sigmoid(z-score) → powerscore_core → × provisional_mult → powerscore_adj
  → ML Layer 13 per cohort: powerscore_ml = powerscore_adj + 0.08·ml_norm
  → Pass 3: national/state SOS columns — display only, never feeds PowerScore
  → Same-age evidence gates (SOS-gated ML authority, shrink, play-up bonus, caps)
            → power_score_true
  → power_score_final = power_score_true × AGE_TO_ANCHOR[age]
  → rank_in_cohort_final by power_score_true DESC (Active only) → 7d/30d changes
  → Clip PowerScore columns to [0, 1] → ranking_history → rankings_full + current_rankings
```

### PowerScore

- Column chain in `rankings_full`: `powerscore_core` → `powerscore_adj` → `powerscore_ml`
  → `power_score_true` (post-gates, unanchored) → `power_score_final` (× `AGE_TO_ANCHOR`).
  `rank_in_cohort_final` is the published rank; `national_rank` and `state_rank` are
  always NULL in `rankings_full` (views compute display ranks).
- Two traps: there is no `powerscore` column, and `sos` is on the raw 1500-centred
  scale — the 0.45 / 0.60 gates read `sos_norm`.
- Range: **always 0.0–1.0** (clamped at every stage and before save). Nothing in code
  defines "elite / top tier" bands — the `rankings-algorithm` skill explains how to read
  a score.

### ML Layer 13

- The `--ml` CLI flag is a no-op under Glicko: `Layer13Config` takes `enabled` from
  `ML_CONFIG`, i.e. env `ML_LAYER_ENABLED` (default true). Set it to `false` to run
  without ML. Model, thresholds, and gating live in the `rankings-algorithm` skill.

---

## Key Database Tables (Supabase)

| Table | Purpose | Notes |
|-------|---------|-------|
| `games` | Game records | **Immutable** — never update after import |
| `teams` | Master team registry | UUID primary keys |
| `team_alias_map` | Provider ID → master ID | `match_method`: direct_id, fuzzy, manual |
| `team_merge_map` | Deprecated → canonical ID | Cascade merge support |
| `rankings_full` | All ranking metrics | Primary output table |
| `current_rankings` | Legacy rankings view | Backward compatibility |
| `team_match_review_queue` | Uncertain matches | 0.75–0.90 confidence range |
| `ranking_history` | Historical snapshots | 7d/30d rank change tracking |

### Supabase Patterns

```python
# Pagination (1000-row limit)
supabase.table('games').select('*').range(offset, offset + 999).execute()

# Batch queries (100-ID limit for URI length)
supabase.table('teams').select('*').in_('id', batch_of_100).execute()

# RPC for bulk operations
supabase.rpc('batch_update_ml_overperformance', {'updates': data}).execute()

# Querying team data directly: resolve merges first (team_id_master) —
# deprecated team_id values yield duplicate or missing rows

# games.home_team_master_id / away_team_master_id join teams.team_id_master,
# NOT teams.id — filtering teams by .id returns zero rows for a game's team
supabase.table('teams').select('*').in_('team_id_master', master_ids).execute()
```

---

## Team Matching (3-Tier)

1. **Direct ID** — `team_alias_map` lookup, 100% confidence, O(1)
2. **Fuzzy Match** — Weighted scoring (team name 35%, club 35%, age 10%, location 10%)
   - ≥0.90: auto-approve
   - 0.75–0.90: manual review queue
   - <0.75: reject
3. **Manual Review** — Human verification via `team_match_review_queue`

---

## Development Commands

### Backend (Python)

```bash
# Install dependencies
pip install -r requirements.txt

# Run ranking calculation (engine defaults to glicko)
python scripts/calculate_rankings.py --lookback-days 365

# Dry run (skips the rankings_full save; residuals/history still persist — known gap)
python scripts/calculate_rankings.py --dry-run

# Force rebuild (ignore cache)
python scripts/calculate_rankings.py --force-rebuild

# Run game scraper
python scripts/scrape_games.py

# Import games from CSV
python scripts/import_games_enhanced.py --file <path>

# Run tests
python -m pytest tests/

# Diagnose ranking for specific teams (validates algorithm + simulates path to #1)
python scripts/diagnose_ranking.py <team_uuid> [<team_uuid> ...]
```

### Frontend (Next.js)

```bash
cd frontend

# Install dependencies
npm install

# Development server
npm run dev

# Production build
npm run build

# Lint
npm run lint

# Unit tests (Vitest)
npm run test              # Run once
npm run test:watch        # Watch mode
npm run test:coverage     # With coverage

# E2E tests (Playwright)
npm run test:e2e
npm run test:e2e:smoke    # Smoke tests only
npm run test:e2e:api      # API tests only

# Bundle analysis
npm run analyze
```

---

## GitHub Actions Workflows

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `scrape-games.yml` | Manual dispatch | Bulk GotSport scrape (bootstrap, recovery) |
| `enqueue-yesterday-games.yml` | Daily 7:00 AM UTC | Queue teams whose yesterday games have null scores (priority 2) |
| `enqueue-active-teams.yml` | Daily 10:00 AM UTC | Queue teams active in the last 3 days (priority 2) |
| `enqueue-discovery.yml` | Sun 2:00 PM UTC | Queue teams with no future games (priority 3) |
| `enqueue-safety-net.yml` | Sun 4:00 PM UTC | Queue never-scraped / 90d+ teams (priority 4) |
| `process-missing-games.yml` | Every 15 min | Drain the queue, 40 teams per run |
| `clear-queue.yml` | Manual dispatch | "Help Clear Queue" — bulk drain + teams-table top-up |
| `calculate-rankings.yml` | Mon 12:30 PM UTC | Recalculate rankings (Glicko-2 + ML) |
| `auto-gotsport-event-scrape.yml` | Manual dispatch | Tournament bracket scraping (cron removed 2026-05-17) |
| `tgs-event-scrape-import.yml` | Mon 6:30 AM UTC | TGS event scraping |
| `data-hygiene-weekly.yml` | Mon 11:00 AM UTC | Data cleanup — name normalization, distinction backfill, dupe and queue-match steps (the age step is disabled; see `AGE_DERIVATION_ENABLED`) |
| `unknown-opponent-hygiene-weekly.yml` | Tue 6:00 PM UTC | Resolve "Unknown" opponents |
| `auto-merge-queue.yml` | Dispatch / `workflow_call` | Auto-approve low-risk merges |
| `modular11-weekly-scrape.yml` | Manual dispatch | MLS NEXT league scraping |

### `AGE_ROLLOVER_FREEZE` (currently LIFTED)

**Status: `'false'` in all nine workflows since the Aug 2026 rollover completed.**
Everything it gated is running normally, with one permanent exception: the
`fix_team_age_groups.py` step carries a second, independent flag,
`AGE_DERIVATION_ENABLED: 'false'`, in both `data-hygiene-weekly.yml` and
`fix-age-year-discrepancies.yml`. That step derives a cohort as
`CURRENT_YEAR - birth_year + 1`, which cannot be right now that a birth year
spans two age groups. **It is not part of the rollover cycle — leave it `'false'`
when lifting or re-arming `AGE_ROLLOVER_FREEZE`.**

The rollover flag stays in place because this recurs every Aug 1 — re-arm it
rather than rebuilding it.

The flag holds the thirteen steps that write a team's age group, because those
derive a cohort from the wall clock while the stored labels only move when
someone hand-applies a migration. Between the two, a derived cohort and a stored
label differ by one, and writing on that difference merges or duplicates teams
permanently. The game importers count: they create unmatched teams through the
provider matchers using an age `EnhancedETLPipeline` derives at import time, so
the derivation is invisible at the call site.

**To re-arm for the next rollover**, set it to `'true'` in all nine:
`data-hygiene-weekly.yml`, `unknown-opponent-hygiene-weekly.yml`,
`auto-merge-queue.yml`, `fix-age-year-discrepancies.yml`,
`tgs-event-scrape-import.yml`, `modular11-weekly-scrape.yml`,
`modular11-events-weekly-scrape.yml`,
`playmetrics-tournament-scrape-import.yml`, `wa-scraper.yml`. Do it before Aug 1;
lift it again only once the relabel migration is applied and the boards verified.

Scrapers keep running while frozen; only the database write is skipped, and the
scraped CSVs still upload as artifacts, so a freeze costs a backfill rather than
a gap. The one exception is `playmetrics-scrape-import.yml`, where scraping and
importing are a single step: it is deliberately left ungated so collection
continues, accepting that a brand-new PlayMetrics team created mid-rollover may
land one cohort off. The exemption is named in the coverage test.

`tests/unit/test_age_rollover_freeze_coverage.py` fails on any ungated writing
step, or a gate widened by a top-level `||`. It guards the gates themselves, not
the flag's value, so it stays meaningful while lifted. It detects steps by script
name, so a genuinely new writer must be added to its lists — a regression guard,
not a discovery tool.

The relabel is hand-applied, so the migration ledger needs updating by hand too
(`supabase migration repair --status applied <version>`, or `--status reverted`
after a committed rollback). Skipping it leaves the next `supabase db push`
either re-applying the file — aborting on its guard, blocking unrelated
migrations — or skipping a rollover that never happened. The rollback expires at
the first post-roll ranking run, which re-anchors scores that restoring labels
cannot undo.

### Weekly Cycle

```
Continuous → Enqueue jobs fill scrape_requests; process_missing_games drains
             it every 15 min (40 teams/run, ~3,840/day)
Monday AM  → Data hygiene jobs
Monday PM  → Calculate rankings (Glicko-2 + ML Layer 13)
Sunday     → Event scraping, discovery + safety-net enqueue
As needed  → "Help Clear Queue" (manual) for bulk catch-up
```

### Scraping is queue-driven, not scheduled

Ongoing scraping runs through a priority queue, not a weekly bulk job. The Sunday-night
`scrape-games.yml` chain was removed in the schedule-driven-scraping migration; that
workflow is now a manual escape hatch for bootstrap and recovery only.

| Producer | Cadence | Priority | Targets |
|----------|---------|----------|---------|
| `frontend/app/api/scrape-missing-game` | User-clicked | 1 | One team |
| `frontend/app/api/create-team` | Admin creates a team | 1 | The new team, GotSport only |
| `enqueue_yesterday_games.py` | Daily | 2 | Teams whose yesterday games have null scores, excluding any already scraped today |
| `enqueue_active_teams.py` | Daily | 2 | Teams that played in the last 3 days |
| `enqueue_discovery_teams.py` | Weekly | 3 | Teams with no future games on record |
| `discover_teams_from_opponents.py` | Weekly | 3 | Teams it newly creates while resolving "Unknown" opponents (run by `unknown-opponent-hygiene-weekly.yml`) |
| `enqueue_safety_net.py` | Weekly | 4 | Never scraped, or not in 90+ days |

That is every caller of `enqueue_scrape_request` — the two `new_team` paths are easy to
miss when tracing why a team entered the queue, because neither lives in an
`enqueue_*.py` script. The RPC keeps at most one pending row per team and promotes
priority via `LEAST`. Consumers:

- `process_missing_games.py` — the automatic drainer, every 15 min, `--limit 40`.
- `drain_queue.py` — **this is the "Help Clear Queue" action** (`clear-queue.yml`).
  Manual only. `--limit` is a total scrape target: it claims queue rows via
  `claim_queue_items` (`FOR UPDATE SKIP LOCKED`), then tops the batch up from the
  `teams` table, most-recently-scraped first past a 14-day gate. Queue claims are
  parallel-safe; the top-up is not, so run one at a time.

A claimed row is set to `processing` and **nothing ever reclaims it** — there is no
lease, expiry, or reaper, and `claim_queue_items` only selects `pending`. Any path that
claims rows without going on to scrape them must release them explicitly.

---

## Environment Variables

Required variables are documented in `.env.example`. Key groups:

- **Database**: `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- **Ranking params**: Glicko engine flags and thresholds (`src/etl/glicko_config.py`), plus the inert legacy v53e layer vars
- **ML config**: `ML_LAYER_ENABLED`, `ML_ALPHA`, `ML_XGB_N_ESTIMATORS`, etc.
- **Scraping**: `ZENROWS_API_KEY`, `GOTSPORT_DELAY_MIN/MAX`
- **Frontend**: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_SITE_URL`
- **Payments**: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- **Email**: `RESEND_API_KEY`

**Never commit `.env` or `.env.local` files.** This repo is **public** (`dallasheidt14/PitchRank`), so a committed secret is disclosed the moment it is pushed, and stays readable in history after the file is untracked. Removing it from the tip is not a remediation; rotating the credential is.

---

## Frontend Architecture

### Tech Stack

- **Next.js 16** with App Router (file-based routing)
- **React 19** with Server Components
- **TypeScript 5.9** (strict mode)
- **Tailwind CSS v4** with shadcn/ui components (Radix UI primitives)
- **React Query v5** for server state (staleTime: 5min, gcTime: 10–60min)
- **Recharts** for data visualization
- **Supabase Auth** (OAuth + email/password)
- **Stripe** for subscriptions

### Key Routes

- `/` — Home page
- `/rankings` — Main rankings table (virtualized)
- `/rankings/[region]/[ageGroup]/[gender]` — Filtered rankings
- `/teams/[id]` — Team detail page (premium, ISR)
- `/compare` — Team comparison (premium)
- `/watchlist` — User's tracked teams (premium)
- `/blog/[slug]` — Blog posts
- `/mission-control` — Admin dashboard

### Auth for API Routes

All routes under `/api` are excluded from middleware auth (the negative lookahead in `config.matcher` at the bottom of `middleware.ts`), so each route must self-enforce authentication. Two shared helpers:

```typescript
// Admin-only routes (mission control, team management)
import { requireAdmin } from '@/lib/supabase/admin';
const auth = await requireAdmin();
if (auth.error) return auth.error;

// Premium routes (watchlist, insights) — returns supabase client for downstream queries
import { requirePremium } from '@/lib/api/requirePremium';
const auth = await requirePremium();
if (auth.error) return auth.error;
const { user, supabase } = auth;
```

### Shared API Utilities

| Utility | File | Purpose |
|---------|------|---------|
| `requirePremium()` | `lib/api/requirePremium.ts` | Auth + premium/admin plan check, returns supabase client |
| `requireAdmin()` | `lib/supabase/admin.ts` | Auth + admin plan check |
| `parseJsonBody()` | `lib/api/parseJsonBody.ts` | Safe JSON body parsing with error response |
| `checkRateLimit()` | `lib/api/rateLimit.ts` | In-memory IP-based rate limiting |

### Design System

- **Display font**: Oswald (athletic headlines)
- **Body font**: DM Sans
- **Primary color**: Forest Green (`#0B5345`)
- **Accent**: Electric Yellow (`#F4D03F`)
- **Path alias**: `@/*` → root directory

---

## Coding Conventions

### Python

- Use `async/await` for Supabase operations
- Supabase pagination: always handle the 1000-row limit
- Team IDs are UUIDs — never use integer IDs
- Game records are **immutable** — never update, only quarantine bad data
- Use `MergeResolver` for any team ID lookup (handles deprecated teams)
- Age groups: always normalize to integer format (`"U14"` → `"14"`, `"u11"` → `"11"`)
- Gender: always normalize to `"Male"` or `"Female"`
- PowerScore must be clamped to [0.0, 1.0] after calculation
- Configuration lives in `config/settings.py` — avoid hardcoding values
- Use `rich` console for CLI output/progress bars

### TypeScript/React

- Use App Router conventions (server components by default, `"use client"` when needed)
- Import paths use `@/` alias (e.g., `@/lib/api`, `@/components/ui/button`)
- Supabase client: use `supabaseBrowserClient.ts` for client components, server-side for API routes
- Data fetching via React Query hooks (`useRankings`, `useTeamSearch`, etc.)
- Styling: Tailwind utility classes, no CSS modules
- UI components: shadcn/ui pattern (Radix + Tailwind)

### Git

- Commit messages: imperative mood, plain descriptions (e.g., "Fix N+1 query in mission-control status endpoint")
- Don't commit `.env`, `.env.local`, or large CSV files
- The `.gitignore` excludes: `venv/`, `__pycache__/`, `*.log`, `logs/`, credentials, large data files

---

## Git Workflow

- Never commit directly to main. Create a feature branch and open a PR; the ruleset and the git guard both refuse direct commits.
- When the user asks for git operations (commit, push, merge), do them immediately without requiring a second ask.
- Keep the working tree clean — stage selectively (`git add <paths>`), not `git add -A`.

---

## General Rules

- Before creating new files or configurations, check if they already exist first (e.g., .env, .env.local, Telegram integrations, notification setups). Never create duplicates.

---

## Editing Rules

- After editing a Python file, re-read it when the post-edit hook reports that `ruff check --fix` rewrote it. The pre-commit ruff hook does not run locally (husky owns `core.hooksPath`); CI and the hook are the ruff gates.

---

## Code Quality

- Add a dry-run guard (`--dry-run` / `dry_run` param) to any new data-mutating method or script.
- A dry run is only as good as its weakest writer. `EnhancedETLPipeline` must pass `dry_run` to every provider matcher it constructs, and each matcher subclass must gate its own autocreate writes — a subclass that skips either makes the base class's guards inert and the run writes while reporting "no changes were made". Verify a new provider's dry run against the database, not its summary output.
- Run `ruff check` before committing Python changes; a Codex review bot also checks PRs (flags missing dry-run guards, lint, race conditions).
- Do NOT run `ruff format` over a whole file. Repo-wide format enforcement is deliberately deferred (`.pre-commit-config.yaml` is lint-only), so formatting a file rewrites unrelated code and buries the real diff. Check `ruff format --diff` first and keep the reformatting to lines the change already touches.

---

## Debugging

- When debugging failures, diagnose the root cause before re-running. Do not blindly retry failing commands or CI runs.

---

## Common Pitfalls

1. **Supabase 1000-row limit** — Always paginate queries; a single `.select()` returns max 1000 rows
2. **Team merge resolution** — Always apply `MergeResolver` before processing team IDs; deprecated teams must map to canonical
3. **Game immutability** — Never UPDATE a game row; quarantine bad data instead
4. **Age/birth year confusion** — `14B` = birth year 2014 = **U13** in 2026-27, not U14
5. **Division tier merging** — ECNL ≠ ECNL-RL, HD ≠ AD — never merge teams across tiers
6. **PowerScore bounds** — Must always be [0.0, 1.0]; check for NaN/Infinity after calculation
7. **URI length limits** — Batch `.in_()` queries to ≤100 IDs per call
8. **ML leakage** — Layer 13 uses a 30-day time-split; never train on recent data used for prediction
9. **Concurrent scraping** — GitHub Actions uses concurrency locks to prevent overlapping scrape runs
10. **Frontend hydration** — Use `"use client"` directive only when needed; prefer server components

---

## Key Files Quick Reference

| Purpose | File |
|---------|------|
| Ranking engine (Glicko-2, production) | `src/etl/glicko_engine.py` |
| Glicko-2 config (`GlickoConfig`) | `src/etl/glicko_config.py` |
| Ranking engine (v53e, `--engine v53e` only) | `src/etl/v53e.py` |
| Age anchors, gate thresholds, league tier multipliers | `src/rankings/constants.py` |
| Ranking orchestrator | `src/rankings/calculator.py` |
| ML Layer 13 | `src/rankings/layer13_predictive_adjustment.py` |
| Supabase ↔ engine adapter | `src/rankings/data_adapter.py` |
| Merge resolver | `src/utils/merge_resolver.py` |
| Game matcher | `src/models/game_matcher.py` |
| Club normalizer | `src/utils/club_normalizer.py` |
| Centralized config | `config/settings.py` |
| Main scraper script | `scripts/scrape_games.py` |
| Ranking calculation script | `scripts/calculate_rankings.py` |
| Frontend API client | `frontend/lib/api.ts` |
| Shared route utilities | `frontend/lib/api/` (requirePremium, parseJsonBody, rateLimit) |
| Frontend types | `frontend/lib/types.ts` |
| Supabase migrations | `supabase/migrations/` |
| GH Actions workflows | `.github/workflows/` |
| Admin dashboard | `dashboard.py` (Streamlit) |
