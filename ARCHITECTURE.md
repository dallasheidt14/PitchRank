# PitchRank — Architecture Document

> **Last updated:** 2026-03-18

PitchRank is a youth soccer ranking platform that scrapes game data from multiple providers, calculates rankings using a proprietary 13-layer algorithm (v53e + ML Layer 13), and serves results through a Next.js frontend backed by Supabase (PostgreSQL).

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [High-Level System Diagram](#2-high-level-system-diagram)
3. [Core Components](#3-core-components)
4. [Data Stores](#4-data-stores)
5. [External Integrations](#5-external-integrations)
6. [Deployment & Infrastructure](#6-deployment--infrastructure)
7. [Security Considerations](#7-security-considerations)
8. [Development & Testing](#8-development--testing)
9. [Future Considerations](#9-future-considerations)
10. [Glossary](#10-glossary)
11. [Project Identification](#11-project-identification)

---

## 1. PROJECT STRUCTURE

```
PitchRank/
│
├── src/                            # Core Python backend
│   ├── api/                        #   REST API endpoints (future)
│   ├── base/                       #   Abstract base classes for providers
│   ├── etl/                        #   ETL pipelines + v53e ranking engine
│   │   ├── v53e.py                 #     10-layer ranking algorithm
│   │   ├── enhanced_pipeline.py    #     Enhanced ETL pipeline
│   │   └── pipeline.py            #     Base pipeline framework
│   ├── identity/                   #   Team identity resolution
│   ├── models/                     #   Game/team matching (fuzzy + provider-specific)
│   │   ├── game_matcher.py         #     Core fuzzy matching
│   │   ├── modular11_matcher.py    #     MLS NEXT matcher
│   │   ├── tgs_matcher.py          #     TGS tournament matcher
│   │   ├── sincsports_matcher.py   #     SincSports matcher
│   │   └── affinity_wa_matcher.py  #     Affinity/WA matcher
│   ├── predictions/                #   ML match prediction (XGBoost)
│   │   ├── ml_match_predictor.py   #     Match outcome model
│   │   └── validate_predictions.py #     Prediction validation
│   ├── providers/                  #   External API clients
│   │   ├── athleteone_client.py    #     AthleteOne API client
│   │   └── athleteone_html_parser.py
│   ├── rankings/                   #   Ranking orchestration + ML Layer 13
│   │   ├── calculator.py           #     Integrated ranking orchestrator
│   │   ├── layer13_predictive_adjustment.py  # XGBoost residual adjustment
│   │   ├── data_adapter.py         #     Supabase ↔ v53e bridge
│   │   └── ranking_history.py      #     Historical snapshot tracking
│   ├── scrapers/                   #   Web scrapers by provider
│   │   ├── gotsport.py             #     GotSport REST API (primary)
│   │   ├── gotsport_event.py       #     GotSport tournament brackets
│   │   ├── sincsports.py           #     SincSports HTML scraper
│   │   ├── athleteone_scraper.py   #     AthleteOne scraper
│   │   ├── surfsports.py           #     SurfSports scraper
│   │   └── athleteone_event.py     #     AthleteOne event scraper
│   └── utils/                      #   Shared utilities
│       ├── merge_resolver.py       #     Deprecated → canonical team IDs
│       ├── merge_suggester.py      #     Auto-merge candidate detection
│       ├── club_normalizer.py      #     Club name standardization
│       ├── team_name_utils.py      #     Team name parsing
│       ├── validators.py           #     Data validators
│       └── enhanced_validators.py  #     Extended validation rules
│
├── frontend/                       # Next.js 16 web application
│   ├── app/                        #   App Router (file-based routing)
│   │   ├── layout.tsx              #     Root layout (fonts, GA, providers)
│   │   ├── page.tsx                #     Home page
│   │   ├── rankings/               #     Rankings pages
│   │   │   ├── page.tsx            #       Main rankings table
│   │   │   └── [region]/[ageGroup]/[gender]/
│   │   │       └── page.tsx        #       Filtered rankings (dynamic)
│   │   ├── teams/[id]/             #     Team detail (premium, ISR)
│   │   ├── compare/                #     Team comparison (premium)
│   │   ├── watchlist/              #     User watchlist (premium)
│   │   ├── blog/[slug]/            #     Blog posts
│   │   ├── methodology/            #     How We Rank
│   │   ├── mission-control/        #     Admin dashboard
│   │   ├── auth/callback/          #     OAuth callback
│   │   ├── login/ & signup/        #     Auth pages
│   │   ├── upgrade/                #     Premium upgrade
│   │   └── api/                    #     API routes
│   │       ├── stripe/             #       Checkout, webhook, portal
│   │       ├── teams/search/       #       Team search API
│   │       ├── team-merge/         #       Merge operations
│   │       ├── team-aliases/       #       Provider ID mappings
│   │       ├── watchlist/          #       Watchlist CRUD
│   │       ├── chat/               #       AI chat endpoint
│   │       ├── notifications/      #       Email notifications
│   │       └── agent-*/            #       Agent system endpoints
│   ├── components/                 #   React components (48+)
│   │   ├── ui/                     #     shadcn/ui primitives (20 components)
│   │   ├── RankingsTable.tsx       #     Virtualized rankings table
│   │   ├── Navigation.tsx          #     Site navigation
│   │   ├── GlobalSearch.tsx        #     Fuse.js-powered search
│   │   ├── TeamHeader.tsx          #     Team detail header
│   │   ├── PredictedMatchCard.tsx  #     Match prediction card
│   │   └── ...                     #     40+ additional components
│   ├── hooks/                      #   Custom React hooks
│   │   ├── useRankings.ts          #     Rankings data (React Query)
│   │   ├── useTeamSearch.ts        #     Team search
│   │   └── useUser.ts             #     Auth state
│   ├── lib/                        #   Utilities and clients
│   │   ├── api.ts                  #     Supabase query wrapper (40K+)
│   │   ├── types.ts                #     TypeScript interfaces
│   │   ├── matchPredictor.ts       #     ML match prediction (30K+)
│   │   ├── matchExplainer.ts       #     Prediction explainer (21K+)
│   │   ├── supabaseBrowserClient.ts#     Client-side Supabase
│   │   ├── supabaseClient.ts       #     Server-side Supabase
│   │   ├── analytics.ts           #     Google Analytics 4
│   │   ├── mergeResolver.ts        #     Team merge resolution
│   │   └── constants.ts           #     App constants
│   ├── types/                      #   TypeScript type definitions
│   ├── e2e/                        #   Playwright E2E tests (9 suites)
│   ├── public/                     #   Static assets
│   ├── middleware.ts               #   Auth + route protection
│   ├── next.config.ts              #   Next.js config (CSP, images, redirects)
│   ├── package.json                #   41 deps + 11 dev deps
│   └── tailwind.config.ts          #   Tailwind v4 config
│
├── scrapers/                       # Scrapy-based scrapers
│   └── modular11_scraper/          #   MLS NEXT / HD league spider
│
├── config/                         # Centralized configuration
│   └── settings.py                 #   12K+ lines, env-driven settings
│
├── scripts/                        # 146+ operational scripts
│   ├── calculate_rankings.py       #   Main ranking calculation (33K+)
│   ├── scrape_games.py             #   Game scraping orchestration
│   ├── import_games_enhanced.py    #   CSV import pipeline
│   ├── auto_match_unknown_opponents.py  # Opponent resolution (20K+)
│   ├── weekly/                     #   Weekly job scripts
│   ├── fixes/                      #   Quick fixes
│   ├── merges/                     #   Merge operations
│   ├── migrations/                 #   Data migrations
│   └── archive_bad/                #   Bad data archival
│
├── supabase/                       # Database layer
│   └── migrations/                 #   70+ SQL migration files
│
├── tests/                          # Python test suite
│   ├── unit/                       #   Unit tests
│   └── integration/                #   Pipeline integration tests
│
├── models/                         # ML model artifacts
│   └── match_predictor/            #   Serialized XGBoost/RF models
│
├── data/                           # Data management
│   ├── master/                     #   Master reference data
│   ├── raw/                        #   Raw scraped data
│   ├── cache/                      #   Computation cache
│   ├── calibration/                #   Model calibration data
│   ├── backtest_results/           #   Ranking backtests
│   ├── exports/                    #   Data exports
│   └── validation/                 #   Validation datasets
│
├── docs/                           # 110+ documentation files
│   ├── ALGORITHM_DEEP_DIVE.md      #   v53e layer breakdown
│   ├── LEARNINGS.md                #   Comprehensive knowledge base
│   └── ...                         #   Investigation reports, guides
│
├── .github/workflows/              # 15+ GitHub Actions workflows
├── .claude/                        # Claude agent configuration
│   ├── agents/                     #   Agent persona definitions
│   └── skills/                     #   16+ domain skill modules
├── memory/                         # Agent working memory files
├── dashboard.py                    # Streamlit admin dashboard (6K lines)
├── requirements.txt                # Python dependencies (39 packages)
├── pyproject.toml                  # Python project metadata
├── playwright.config.ts            # E2E test configuration
├── .env.example                    # Environment template (174 vars)
└── CLAUDE.md                       # AI assistant guide
```

---

## 2. HIGH-LEVEL SYSTEM DIAGRAM

### C4 Model — Level 1 (System Context)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL DATA PROVIDERS                        │
│                                                                         │
│  ┌──────────┐  ┌─────┐  ┌───────────┐  ┌───────────┐  ┌────────────┐  │
│  │ GotSport │  │ TGS │  │ SincSports│  │AthleteOne │  │ Modular11  │  │
│  │ REST API │  │Event│  │  HTML     │  │  API      │  │ Scrapy     │  │
│  │ (25K+    │  │Scrape│  │ Scraping  │  │  Client   │  │ MLS NEXT   │  │
│  │  teams)  │  │     │  │           │  │           │  │ HD Leagues │  │
│  └────┬─────┘  └──┬──┘  └─────┬─────┘  └─────┬─────┘  └──────┬─────┘  │
│       │           │           │              │               │          │
└───────┼───────────┼───────────┼──────────────┼───────────────┼──────────┘
        │           │           │              │               │
        ▼           ▼           ▼              ▼               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PYTHON BACKEND (src/)                               │
│                                                                         │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────────────┐ │
│  │  Scrapers   │──▶│  ETL / Team  │──▶│  Ranking Engine (v53e + ML)  │ │
│  │  (src/      │   │  Matching    │   │  ┌────────────────────────┐  │ │
│  │   scrapers/)│   │  (src/models)│   │  │ 10 v53e Layers         │  │ │
│  └─────────────┘   └──────────────┘   │  │ ML Layer 13 (XGBoost)  │  │ │
│                                        │  │ SOS Normalization      │  │ │
│  ┌─────────────┐                      │  │ Age Anchor Scaling     │  │ │
│  │  Merge      │                      │  └────────────────────────┘  │ │
│  │  Resolver   │◀─────────────────────│                              │ │
│  │  (src/utils)│                      └──────────────────────────────┘ │
│  └─────────────┘                                     │                  │
│                                                      ▼                  │
└──────────────────────────────────────────────────────┼──────────────────┘
                                                       │
                              ┌─────────────────────────────────────┐
                              │         SUPABASE (PostgreSQL)       │
                              │                                     │
                              │  ┌─────────┐  ┌────────────────┐   │
                              │  │  teams   │  │ rankings_full  │   │
                              │  │  games   │  │ ranking_history│   │
                              │  │  aliases │  │ user_profiles  │   │
                              │  └─────────┘  └────────────────┘   │
                              │         + PostgREST API             │
                              │         + Supabase Auth             │
                              └──────────────┬──────────────────────┘
                                             │
                              ┌──────────────┴──────────────────────┐
                              │     NEXT.JS 16 FRONTEND (Vercel)    │
                              │                                     │
                              │  ┌──────────────┐ ┌──────────────┐  │
                              │  │ Server       │ │ Client       │  │
                              │  │ Components   │ │ Components   │  │
                              │  │ (SSR / ISR)  │ │ (React Query)│  │
                              │  └──────────────┘ └──────────────┘  │
                              │                                     │
                              │  ┌──────────────┐ ┌──────────────┐  │
                              │  │ API Routes   │ │ Middleware    │  │
                              │  │ (Stripe,     │ │ (Auth, RBAC, │  │
                              │  │  Search, etc)│ │  Redirects)  │  │
                              │  └──────────────┘ └──────────────┘  │
                              └──────────────┬──────────────────────┘
                                             │
                              ┌──────────────┴──────────────────────┐
                              │            END USERS                 │
                              │                                     │
                              │  ┌──────────┐  ┌────────────────┐   │
                              │  │  Free    │  │  Premium       │   │
                              │  │  Users   │  │  Subscribers   │   │
                              │  │  (view   │  │  (team detail, │   │
                              │  │  rankings│  │   compare,     │   │
                              │  │  only)   │  │   watchlist)   │   │
                              │  └──────────┘  └────────────────┘   │
                              └─────────────────────────────────────┘

                    ┌───────────────────────────────────────────┐
                    │          EXTERNAL SERVICES                 │
                    │                                           │
                    │  ┌────────┐ ┌────────┐ ┌──────────────┐  │
                    │  │ Stripe │ │ Resend │ │ Google       │  │
                    │  │Payments│ │ Email  │ │ Analytics 4  │  │
                    │  └────────┘ └────────┘ └──────────────┘  │
                    │                                           │
                    │  ┌──────────────────────────────────────┐ │
                    │  │ GitHub Actions (CI/CD + Automation)  │ │
                    │  └──────────────────────────────────────┘ │
                    └───────────────────────────────────────────┘
```

### Data Flow (Weekly Ranking Cycle)

```
Monday AM                  Monday PM                    Continuous
┌──────────┐    ┌─────────────────────┐    ┌──────────────────────┐
│ Scrape   │    │ Calculate Rankings  │    │ Serve via Frontend   │
│ Games    │───▶│                     │───▶│                      │
│ (25K     │    │ v53e (10 layers)    │    │ Rankings table       │
│  teams)  │    │ ML Layer 13         │    │ Team detail (ISR)    │
│          │    │ SOS normalization   │    │ Compare / Watchlist  │
│          │    │ Age anchor scaling  │    │ Match predictions    │
└──────────┘    └─────────────────────┘    └──────────────────────┘

Sunday
┌──────────────────────┐
│ Data Hygiene          │
│ - Age corrections     │
│ - Duplicate removal   │
│ - State backfill      │
│ - Unknown opponents   │
│ - Merge queue         │
└──────────────────────┘
```

---

## 3. CORE COMPONENTS

### 3.1 Frontend — Next.js Web Application

| Attribute | Details |
|-----------|---------|
| **Purpose** | User-facing rankings browser, team detail pages, match predictions, premium features (compare, watchlist), admin mission control |
| **Technologies** | Next.js 16, React 19, TypeScript 5.9, Tailwind CSS v4, shadcn/ui (Radix), React Query v5, Recharts, Fuse.js, React Virtual |
| **Deployment** | Vercel (edge-optimized, ISR for team pages) |
| **Key patterns** | Server Components by default, `"use client"` only when needed; React Query for data fetching (staleTime: 5min); App Router file-based routing; `@/*` path alias |

**Route Architecture:**

| Route | Access | Description |
|-------|--------|-------------|
| `/` | Public | Home page with leaderboard preview |
| `/rankings` | Public | Virtualized rankings table with filters |
| `/rankings/[region]/[ageGroup]/[gender]` | Public | Dynamic filtered rankings |
| `/teams/[id]` | Premium | Team detail with game history, trajectory, predictions |
| `/compare` | Premium | Side-by-side team comparison |
| `/watchlist` | Premium | User's tracked teams |
| `/blog/[slug]` | Public | Content marketing / methodology articles |
| `/methodology` | Public | How We Rank explainer |
| `/mission-control` | Admin | Internal operations dashboard |
| `/api/stripe/*` | Internal | Payment webhook, checkout, billing portal |
| `/api/teams/search` | Internal | Fuzzy team search API |

### 3.2 Backend — Python Ranking & Scraping Engine

| Attribute | Details |
|-----------|---------|
| **Purpose** | Game data scraping, team matching, ranking calculation (v53e + ML Layer 13), data hygiene, merge resolution |
| **Technologies** | Python 3.11, pandas, numpy, XGBoost, scikit-learn, Beautiful Soup, Scrapy, Supabase SDK, Click, Rich |
| **Deployment** | GitHub Actions (scheduled workflows — not a long-running server) |
| **Key patterns** | Async Supabase operations; 1000-row pagination; MergeResolver for all team ID lookups; immutable game records |

**Module Breakdown:**

| Module | Purpose |
|--------|---------|
| `src/etl/v53e.py` | Core 10-layer ranking algorithm (offense/defense, recency, SOS, Bayesian shrinkage, PowerScore blend) |
| `src/rankings/calculator.py` | Orchestrates v53e + ML Layer 13 + age anchoring + history tracking |
| `src/rankings/layer13_predictive_adjustment.py` | XGBoost residual model (220 estimators, α=0.15 blend weight) |
| `src/rankings/data_adapter.py` | Translates Supabase rows ↔ v53e data structures |
| `src/scrapers/*` | Provider-specific scrapers (GotSport, TGS, SincSports, AthleteOne, SurfSports) |
| `src/models/game_matcher.py` | Fuzzy team matching (name 35%, club 35%, age 10%, location 10%) |
| `src/utils/merge_resolver.py` | Maps deprecated team IDs → canonical IDs with cascade support |
| `src/predictions/ml_match_predictor.py` | Match outcome prediction using historical rankings data |

### 3.3 Admin Dashboard — Streamlit

| Attribute | Details |
|-----------|---------|
| **Purpose** | Internal operations dashboard for data monitoring, team auditing, merge management, import tracking |
| **Technologies** | Streamlit 1.28+, matplotlib, pandas |
| **Deployment** | Run locally or on-demand (`streamlit run dashboard.py`) |
| **Size** | 6,036 lines |

### 3.4 Scrapy Spiders

| Attribute | Details |
|-----------|---------|
| **Purpose** | Structured scraping for MLS NEXT and HD leagues via Modular11 |
| **Technologies** | Scrapy 2.13+, Twisted |
| **Deployment** | GitHub Actions (manual dispatch or scheduled) |

### 3.5 Agent System

PitchRank employs a multi-agent AI system with specialized personas for different operational tasks:

| Agent | Role | Memory |
|-------|------|--------|
| Codey | Development & bug fixes | `memory/WORKING-codey.md` |
| Ranky | Ranking calculations | `memory/WORKING-ranky.md` |
| Scrappy | Data scraping | `memory/WORKING-scrappy.md` |
| Cleany | Data hygiene & cleanup | `memory/WORKING-cleany.md` |
| Movy | Data movement & imports | `memory/WORKING-movy.md` |
| Compy | Computation & analysis | `memory/WORKING-compy.md` |
| Watchy | Monitoring & health checks | `memory/WORKING-watchy.md` |
| Socialy | SEO, content & marketing | `memory/WORKING-socialy.md` |

Skills are defined in `.claude/skills/` (16+ domain-specific modules) covering ranking algorithms, scraper patterns, database operations, and SEO.

---

## 4. DATA STORES

### 4.1 Supabase (Hosted PostgreSQL + PostgREST)

| Attribute | Details |
|-----------|---------|
| **Type** | PostgreSQL (via Supabase) |
| **Purpose** | Primary data store for all teams, games, rankings, user data, and operational metadata |
| **Access** | PostgREST API (auto-generated REST), Supabase JS SDK (frontend), Python SDK (backend) |
| **Migrations** | 70+ SQL migration files in `supabase/migrations/` |

**Key Tables:**

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `teams` | Master team registry | `team_id_master` (UUID PK), `team_name`, `club_name`, `age_group`, `gender`, `state` |
| `games` | Game records (**immutable**) | `id`, `home_team_id`, `away_team_id`, `home_score`, `away_score`, `game_date`, `provider`, `ml_overperformance` |
| `team_alias_map` | Provider ID → master team ID | `provider_team_id`, `master_team_id`, `match_method` (direct_id / fuzzy / manual), `confidence` |
| `team_merge_map` | Deprecated → canonical team ID | `deprecated_team_id`, `canonical_team_id` (cascade merge support) |
| `rankings_full` | All ranking metrics | 30+ columns: `powerscore`, `powerscore_ml`, `offense_rating`, `defense_rating`, `sos_score`, `national_rank`, `state_rank` |
| `current_rankings` | Legacy rankings view | Backward-compatible aliases |
| `ranking_history` | Weekly snapshots | `team_id`, `rank`, `powerscore`, `snapshot_date`, `rank_change_7d`, `rank_change_30d` |
| `team_match_review_queue` | Uncertain matches (0.75–0.90 confidence) | `provider_team_id`, `candidate_team_id`, `confidence`, `status` |
| `user_profiles` | User metadata + subscription | `user_id`, `plan` (free / premium / admin), `stripe_customer_id` |
| `game_corrections` | Quarantined invalid games | Mirror of `games` structure + correction reason |
| `quarantine_teams` | Flagged invalid teams | Review queue for manual verification |
| `build_logs` | ETL execution tracking | `run_id`, `metrics` (JSONB), `started_at`, `completed_at` |
| `newsletter_subscribers` | Email list | `email`, `subscribed_at` |
| `scrape_requests` | User-initiated scrapes | `status` (pending / processing / completed / failed) |

**Database Views:**

| View | Purpose |
|------|---------|
| `rankings_view` | National rankings with rank/score aliases |
| `state_rankings_view` | State-level rankings |
| `current_rankings_view` | Backward-compatible view |
| `team_predictive_view` | Predictive metrics for match prediction |

**Access Patterns & Constraints:**

- **1000-row pagination limit** — all queries must paginate using `.range(offset, offset + 999)`
- **100-ID batch limit** — `.in_()` queries batched to ≤100 IDs per call (URI length)
- **RPC for bulk writes** — `supabase.rpc('batch_update_ml_overperformance', {'updates': data})`
- **Row-Level Security (RLS)** — enabled on user-facing tables

### 4.2 Local File Cache

| Attribute | Details |
|-----------|---------|
| **Type** | File system (CSV, JSON, pickle) |
| **Purpose** | Intermediate computation cache, raw scrape data, model artifacts |
| **Location** | `data/cache/`, `data/raw/`, `data/master/`, `models/match_predictor/` |

### 4.3 ML Model Artifacts

| Attribute | Details |
|-----------|---------|
| **Type** | Serialized models (joblib / pickle) |
| **Purpose** | Persisted XGBoost and RandomForest models for Layer 13 and match prediction |
| **Location** | `models/match_predictor/` |

---

## 5. EXTERNAL INTEGRATIONS

### Data Providers

| Service | Purpose | Integration Method | Scale |
|---------|---------|-------------------|-------|
| **GotSport** | Primary game data source | REST API via ZenRows proxy | 25K+ teams |
| **TGS (Total Global Sports)** | Tournament data | Event page scraping | Tournament brackets |
| **Modular11** | MLS NEXT / HD league data | Scrapy spider | League schedules |
| **SincSports** | Supplementary game data | HTML scraping | Regional tournaments |
| **AthleteOne** | Conference schedules | REST API client + HTML parser | Conference data |
| **SurfSports** | Additional game data | Web scraping | Regional events |

### SaaS Integrations

| Service | Purpose | Integration Method | Key Files |
|---------|---------|-------------------|-----------|
| **Stripe** | Subscription payments (monthly $6.99 / yearly $69) | Webhooks + Checkout Sessions + Customer Portal | `frontend/app/api/stripe/*` |
| **Resend** | Transactional email (welcome, digest, auth) | REST API | `frontend/lib/email/` |
| **Supabase Auth** | User authentication | OAuth (Google, GitHub) + email/password | `frontend/middleware.ts` |
| **Google Analytics 4** | Usage analytics | Client-side gtag.js | `frontend/components/GoogleAnalytics.tsx` |
| **ZenRows** | Web scraping proxy (anti-bot bypass) | Proxy API | `src/scrapers/gotsport.py` |
| **Serper.dev** | Google Search API (Instagram handle discovery) | REST API | `scripts/enrich_instagram_handles.py` |
| **Vercel** | Frontend hosting + edge functions | Git-based deployment | `next.config.ts` |

---

## 6. DEPLOYMENT & INFRASTRUCTURE

### Cloud Services

| Layer | Service | Purpose |
|-------|---------|---------|
| **Frontend hosting** | Vercel | Next.js edge deployment, ISR, CDN |
| **Database** | Supabase (AWS-backed) | Hosted PostgreSQL, PostgREST, Auth, Storage |
| **Backend automation** | GitHub Actions | Scheduled scraping, ranking calculations, data hygiene |
| **Scraping proxy** | ZenRows | Anti-bot bypass for GotSport |

### CI/CD Pipeline — GitHub Actions

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `scrape-games.yml` | Mon 6:00 & 11:15 AM UTC | Scrape 25K GotSport teams (2 batches) |
| `calculate-rankings.yml` | Mon 4:45 PM UTC | Full ranking recalculation (v53e + ML Layer 13) |
| `auto-gotsport-event-scrape.yml` | Mon & Thu 6:00 AM UTC | Tournament bracket scraping |
| `tgs-event-scrape-import.yml` | Sun 6:30 AM UTC | TGS event data |
| `data-hygiene-weekly.yml` | Sun 5:00 PM UTC | Age correction, duplicate removal, state backfill |
| `unknown-opponent-hygiene-weekly.yml` | Weekly | Resolve "Unknown" opponent entries |
| `auto-merge-queue.yml` | Post-import | Auto-approve low-risk team merges |
| `modular11-weekly-scrape.yml` | Manual dispatch | MLS NEXT league scraping |
| `modular11-events-weekly-scrape.yml` | Weekly | MLS NEXT event scraping |
| `update-missing-club-names.yml` | Weekly | Club name backfill |
| `fix-age-year-discrepancies.yml` | Manual dispatch | Age/birth year corrections |
| `match-state-from-club.yml` | Manual dispatch | State metadata backfill |
| `scrape-specific-event.yml` | Manual dispatch | Ad-hoc event scraping |
| `process-missing-games.yml` | Manual dispatch | Missing game recovery |
| `wa-scraper.yml` | Manual dispatch | Washington state scraper |

**Weekly Cycle:**

```
Monday AM  → Scrape games (2 batches, 25K teams each)
Monday PM  → Calculate rankings (v53e + ML Layer 13)
Sunday     → Data hygiene, event scraping
Continuous → Merge queue processing, club name backfill
```

**Concurrency:** Workflows use concurrency locks to prevent overlapping runs of the same job.

### Frontend Deployment (Vercel)

- **Build**: `npm run build` (Next.js static + SSR + ISR)
- **ISR**: Team detail pages use Incremental Static Regeneration
- **Security headers**: CSP, X-Frame-Options, HSTS, Strict-Transport-Security
- **SEO**: Automatic www → non-www redirect (301), canonical URLs
- **Image optimization**: Remote patterns for `images.pitchrank.io`

### Monitoring

| Tool | Purpose |
|------|---------|
| Google Analytics 4 | User behavior, page views, conversions |
| `build_logs` table | ETL execution metrics (JSONB), duration tracking |
| Streamlit Dashboard | Real-time data quality, import status, merge queue |
| GitHub Actions logs | Workflow execution history |

---

## 7. SECURITY CONSIDERATIONS

### Authentication

| Method | Implementation | Scope |
|--------|---------------|-------|
| **Supabase Auth** | OAuth 2.0 (Google, GitHub) + email/password | End-user authentication |
| **Supabase Anon Key** | Public API key with RLS restrictions | Frontend read-only access |
| **Supabase Service Role Key** | Elevated-privilege key | Backend operations (bypasses RLS) |
| **Stripe Webhook Signing** | HMAC signature verification | Payment webhook validation |

### Authorization Model

- **Row-Level Security (RLS)**: Enabled on user-facing Supabase tables
- **Middleware-based RBAC** (`frontend/middleware.ts`):
  - **Public routes**: `/`, `/rankings`, `/blog/*`, `/methodology`
  - **Auth-required routes**: `/watchlist`, `/compare`, `/teams/*`
  - **Premium-required routes**: Same as auth-required; checks `user_profiles.plan` (free → redirect to `/upgrade`)
  - **Admin routes**: `/mission-control` (requires `plan = 'admin'`)
- **API route protection**: Server-side session validation per API route

### Data Encryption

| Layer | Method |
|-------|--------|
| **In transit** | TLS 1.2+ (enforced by Supabase and Vercel) |
| **At rest** | Supabase-managed PostgreSQL encryption (AES-256) |
| **Secrets** | Environment variables (never committed); `.env` in `.gitignore` |

### Security Practices

- CSP headers configured in `next.config.ts`
- `X-Frame-Options: DENY` to prevent clickjacking
- `Strict-Transport-Security` with `max-age=63072000`
- Stripe PCI compliance via hosted checkout (no card data on PitchRank servers)
- 174 environment variables managed via `.env.example` template; sensitive keys never committed
- Service role key restricted to backend GitHub Actions workflows

---

## 8. DEVELOPMENT & TESTING

### Local Setup

**Prerequisites:** Python 3.11+, Node.js 20+, npm

```bash
# Clone repository
git clone https://github.com/dallasheidt14/PitchRank.git
cd PitchRank

# Backend setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in required values

# Frontend setup
cd frontend
npm install
cp .env.example .env.local  # Fill in Supabase + Stripe keys
npm run dev  # Start development server at localhost:3000
```

### Testing Frameworks

| Layer | Framework | Config | Command |
|-------|-----------|--------|---------|
| **Python unit tests** | pytest 7.4+ | `pyproject.toml` | `python -m pytest tests/` |
| **Python async tests** | pytest-asyncio | `pyproject.toml` | `python -m pytest tests/ -v` |
| **Python coverage** | pytest-cov | — | `python -m pytest --cov=src tests/` |
| **E2E tests** | Playwright 1.58 | `playwright.config.ts` | `npm run test:e2e` |
| **E2E smoke tests** | Playwright | — | `npm run test:e2e:smoke` |
| **E2E API tests** | Playwright | — | `npm run test:e2e:api` |

**E2E Test Suites** (9 files in `frontend/e2e/`):

| Suite | Coverage |
|-------|----------|
| `api.spec.ts` | API endpoint integration |
| `auth.spec.ts` | Authentication flows |
| `homepage.spec.ts` | Landing page rendering |
| `navigation.spec.ts` | Routing and navigation |
| `premium-gating.spec.ts` | Premium access control |
| `rankings.spec.ts` | Rankings page functionality |
| `search.spec.ts` | Team search |
| `static-pages.spec.ts` | Static page rendering |
| `team-detail.spec.ts` | Team detail page |

**Playwright Configuration:**
- Projects: Chromium (desktop), mobile-chrome, API
- Base URL: `https://pitchrank.io` (override with `PLAYWRIGHT_BASE_URL`)

### Code Quality Tools

| Tool | Purpose | Config |
|------|---------|--------|
| **ESLint** | TypeScript/React linting | `eslint.config.mjs` (Next.js preset) |
| **TypeScript** | Static type checking (strict mode) | `tsconfig.json` |
| **black** | Python code formatting | `pyproject.toml` |
| **flake8** | Python linting | `pyproject.toml` |
| **Bundle Analyzer** | Frontend bundle size analysis | `npm run analyze` |

### Development Commands

```bash
# Backend
pip install -r requirements.txt
python scripts/calculate_rankings.py --ml --lookback-days 365   # Full ranking run
python scripts/calculate_rankings.py --ml --dry-run              # Dry run (no DB write)
python scripts/calculate_rankings.py --ml --force-rebuild        # Ignore cache
python scripts/scrape_games.py                                   # Scrape games
python scripts/import_games_enhanced.py --file <path>            # Import CSV
python -m pytest tests/                                          # Run tests

# Frontend
cd frontend
npm run dev           # Development server
npm run build         # Production build
npm run lint          # ESLint
npm run test:e2e      # All E2E tests
npm run test:e2e:smoke  # Smoke tests
npm run test:e2e:api    # API tests
npm run test:e2e:ui     # Interactive UI mode
npm run test:e2e:report # HTML test report
npm run analyze         # Bundle analysis
```

---

## 9. FUTURE CONSIDERATIONS

### Known Technical Debt

- **`src/api/`** — REST API module exists but contains only `__init__.py`; API routes are currently handled by Next.js API routes and direct Supabase queries
- **`current_rankings` table** — Legacy backward-compatible view; should be consolidated with `rankings_full`
- **`config/settings.py`** — 12K+ lines of monolithic configuration; could benefit from modularization
- **`dashboard.py`** — 6K-line Streamlit dashboard; could be migrated to the Next.js admin panel (`/mission-control`)
- **`frontend/lib/api.ts`** — 40K+ line API client; would benefit from code splitting
- **`frontend/lib/matchPredictor.ts`** — 30K+ line prediction module; could be modularized
- **Dual scraper frameworks** — `src/scrapers/` (requests/BS4) and `scrapers/` (Scrapy) coexist; could be unified

### Planned Migrations

- Consolidation of admin functionality from Streamlit → Next.js `/mission-control`
- Potential dedicated Python API server (`src/api/`) to decouple backend from GitHub Actions–only execution
- Team identity resolution (`src/identity/`) module under active development

### Potential Roadmap Items

- Real-time game updates (currently weekly batch)
- Mobile application
- Advanced match prediction features
- Coach/parent notification system
- League-level rankings and tournament brackets
- Enhanced ML models beyond XGBoost Layer 13

---

## 10. GLOSSARY

| Term | Definition |
|------|-----------|
| **v53e** | Version 53e of the PitchRank ranking algorithm; comprises 10 statistical layers |
| **ML Layer 13** | Machine learning enhancement layer using XGBoost to adjust PowerScores via residual prediction |
| **PowerScore** | Composite ranking metric (0.0–1.0); higher = better. Blend of offense, defense, and SOS |
| **SOS** | Strength of Schedule — iterative measure of opponent quality (3 passes, unranked base = 0.35) |
| **Age Anchor** | Scaling factor applied per age group (U10 = 0.40 → U19 = 1.00) to normalize cross-age comparisons |
| **MergeResolver** | Utility that maps deprecated team IDs to their canonical counterparts, supporting cascade merges |
| **ECNL** | Elite Clubs National League — top-tier competitive youth soccer league |
| **ECNL-RL** | ECNL Regional League — second-tier ECNL competition (distinct from ECNL proper) |
| **MLS NEXT** | Major League Soccer's youth development platform |
| **HD** | High Division — MLS NEXT's upper competitive tier |
| **AD** | Academy Division — MLS NEXT's lower competitive tier |
| **DPL** | Development Player League |
| **NPL** | National Premier League |
| **GA** | Girls Academy — elite girls' soccer league |
| **GotSport** | Primary data provider; REST API serving 25K+ team records |
| **TGS** | Total Global Sports — tournament data provider |
| **Modular11** | Data provider for MLS NEXT/HD leagues, scraped via Scrapy |
| **SincSports** | Supplementary data provider (HTML scraping) |
| **AthleteOne** | Conference schedule provider (REST API) |
| **Birth Year vs Age Group** | `14B` = born 2014 = U12 Boys; `U14B` = U14 Boys. The `B`/`G` suffix denotes gender, not age |
| **ISR** | Incremental Static Regeneration — Next.js feature for periodic page rebuilds |
| **RLS** | Row-Level Security — PostgreSQL feature restricting row access per user |
| **PostgREST** | Auto-generated REST API from PostgreSQL schema (used by Supabase) |
| **Quarantine** | Process of flagging invalid game or team records for manual review instead of deletion |
| **Cascade Merge** | When team A → B and B → C, the resolver correctly maps A → C |
| **Review Queue** | Teams matched with 0.75–0.90 fuzzy confidence are queued for human verification |

---

## 11. PROJECT IDENTIFICATION

| Field | Value |
|-------|-------|
| **Project name** | PitchRank |
| **Repository URL** | `https://github.com/dallasheidt14/PitchRank` |
| **Primary contact / team** | Dallas Heidt (@dallasheidt14) |
| **Production URL** | `https://www.pitchrank.io` |
| **Date of last update** | 2026-03-18 |
| **Primary branch** | `main` |
| **License** | Private |
