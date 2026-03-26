# CLAUDE.md — PitchRank AI Assistant Guide

> Last updated: 2026-03-10

PitchRank is a **youth soccer ranking platform** that scrapes game data from multiple providers, calculates rankings using a proprietary 13-layer algorithm (v53e + ML), and serves results through a Next.js frontend. This file is the primary reference for AI assistants working in this codebase.

---

## Quick Reference

| Item | Value |
|------|-------|
| **Backend** | Python 3.11, Supabase (PostgreSQL) |
| **Frontend** | Next.js 16, React 19, TypeScript 5.9, Tailwind CSS v4 |
| **ML** | XGBoost, scikit-learn, pandas, numpy |
| **Database** | Supabase (hosted PostgreSQL + PostgREST) |
| **Deployment** | Vercel (frontend), GitHub Actions (backend automation) |
| **Package manager** | pip (backend), npm (frontend) |
| **Primary branch** | `main` |
| **Rankings recalculation** | Weekly (Monday) via GitHub Actions |

---

## Repository Structure

```
PitchRank/
├── src/                    # Core Python backend (rankings, ETL, matching)
│   ├── api/                # REST API endpoints
│   ├── etl/                # ETL pipelines + v53e ranking engine
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
│   ├── hooks/              # Custom React hooks
│   ├── types/              # TypeScript type definitions
│   ├── e2e/                # Playwright E2E tests
│   └── middleware.ts       # Auth + route protection
│
├── scripts/                # 146+ operational scripts (import, ranking, hygiene)
├── scrapers/               # Scrapy-based scrapers (Modular11/MLS NEXT)
├── config/                 # Centralized settings.py (12K+ lines)
├── data/                   # Cache, master data, raw imports, backtests
├── models/                 # ML model artifacts
├── supabase/               # Database migrations (70+ files)
├── tests/                  # Python test suite
├── docs/                   # 110+ documentation files
├── memory/                 # Agent working memory files
├── .claude/                # Claude agent configs + skills
│   ├── agents/             # SEO sub-agent definitions
│   └── skills/             # Domain skills (ranking, scraping, SEO, etc.)
├── .github/workflows/      # 15+ automated workflows
├── dashboard.py            # Streamlit admin dashboard (248K lines)
└── agent_skills/           # Standalone agent skill packages
```

---

## Domain Knowledge (CRITICAL)

### Age Groups (2026 Season)

| Birth Year | Age Group | | Birth Year | Age Group |
|---|---|---|---|---|
| 2016 | U10 | | 2012 | U14 |
| 2015 | U11 | | 2011 | U15 |
| 2014 | U12 | | 2010 | U16 |
| 2013 | U13 | | 2009 | U17 |
| | | | 2008 | U19 |
| | | | 2007 | U19 |

- `14B` = 2014 birth year, Boys = **U12 Male** (NOT U14!)
- `U14B` = U14 age group, Boys = **U14 Male**
- `G2016` = Girls, 2016 birth year = **U10 Female**
- **B/G = Gender (Boys/Girls), NOT part of age number**

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

---

## Ranking Algorithm (v53e + ML)

### Pipeline Flow

```
Games (Supabase, 365-day window)
  → Merge Resolution (deprecated → canonical team IDs)
  → v53e Base Calculation (10 layers)
  → ML Layer 13 (XGBoost residual adjustment, alpha=0.15)
  → Two-Pass SOS Normalization (cross-age, national, state)
  → Age Anchor Scaling (U10=0.40 → U19=1.00)
  → Save to rankings_full + current_rankings
```

### v53e Layers

1. **Window**: 365-day lookback, 180-day inactivity threshold
2. **Offense/Defense**: Goal difference capped at 6
3. **Recency**: Exponential decay (rate=0.05), recent 15 games at 65% weight
4. **Defense Ridge**: Ridge regression (factor=0.25)
5. **Adaptive K**: Dynamic K-factor (alpha=0.5, beta=0.6)
6. **Performance**: Goal-based residuals (scale=5.0, decay=0.08)
7. **Bayesian Shrinkage**: Tau=8.0 for small-sample correction
8. **SOS**: Iterative, 3 passes, unranked base=0.35, repeat cap=2
9. **Opponent-Adjusted**: Offense/defense corrected for opponent strength
10. **PowerScore Blend**: OFF:0.25, DEF:0.25, SOS:0.50

### PowerScore

- Range: **always 0.0–1.0** (clamp after calculation)
- 0.95+ = elite national | 0.80–0.95 = top tier | 0.50–0.80 = competitive
- Higher = better

### ML Layer 13

- XGBoost (220 estimators, max_depth=5, learning_rate=0.08)
- Fallback: RandomForest (240 estimators, max_depth=18)
- 30-day time-split prevents data leakage
- Residuals clipped ±3.5 goals, normalized by cohort
- Blend: `powerscore_ml = powerscore_adj + α * ml_norm` (α=0.15)

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

# Run ranking calculation
python scripts/calculate_rankings.py --ml --lookback-days 365

# Dry run (no DB write)
python scripts/calculate_rankings.py --ml --dry-run

# Force rebuild (ignore cache)
python scripts/calculate_rankings.py --ml --force-rebuild

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

# E2E tests
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
| `scrape-games.yml` | Mon 6:00 & 11:15 AM UTC | Scrape 25K GotSport teams |
| `calculate-rankings.yml` | Mon 4:45 PM UTC | Recalculate rankings (v53e + ML) |
| `auto-gotsport-event-scrape.yml` | Mon & Thu 6:00 AM UTC | Tournament bracket scraping |
| `tgs-event-scrape-import.yml` | Sun 6:30 AM UTC | TGS event scraping |
| `data-hygiene-weekly.yml` | Sun 5:00 PM UTC | Data cleanup (age, dupes, states) |
| `unknown-opponent-hygiene-weekly.yml` | Weekly | Resolve "Unknown" opponents |
| `auto-merge-queue.yml` | Post-import | Auto-approve low-risk merges |
| `modular11-weekly-scrape.yml` | Manual dispatch | MLS NEXT league scraping |

### Weekly Cycle

```
Monday AM  → Scrape games (2 batches, 25K teams each)
Monday PM  → Calculate rankings (v53e + ML Layer 13)
Sunday     → Data hygiene jobs, event scraping
Continuous → Merge queue processing, club name backfill
```

---

## Environment Variables

Required variables are documented in `.env.example`. Key groups:

- **Database**: `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- **Ranking params**: 40+ vars for v53e layers (window, weights, thresholds)
- **ML config**: `ML_LAYER_ENABLED`, `ML_ALPHA`, `ML_XGB_N_ESTIMATORS`, etc.
- **Scraping**: `ZENROWS_API_KEY`, `GOTSPORT_DELAY_MIN/MAX`
- **Frontend**: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_SITE_URL`
- **Payments**: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- **Email**: `RESEND_API_KEY`

**Never commit `.env` or `.env.local` files.**

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

### Admin Auth for API Routes

Admin-only API routes use `requireAdmin()` from `frontend/lib/supabase/admin.ts`. This verifies the caller is an authenticated user with `user_profiles.plan === 'admin'`. All routes under `/api` are excluded from middleware auth (middleware.ts line 128), so each route must self-enforce authentication.

```typescript
import { requireAdmin } from '@/lib/supabase/admin';

export async function POST(request: NextRequest) {
  const auth = await requireAdmin();
  if (auth.error) return auth.error;
  // ... route logic
}
```

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

- Commit messages: conventional style (`feat:`, `fix:`, `chore:`, `docs:`)
- Don't commit `.env`, `.env.local`, or large CSV files
- The `.gitignore` excludes: `venv/`, `__pycache__/`, `*.log`, `logs/`, credentials, large data files

---

## Agent System

PitchRank uses a multi-agent system with specialized personas:

| Agent | Role | Memory File |
|-------|------|-------------|
| **Codey** | Development, bug fixes | `memory/WORKING-codey.md` |
| **Ranky** | Ranking calculations | `memory/WORKING-ranky.md` |
| **Scrappy** | Data scraping | `memory/WORKING-scrappy.md` |
| **Cleany** | Data hygiene, cleanup | `memory/WORKING-cleany.md` |
| **Movy** | Data movement, imports | `memory/WORKING-movy.md` |
| **Compy** | Computation, analysis | `memory/WORKING-compy.md` |
| **Watchy** | Monitoring, health checks | `memory/WORKING-watchy.md` |
| **Socialy** | SEO, content, marketing | `memory/WORKING-socialy.md` |

Skills are defined in `.claude/skills/` and provide domain-specific knowledge for ranking algorithms, scraping patterns, database operations, and more.

---

## Common Pitfalls

1. **Supabase 1000-row limit** — Always paginate queries; a single `.select()` returns max 1000 rows
2. **Team merge resolution** — Always apply `MergeResolver` before processing team IDs; deprecated teams must map to canonical
3. **Game immutability** — Never UPDATE a game row; quarantine bad data instead
4. **Age/birth year confusion** — `14B` = birth year 2014 = **U12**, not U14
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
| Ranking engine (v53e) | `src/etl/v53e.py` |
| Ranking orchestrator | `src/rankings/calculator.py` |
| ML Layer 13 | `src/rankings/layer13_predictive_adjustment.py` |
| Supabase ↔ v53e adapter | `src/rankings/data_adapter.py` |
| Merge resolver | `src/utils/merge_resolver.py` |
| Merge suggester | `src/utils/merge_suggester.py` |
| Game matcher | `src/models/game_matcher.py` |
| Club normalizer | `src/utils/club_normalizer.py` |
| Centralized config | `config/settings.py` |
| Main scraper script | `scripts/scrape_games.py` |
| Ranking calculation script | `scripts/calculate_rankings.py` |
| Frontend API client | `frontend/lib/api.ts` |
| Frontend types | `frontend/lib/types.ts` |
| Supabase migrations | `supabase/migrations/` |
| GH Actions workflows | `.github/workflows/` |
| Admin dashboard | `dashboard.py` (Streamlit) |
