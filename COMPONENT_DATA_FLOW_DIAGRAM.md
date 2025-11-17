# PitchRank Frontend Component & Data Flow Architecture

## Executive Summary
PitchRank is a Next.js 16 application built with React 19.2, TypeScript, TanStack React Query, and Supabase. This document provides a comprehensive overview of the component architecture, data flow patterns, and integration points.

---

## Technology Stack

### Core Framework
- **Next.js 16.0.1** - App Router with Server Components & ISR
- **React 19.2.0** - UI library
- **TypeScript 5** - Type safety

### Data Management
- **Supabase JS 2.81.1** - Backend-as-a-Service (PostgreSQL)
- **TanStack React Query 5.90.7** - Server state management, caching, & data fetching
- **localStorage** - Client-side persistence (watchlist, scrape requests, theme)

### UI & Styling
- **Tailwind CSS 4** - Utility-first CSS
- **Radix UI** - Accessible component primitives
- **Recharts 3.4.1** - Data visualization
- **Lucide React** - Icon library
- **Fuse.js 7.1.0** - Fuzzy search

### Performance
- **TanStack Virtual 3.13.12** - Virtualized lists
- **React Query** - Request deduplication & caching

---

## Database Schema (Supabase/PostgreSQL)

### Core Tables

```
┌─────────────────────────────────────────────────────────────────┐
│                         CORE TABLES                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐      ┌──────────────┐      ┌───────────────┐ │
│  │  providers   │      │    teams     │      │     games     │ │
│  ├──────────────┤      ├──────────────┤      ├───────────────┤ │
│  │ id (PK)      │◄─────│ provider_id  │      │ id (PK)       │ │
│  │ code         │      │ id (PK)      │      │ home_team_id─┼─┤
│  │ name         │      │ team_id_     │◄─────│ away_team_id─┼─┤
│  │ base_url     │      │  master (UK) │      │ home_score    │ │
│  └──────────────┘      │ team_name    │      │ away_score    │ │
│                        │ club_name    │      │ game_date     │ │
│                        │ state_code   │      │ competition   │ │
│                        │ age_group    │      │ source_url    │ │
│                        │ gender       │      │ scraped_at    │ │
│                        └──────────────┘      └───────────────┘ │
│                                                                  │
│  ┌──────────────────┐    ┌───────────────────┐                 │
│  │ rankings_full    │    │ current_rankings  │                 │
│  ├──────────────────┤    ├───────────────────┤                 │
│  │ team_id (PK,FK)  │    │ team_id (PK,FK)   │                 │
│  │ age_group        │    │ national_rank     │                 │
│  │ gender           │    │ national_power_   │                 │
│  │ state_code       │    │  score            │                 │
│  │ games_played     │    │ state_rank        │                 │
│  │ wins/losses/     │    │ games_played      │                 │
│  │  draws           │    │ wins/losses/draws │                 │
│  │ power_score_     │    │ strength_of_      │                 │
│  │  final           │    │  schedule         │                 │
│  │ sos_norm         │    │ global_power_     │                 │
│  │ off_norm         │    │  score            │                 │
│  │ def_norm         │    └───────────────────┘                 │
│  │ powerscore_ml    │                                           │
│  │ rank_in_cohort   │    ┌───────────────────┐                 │
│  │ exp_margin       │    │ scrape_requests   │                 │
│  │ exp_win_rate     │    ├───────────────────┤                 │
│  └──────────────────┘    │ id (PK)           │                 │
│                          │ team_id_master    │                 │
│                          │ game_date         │                 │
│                          │ status            │                 │
│                          │ games_found       │                 │
│                          └───────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

### Database Views (Computed)

```
┌──────────────────────────────────────────────────────────────┐
│                      DATABASE VIEWS                           │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────────┐  ┌──────────────────────────────┐  │
│  │  rankings_view      │  │  state_rankings_view         │  │
│  ├─────────────────────┤  ├──────────────────────────────┤  │
│  │ team_id_master      │  │ team_id_master               │  │
│  │ team_name           │  │ team_name                    │  │
│  │ club_name           │  │ club_name                    │  │
│  │ state               │  │ state                        │  │
│  │ age (INTEGER)       │  │ age (INTEGER)                │  │
│  │ gender (M/F/B/G)    │  │ gender (M/F/B/G)             │  │
│  │ power_score_final   │  │ power_score_final            │  │
│  │ sos_norm            │  │ sos_norm                     │  │
│  │ offense_norm        │  │ offense_norm                 │  │
│  │ defense_norm        │  │ defense_norm                 │  │
│  │ rank_in_cohort_     │  │ rank_in_cohort_final         │  │
│  │  final              │  │ rank_in_state_final (UNIQUE) │  │
│  │ games_played        │  │ games_played                 │  │
│  │ wins/losses/draws   │  │ wins/losses/draws            │  │
│  │ win_percentage      │  │ win_percentage               │  │
│  └─────────────────────┘  └──────────────────────────────┘  │
│        (National)               (State-specific)             │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  team_predictive_view                                │    │
│  ├──────────────────────────────────────────────────────┤    │
│  │ team_id_master                                       │    │
│  │ exp_margin         (Expected goal margin)            │    │
│  │ exp_win_rate       (Expected win probability)        │    │
│  │ exp_goals_for      (Computed/stored)                 │    │
│  │ exp_goals_against  (Computed/stored)                 │    │
│  │ power_score_final                                    │    │
│  │ sos_norm                                             │    │
│  │ offense_norm / defense_norm                          │    │
│  └──────────────────────────────────────────────────────┘    │
│        (ML-powered predictions)                              │
└──────────────────────────────────────────────────────────────┘
```

---

## API Layer (`frontend/lib/api.ts`)

The API layer encapsulates all Supabase database queries and provides a clean interface for React Query hooks.

```
┌────────────────────────────────────────────────────────────────┐
│                      API FUNCTIONS                             │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  api.getRankings(region?, ageGroup?, gender?)                  │
│  ├─ Uses: rankings_view OR state_rankings_view                 │
│  ├─ Filters: state, age (normalized), gender                   │
│  ├─ Sorting: power_score_final DESC                            │
│  └─ Returns: RankingWithTeam[]                                 │
│                                                                 │
│  api.getTeam(id)                                               │
│  ├─ Query 1: teams table → Team data                           │
│  ├─ Query 2: rankings_view → Ranking stats                     │
│  ├─ Merges: TeamWithRanking                                    │
│  └─ Returns: TeamWithRanking (team + ranking merged)           │
│                                                                 │
│  api.getTeamGames(id, limit=50)                                │
│  ├─ Query 1: games table → games[]                             │
│  ├─ Query 2: teams table → team names/clubs                    │
│  ├─ Enriches: games with team names                            │
│  ├─ Computes: lastScrapedAt (most recent scraped_at)           │
│  └─ Returns: { games: GameWithTeams[], lastScrapedAt }         │
│                                                                 │
│  api.getTeamTrajectory(id, periodDays=30)                      │
│  ├─ Query: games table → all team games                        │
│  ├─ Aggregates: by time periods (periodDays)                   │
│  ├─ Calculates: win%, avg goals for/against per period         │
│  └─ Returns: TeamTrajectory[]                                  │
│                                                                 │
│  api.getCommonOpponents(team1Id, team2Id)                      │
│  ├─ Query 1: games for team1                                   │
│  ├─ Query 2: games for team2                                   │
│  ├─ Intersection: find common opponent IDs                     │
│  ├─ Query 3: fetch opponent names                              │
│  └─ Returns: Array<CommonOpponent>                             │
│                                                                 │
│  api.getPredictive(teamId)                                     │
│  ├─ Query: team_predictive_view                                │
│  ├─ Graceful: returns null if view doesn't exist               │
│  └─ Returns: TeamPredictive | null                             │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## React Query Hooks (`frontend/lib/hooks.ts` & `frontend/hooks/`)

### Hook Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    REACT QUERY HOOKS                             │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  useRankings(region?, ageGroup?, gender?)                        │
│  ├─ Query Key: ['rankings', region, ageGroup, gender]            │
│  ├─ API: api.getRankings()                                       │
│  ├─ Stale Time: 5 minutes                                        │
│  ├─ Cache Time: 30 minutes                                       │
│  └─ Used by: RankingsTable, HomeLeaderboard, ComparePanel        │
│                                                                   │
│  useTeam(id)                                                     │
│  ├─ Query Key: ['team', id]                                      │
│  ├─ API: api.getTeam(id)                                         │
│  ├─ Stale Time: 10 minutes                                       │
│  ├─ Cache Time: 60 minutes                                       │
│  ├─ Retry: 1                                                     │
│  └─ Used by: TeamHeader, GameHistoryTable, ComparePanel          │
│                                                                   │
│  useTeamGames(id, limit=50)                                      │
│  ├─ Query Key: ['team-games', id, limit]                         │
│  ├─ API: api.getTeamGames(id, limit)                             │
│  ├─ Stale Time: 2 minutes                                        │
│  ├─ Cache Time: 15 minutes                                       │
│  └─ Used by: GameHistoryTable                                    │
│                                                                   │
│  useTeamTrajectory(id, periodDays=30)                            │
│  ├─ Query Key: ['team-trajectory', id, periodDays]               │
│  ├─ API: api.getTeamTrajectory(id, periodDays)                   │
│  ├─ Stale Time: 5 minutes                                        │
│  ├─ Cache Time: 30 minutes                                       │
│  └─ Used by: TeamTrajectoryChart, ComparePanel                   │
│                                                                   │
│  useCommonOpponents(team1Id, team2Id)                            │
│  ├─ Query Key: ['common-opponents', team1Id, team2Id]            │
│  ├─ API: api.getCommonOpponents(team1Id, team2Id)                │
│  ├─ Enabled: when both team IDs exist                            │
│  ├─ Stale Time: 5 minutes                                        │
│  └─ Used by: ComparePanel                                        │
│                                                                   │
│  usePredictive(teamId)                                           │
│  ├─ Query Key: ['predictive', teamId]                            │
│  ├─ API: api.getPredictive(teamId)                               │
│  ├─ Retry: false (graceful degradation)                          │
│  ├─ Stale Time: 5 minutes                                        │
│  └─ Used by: PredictedMatchCard, ComparePanel                    │
│                                                                   │
│  useTeamSearch()                                                 │
│  ├─ Query Key: ['team-search']                                   │
│  ├─ Fetches: ALL teams via pagination (teams table)              │
│  ├─ Transforms: to RankingRow format with defaults               │
│  ├─ Stale Time: 10 minutes                                       │
│  ├─ Cache Time: 60 minutes                                       │
│  └─ Used by: GlobalSearch, TeamSelector                          │
│                                                                   │
│  usePrefetchTeam()                                               │
│  ├─ Returns: prefetch function (id) => void                      │
│  ├─ Prefetches: team data on hover                               │
│  └─ Used by: RankingsTable, GameHistoryTable (link hovers)       │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### React Query Configuration (providers.tsx)

```typescript
QueryClient Config:
  - staleTime: 60 seconds (default)
  - refetchOnWindowFocus: false
  - refetchOnMount: true
  - retry: only on network errors (up to 3 times)
  - retryDelay: exponential backoff (2^attemptIndex * 1000ms)
  - Automatic request deduplication by query key
```

---

## Component Architecture

### Page Components (App Router)

```
┌─────────────────────────────────────────────────────────────────┐
│                         PAGES                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  app/page.tsx (Home Page)                                       │
│  ├─ Client Component                                            │
│  ├─ Uses: useRankings(null, 'u12', 'M')                         │
│  ├─ Child Components:                                            │
│  │   ├─ PageHeader                                              │
│  │   ├─ HomeLeaderboard                                         │
│  │   ├─ Recent Movers card                                      │
│  │   └─ Quick Links card                                        │
│  └─ Features: Logo, leaderboard preview, recent movers          │
│                                                                  │
│  app/rankings/page.tsx (Rankings Page)                          │
│  ├─ Client Component                                            │
│  ├─ State: region, ageGroup, gender (local)                     │
│  ├─ Child Components:                                            │
│  │   ├─ PageHeader                                              │
│  │   ├─ RankingsFilter (controls state)                         │
│  │   └─ RankingsTable (consumes state)                          │
│  └─ Features: Filter controls, full rankings table              │
│                                                                  │
│  app/rankings/[region]/[ageGroup]/[gender]/page.tsx             │
│  ├─ Server Component (future enhancement)                       │
│  └─ Dynamic route for SEO/deep linking                          │
│                                                                  │
│  app/teams/[id]/page.tsx (Team Detail Page)                     │
│  ├─ Server Component (ISR enabled, revalidate: 3600s)           │
│  ├─ generateMetadata(): Dynamic SEO meta tags                   │
│  ├─ Child: TeamPageShell (client component)                     │
│  └─ Features: Team profile, games, trajectory, momentum         │
│                                                                  │
│  app/compare/page.tsx (Compare Page)                            │
│  ├─ Client Component                                            │
│  ├─ Child Components:                                            │
│  │   ├─ PageHeader                                              │
│  │   └─ ComparePanel                                            │
│  └─ Features: Side-by-side team comparison                      │
│                                                                  │
│  app/methodology/page.tsx (Methodology Page)                    │
│  ├─ Client Component                                            │
│  ├─ Child: MethodologySection                                   │
│  └─ Features: Ranking methodology explanation                   │
│                                                                  │
│  app/layout.tsx (Root Layout)                                   │
│  ├─ Server Component                                            │
│  ├─ Wraps all pages with:                                       │
│  │   ├─ Providers (React Query)                                 │
│  │   ├─ Navigation (sticky header)                              │
│  │   ├─ Toaster (notifications)                                 │
│  │   └─ Theme initialization script                             │
│  └─ Features: Global styles, fonts, SEO meta                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Feature Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    FEATURE COMPONENTS                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  RankingsTable                                                  │
│  ├─ Props: region, ageGroup, gender                             │
│  ├─ Hooks: useRankings(region, ageGroup, gender)                │
│  ├─ Features:                                                    │
│  │   ├─ Virtualized rendering (TanStack Virtual)                │
│  │   ├─ Sortable columns (rank, team, powerScore, win%, etc.)   │
│  │   ├─ Dynamic SOS rank calculation within cohort              │
│  │   ├─ Visual rank badges (top 3, top 10)                      │
│  │   ├─ Responsive grid layout                                  │
│  │   └─ Hover prefetching for team links                        │
│  └─ Performance: ~600px viewport, overscan=5                    │
│                                                                  │
│  TeamPageShell                                                  │
│  ├─ Props: id (team_id_master)                                  │
│  ├─ Layout: Container for team detail page                      │
│  ├─ Child Components:                                            │
│  │   ├─ BackToRankingsButton (preserves filter state)           │
│  │   ├─ TeamHeader                                              │
│  │   ├─ GameHistoryTable                                        │
│  │   ├─ MomentumMeter (lazy loaded)                             │
│  │   └─ TeamTrajectoryChart (lazy loaded)                       │
│  └─ Features: Suspense boundaries, dynamic imports              │
│                                                                  │
│  TeamHeader                                                     │
│  ├─ Props: teamId                                               │
│  ├─ Hooks: useTeam(teamId)                                      │
│  ├─ Features:                                                    │
│  │   ├─ Team name, club, state, age/gender badges               │
│  │   ├─ PowerScore (ML Adjusted) display                        │
│  │   ├─ National/State rank                                     │
│  │   ├─ Games played, win percentage                            │
│  │   ├─ Record (W-L-D)                                          │
│  │   ├─ SOS Index with tooltip                                  │
│  │   └─ Watch/Unwatch button (localStorage)                     │
│  └─ State: watched (localStorage)                               │
│                                                                  │
│  GameHistoryTable                                               │
│  ├─ Props: teamId, limit?, teamName?                            │
│  ├─ Hooks: useTeamGames(teamId, limit), useTeam(teamId)         │
│  ├─ Features:                                                    │
│  │   ├─ Table of games (date, opponent, result, score)          │
│  │   ├─ Opponent links with hover prefetch                      │
│  │   ├─ ML over/underperformance indicators (colored results)   │
│  │   ├─ Last updated timestamp                                  │
│  │   ├─ MissingGamesForm (request scrapes)                      │
│  │   └─ Competition/division info                               │
│  └─ Default limit: 10000 (all games)                            │
│                                                                  │
│  TeamTrajectoryChart                                            │
│  ├─ Props: teamId                                               │
│  ├─ Hooks: useTeamTrajectory(teamId, 30)                        │
│  ├─ Library: Recharts (LineChart)                               │
│  ├─ Features:                                                    │
│  │   ├─ Performance over time (30-day periods)                  │
│  │   ├─ Multiple metrics: win%, goals for/against               │
│  │   └─ Responsive chart                                        │
│  └─ Lazy loaded via dynamic import                              │
│                                                                  │
│  MomentumMeter                                                  │
│  ├─ Props: teamId                                               │
│  ├─ Hooks: useTeamGames(teamId, 10)                             │
│  ├─ Features:                                                    │
│  │   ├─ Recent form indicator (last 10 games)                   │
│  │   ├─ Win/loss/draw breakdown                                 │
│  │   ├─ Visual momentum meter (gauge)                           │
│  │   └─ Trend indicator (hot/cold streaks)                      │
│  └─ Lazy loaded via dynamic import                              │
│                                                                  │
│  ComparePanel                                                   │
│  ├─ State: team1Id, team2Id, team1Data, team2Data               │
│  ├─ Hooks:                                                       │
│  │   ├─ useTeam(team1Id), useTeam(team2Id)                      │
│  │   ├─ useTeamTrajectory(team1Id), useTeamTrajectory(team2Id)  │
│  │   ├─ useCommonOpponents(team1Id, team2Id)                    │
│  │   ├─ usePredictive(team1Id), usePredictive(team2Id)          │
│  │   └─ useRankings() (for percentile calculation)              │
│  ├─ Child Components:                                            │
│  │   ├─ TeamSelector (x2)                                       │
│  │   ├─ PredictedMatchCard                                      │
│  │   ├─ BarChart (side-by-side comparison)                      │
│  │   ├─ LineChart (trajectory comparison)                       │
│  │   └─ Common Opponents cards                                  │
│  ├─ Features:                                                    │
│  │   ├─ Swap teams button                                       │
│  │   ├─ Percentile bars for metrics                             │
│  │   ├─ Parallel data fetching                                  │
│  │   └─ Graceful error handling                                 │
│  └─ Performance: Memoized calculations                          │
│                                                                  │
│  PredictedMatchCard                                             │
│  ├─ Props: teamA, teamB, teamAName, teamBName                   │
│  ├─ Data: TeamPredictive (from team_predictive_view)            │
│  ├─ Features:                                                    │
│  │   ├─ Expected margin prediction                              │
│  │   ├─ Expected win rate (%)                                   │
│  │   ├─ Expected goals for/against                              │
│  │   └─ ML-powered match simulation                             │
│  └─ Graceful: Shows fallback if no predictive data              │
│                                                                  │
│  GlobalSearch                                                   │
│  ├─ Hooks: useTeamSearch()                                      │
│  ├─ Library: Fuse.js (fuzzy search)                             │
│  ├─ State: searchQuery, isOpen, selectedIndex                   │
│  ├─ Features:                                                    │
│  │   ├─ Fuzzy search across all teams                           │
│  │   ├─ Search by: team_name (70%), club_name (20%), state (10%)│
│  │   ├─ Keyboard navigation (arrows, enter, escape)             │
│  │   ├─ Highlighted matches                                     │
│  │   ├─ Auto-scroll selected item into view                     │
│  │   ├─ Click-outside to close                                  │
│  │   └─ Shows rank, age group, gender in results                │
│  └─ Performance: Limits to 8 results, threshold=0.3             │
│                                                                  │
│  TeamSelector                                                   │
│  ├─ Props: label, value, onChange, excludeTeamId                │
│  ├─ Hooks: useTeamSearch()                                      │
│  ├─ Library: Fuse.js                                            │
│  ├─ Features:                                                    │
│  │   ├─ Searchable team dropdown                                │
│  │   ├─ Filters out excluded team                               │
│  │   ├─ Shows team details in dropdown                          │
│  │   └─ Callback with team ID and full team data                │
│  └─ Used by: ComparePanel                                       │
│                                                                  │
│  RankingsFilter                                                 │
│  ├─ Props: onFilterChange(region, ageGroup, gender)             │
│  ├─ Features:                                                    │
│  │   ├─ Region selector (National + 50 states)                  │
│  │   ├─ Age group selector (U10-U18)                            │
│  │   ├─ Gender selector (Male/Female)                           │
│  │   └─ Radix UI Select components                              │
│  └─ Controlled by: RankingsPage state                           │
│                                                                  │
│  HomeLeaderboard                                                │
│  ├─ Hooks: useRankings(null, 'u12', 'M')                        │
│  ├─ Features:                                                    │
│  │   ├─ Shows top 10 teams                                      │
│  │   ├─ Quick preview on homepage                               │
│  │   └─ Links to full rankings                                  │
│  └─ Default: U12 Boys National                                  │
│                                                                  │
│  MissingGamesForm                                               │
│  ├─ Props: teamId, teamName                                     │
│  ├─ Features:                                                    │
│  │   ├─ Dialog for requesting missing game scrapes              │
│  │   ├─ Date picker for game date                               │
│  │   ├─ Submits to /api/scrape-missing-game                     │
│  │   ├─ Tracks request ID in localStorage                       │
│  │   └─ Toast notifications on submit                           │
│  └─ Used by: GameHistoryTable                                   │
│                                                                  │
│  Navigation                                                     │
│  ├─ State: mobileMenuOpen                                       │
│  ├─ Child Components:                                            │
│  │   ├─ GlobalSearch                                            │
│  │   └─ ThemeToggle                                             │
│  ├─ Features:                                                    │
│  │   ├─ Sticky header                                           │
│  │   ├─ Logo with dark mode variants                            │
│  │   ├─ Desktop nav links                                       │
│  │   ├─ Mobile hamburger menu                                   │
│  │   └─ Responsive search bar                                   │
│  └─ Layout: Container, flex, responsive breakpoints             │
│                                                                  │
│  ThemeToggle                                                    │
│  ├─ State: theme (localStorage: 'light' | 'dark' | null)        │
│  ├─ Features:                                                    │
│  │   ├─ Toggle light/dark mode                                  │
│  │   ├─ Persists to localStorage                                │
│  │   ├─ Applies class to <html> element                         │
│  │   └─ System preference detection                             │
│  └─ Icon: Sun/Moon (Lucide)                                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### UI Components (`components/ui/`)

```
┌──────────────────────────────────────────────────────────────┐
│                     UI COMPONENTS                             │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  Card, CardHeader, CardTitle, CardDescription, CardContent   │
│  Button, Badge, Input, Label                                 │
│  Select, SelectTrigger, SelectContent, SelectItem            │
│  Dialog, DialogTrigger, DialogContent, DialogHeader          │
│  Table, TableHeader, TableBody, TableRow, TableCell          │
│  Tooltip, TooltipTrigger, TooltipContent                     │
│  Toaster (toast notifications via Sonner pattern)            │
│  Skeleton, LoadingStates (spinners, inline loaders)          │
│  ErrorDisplay (retry button, fallback UI)                    │
│  LastUpdated (timestamp display)                             │
│                                                               │
│  All UI components:                                          │
│  - Built on Radix UI primitives                             │
│  - Styled with Tailwind CSS                                 │
│  - Class variance authority (CVA) for variants              │
│  - Full keyboard accessibility                              │
│  - Dark mode support                                        │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## Data Flow Patterns

### 1. Rankings Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                    RANKINGS DATA FLOW                             │
└──────────────────────────────────────────────────────────────────┘

User → RankingsPage → RankingsFilter
                         │
                         ▼ (state change)
                   region, ageGroup, gender
                         │
                         ▼
                   RankingsTable
                         │
                         ▼
                   useRankings(region, ageGroup, gender)
                         │
                         ▼
      React Query Cache Check (stale < 5 min?)
                    │            │
               [Cache Hit]   [Cache Miss/Stale]
                    │            │
                    │            ▼
                    │     api.getRankings()
                    │            │
                    │            ▼
                    │     Supabase Query:
                    │     - rankings_view (national)
                    │     - state_rankings_view (state)
                    │     - Filter: age, gender, state
                    │     - Order: power_score_final DESC
                    │            │
                    │            ▼
                    │     RankingRow[] (typed)
                    │            │
                    └────────────┘
                         │
                         ▼
           React Query stores in cache
                         │
                         ▼
                   RankingsTable receives data
                         │
                         ├─ Compute SOS ranks (memoized)
                         ├─ Apply sorting (user-controlled)
                         ├─ Virtualize rendering (TanStack Virtual)
                         │
                         ▼
                   Render virtualized rows
                         │
                         ▼
                   User clicks team link
                         │
                         ▼
                   Prefetch team data (onMouseEnter)
                         │
                         ▼
                   Navigate to /teams/[id]
```

### 2. Team Detail Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                   TEAM DETAIL DATA FLOW                           │
└──────────────────────────────────────────────────────────────────┘

User → /teams/[id] → TeamPageShell(id)
                         │
         ┌───────────────┼───────────────┬──────────────┐
         │               │               │              │
         ▼               ▼               ▼              ▼
   TeamHeader    GameHistoryTable  MomentumMeter  TeamTrajectoryChart
         │               │               │              │
         ▼               ▼               ▼              ▼
   useTeam(id)    useTeamGames(id)  useTeamGames  useTeamTrajectory
         │               │            (limit=10)       (30 days)
         │               │               │              │
         ▼               ▼               ▼              ▼
   React Query    React Query      React Query    React Query
   Cache Check    Cache Check      Cache Check    Cache Check
         │               │               │              │
         ▼               ▼               ▼              ▼
   api.getTeam()  api.getTeamGames() [cached]    api.getTeamTrajectory()
         │               │                              │
         ▼               ▼                              ▼
   Supabase:      Supabase:                      Supabase:
   1. teams       1. games (ORDER BY              1. games
   2. rankings_      game_date DESC)              2. Aggregate by
      view        2. teams (team names)              time periods
         │               │                              │
         ▼               ▼                              ▼
   TeamWithRanking  { games:           TeamTrajectory[]
   (merged)         GameWithTeams[],   (win%, goals)
                    lastScrapedAt }
         │               │                              │
         └───────────────┴──────────────────────────────┘
                         │
                         ▼
               All components render concurrently
                         │
                         ▼
          React Suspense resolves → Page fully hydrated
```

### 3. Compare Teams Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                  COMPARE TEAMS DATA FLOW                          │
└──────────────────────────────────────────────────────────────────┘

User → ComparePage → ComparePanel
                         │
                         ▼
         User selects Team 1 via TeamSelector
                         │
                         ▼ (state: team1Id, team1Data)
           ┌─────────────┴─────────────┬─────────────┐
           │                           │             │
           ▼                           ▼             ▼
   useTeam(team1Id)      useTeamTrajectory(team1Id)  usePredictive
           │                           │             (team1Id)
           │                           │             │
   User selects Team 2 via TeamSelector │             │
           │                           │             │
           ▼ (state: team2Id, team2Data)│             │
   ┌───────┴─────────┬─────────────────┼─────────────┤
   │                 │                 │             │
   ▼                 ▼                 ▼             ▼
useTeam(team2Id)  useTeamTrajectory  usePredictive  useCommonOpponents
                  (team2Id)          (team2Id)      (team1Id,team2Id)
   │                 │                 │             │
   └─────────────────┴─────────────────┴─────────────┘
                         │
                         ▼
         useRankings() - for percentile calculation
                         │
                         ▼
           All queries execute in parallel
                         │
                         ▼
         React Query manages caching/refetching
                         │
                         ▼
         ComparePanel receives all data
                         │
         ├─ Compute percentiles (memoized)
         ├─ Prepare trajectory chart data (memoized)
         ├─ Prepare comparison chart data
         │
         ▼
   Render comparison UI:
   - Side-by-side stats cards
   - PredictedMatchCard (ML predictions)
   - BarChart (comparison)
   - LineChart (trajectory)
   - Common opponents list
```

### 4. Global Search Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                   GLOBAL SEARCH DATA FLOW                         │
└──────────────────────────────────────────────────────────────────┘

Navigation → GlobalSearch (mounted)
                 │
                 ▼
         useTeamSearch() (on mount)
                 │
                 ▼
         React Query Cache Check
                 │
                 ▼ [Cache Miss]
         Fetch ALL teams via pagination
         (teams table, batches of 1000)
                 │
                 ▼
         Transform to RankingRow format
         (with default ranking values)
                 │
                 ▼
         React Query caches RankingRow[]
                 │
                 ▼
         User types in search input
                 │
                 ▼
         searchQuery state updates
                 │
                 ▼
         Fuse.js fuzzy search (memoized)
         - Keys: team_name (70%), club_name (20%), state (10%)
         - Threshold: 0.3
         - Min match length: 2
                 │
                 ▼
         Results (top 8) → dropdown
                 │
                 ▼
         User navigates with keyboard/mouse
         (arrows, enter, click)
                 │
                 ▼
         Navigate to /teams/[id]
```

### 5. Scrape Request Flow

```
┌──────────────────────────────────────────────────────────────────┐
│              MISSING GAME SCRAPE REQUEST FLOW                     │
└──────────────────────────────────────────────────────────────────┘

GameHistoryTable → MissingGamesForm
                         │
                         ▼
         User fills game date, clicks submit
                         │
                         ▼
         POST /api/scrape-missing-game
         Body: { teamId, gameDate, teamName }
                         │
                         ▼
         Next.js API Route:
         1. Validate request
         2. Insert into scrape_requests table
         3. Return request ID
                         │
                         ▼
         Frontend receives request ID
                         │
                         ├─ Track in localStorage
                         │  (scrape_request_ids array)
                         │
                         └─ Show success toast
                         │
                         ▼
         useScrapeRequestNotifications hook
         (Supabase Realtime subscription)
                         │
                         ▼
         Listen for UPDATE on scrape_requests
         WHERE status = 'completed'
                         │
                         ▼
         Match request ID with localStorage
                         │
                         ▼
         Show notification toast:
         - "Game Data Added!" (games_found > 0)
         - "No Games Found" (games_found = 0)
                         │
                         ▼
         Remove request ID from localStorage
                         │
                         ▼
         User sees updated game history
         (React Query refetch or cache invalidation)
```

---

## State Management

### Server State (React Query)
```
┌────────────────────────────────────────────────────────────────┐
│  Query Key Structure:                                          │
│  - ['rankings', region, ageGroup, gender]                      │
│  - ['team', teamId]                                            │
│  - ['team-games', teamId, limit]                               │
│  - ['team-trajectory', teamId, periodDays]                     │
│  - ['common-opponents', team1Id, team2Id]                      │
│  - ['predictive', teamId]                                      │
│  - ['team-search']                                             │
│                                                                 │
│  Automatic Features:                                           │
│  - Request deduplication (same query key)                      │
│  - Background refetching (staleTime expiry)                    │
│  - Garbage collection (gcTime)                                 │
│  - Optimistic updates (mutations)                              │
│  - Retry logic with exponential backoff                        │
│  - Error boundary integration                                  │
└────────────────────────────────────────────────────────────────┘
```

### Client State (Local)
```
┌────────────────────────────────────────────────────────────────┐
│  localStorage:                                                  │
│  - 'theme' → 'light' | 'dark' | null                           │
│  - 'pitchrank_watchedTeams' → string[] (team_id_master UUIDs)  │
│  - 'scrape_request_ids' → string[] (scrape request UUIDs)      │
│                                                                 │
│  Component State (useState):                                   │
│  - RankingsPage: region, ageGroup, gender                      │
│  - ComparePanel: team1Id, team2Id, team1Data, team2Data        │
│  - GlobalSearch: searchQuery, isOpen, selectedIndex            │
│  - Navigation: mobileMenuOpen                                  │
│  - TeamHeader: watched (synced from localStorage)              │
│  - ThemeToggle: theme (synced from localStorage)               │
└────────────────────────────────────────────────────────────────┘
```

### URL State (Next.js Router)
```
┌────────────────────────────────────────────────────────────────┐
│  Dynamic Routes:                                                │
│  - /teams/[id] → params.id = team_id_master UUID               │
│  - /rankings/[region]/[ageGroup]/[gender]                      │
│                                                                 │
│  Query Params:                                                  │
│  - /teams/[id]?region=ca&ageGroup=u12&gender=male              │
│    → BackToRankingsButton preserves filter state               │
└────────────────────────────────────────────────────────────────┘
```

---

## Performance Optimizations

### 1. React Query Caching Strategy
```
- Rankings: 5 min stale, 30 min cache
- Team details: 10 min stale, 60 min cache
- Games: 2 min stale, 15 min cache
- Team search: 10 min stale, 60 min cache
- Request deduplication: Automatic
```

### 2. Component-Level Optimizations
```
- useMemo: percentile calculations, trajectory data, SOS ranks
- useCallback: event handlers, prefetch functions
- React.memo: not heavily used (React 19 auto-optimizes)
- Lazy loading: TeamTrajectoryChart, MomentumMeter (dynamic imports)
- Code splitting: Automatic (Next.js)
```

### 3. Rendering Optimizations
```
- Virtualization: RankingsTable (TanStack Virtual)
  → Renders only visible rows (~600px viewport)
  → Overscan: 5 rows above/below

- Suspense boundaries: Team pages, lazy components
- ISR (Incremental Static Regeneration): Team pages (revalidate: 3600s)
```

### 4. Data Fetching Optimizations
```
- Prefetching: Team data on link hover (usePrefetchTeam)
- Parallel fetching: ComparePanel fetches all data concurrently
- Pagination: useTeamSearch (teams table, 1000 per batch)
- Field selection: Only fetch required fields from Supabase
```

### 5. Network Optimizations
```
- Retry logic: Network errors only, exponential backoff
- Request deduplication: React Query automatic
- Connection pooling: Supabase client (singleton)
```

---

## Error Handling

### React Query Error Handling
```typescript
// Global config (providers.tsx)
retry: (failureCount, error) => {
  return isNetworkError(error) ? failureCount < 3 : false;
}

// Hook-level
isError, error → passed to <ErrorDisplay />
```

### Component Error Boundaries
```
- ErrorDisplay component:
  → Shows error message
  → Provides retry button
  → Optional fallback UI
  → Compact mode for inline errors

- Used by: All data-driven components
  (RankingsTable, TeamHeader, GameHistoryTable, etc.)
```

### Graceful Degradation
```
- usePredictive: Returns null if view doesn't exist
  → PredictedMatchCard shows fallback UI

- Team data: Shows loading skeleton → error → empty state
- Rankings: Shows error with retry → fallback to empty
```

---

## Real-time Features

### Supabase Realtime Subscriptions
```typescript
useScrapeRequestNotifications():
  - Channel: 'scrape_requests_changes'
  - Event: UPDATE on scrape_requests table
  - Filter: status = 'completed'
  - Action: Show toast notification
  - Cleanup: Unsubscribe on unmount
```

### localStorage Tracking
```
- Scrape requests: Track submitted request IDs
- Notifications: Match completed requests with tracked IDs
- Auto-cleanup: Remove from localStorage after notification
```

---

## TypeScript Type System

### Core Types (`frontend/lib/types.ts`)

```typescript
Team                 // Raw team data from teams table
Game                 // Raw game data from games table
RankingWithTeam      // View data (rankings_view, state_rankings_view)
TeamWithRanking      // Team + ranking data merged (api.getTeam result)
TeamTrajectory       // Aggregated performance over time
GameWithTeams        // Game + opponent names/clubs
ScrapeRequest        // Scrape request tracking
```

### Additional Types
```typescript
TeamPredictive       // ML predictions (types/TeamPredictive.ts)
RankingRow           // Alias for RankingWithTeam (types/RankingRow.ts)
```

### Type Safety
```
- All API functions fully typed
- All hooks return typed data
- All component props typed
- Strict null checks
- Deprecated field warnings (never type)
```

---

## Accessibility Features

```
┌──────────────────────────────────────────────────────────────┐
│  Keyboard Navigation:                                         │
│  - GlobalSearch: Arrow keys, Enter, Escape                   │
│  - RankingsTable: Tab navigation, sortable columns           │
│  - All buttons: Focus visible rings                          │
│  - Dialogs: Escape to close, focus trap                      │
│                                                               │
│  ARIA Labels:                                                 │
│  - All interactive elements have aria-label                  │
│  - Tooltips: aria-describedby                                │
│  - Search: aria-autocomplete, aria-expanded                  │
│                                                               │
│  Screen Reader Support:                                      │
│  - Semantic HTML (nav, main, header, table)                  │
│  - sr-only class for hidden labels                           │
│  - Role attributes where needed                              │
│                                                               │
│  Visual Accessibility:                                       │
│  - Dark mode support (full app)                              │
│  - High contrast ratios (WCAG AA)                            │
│  - Focus indicators (visible rings)                          │
│  - Color not sole indicator (icons + text)                   │
└──────────────────────────────────────────────────────────────┘
```

---

## SEO & Metadata

### Dynamic Metadata (Team Pages)
```typescript
generateMetadata({ params }):
  - Fetches team data server-side
  - Sets page title: "{team_name} ({state}) | PitchRank"
  - Sets description: "View rankings, trajectory... for {team_name}"
  - OpenGraph tags for social sharing
```

### Static Metadata (Other Pages)
```typescript
Root layout.tsx:
  - metadataBase: NEXT_PUBLIC_SITE_URL
  - title: "PitchRank — Youth Soccer Rankings"
  - description: "Data-powered youth soccer team rankings..."
  - icons, favicon
  - OpenGraph images
```

---

## API Routes (Next.js)

```
/api/scrape-missing-game
  - Method: POST
  - Body: { teamId, gameDate, teamName }
  - Action: Insert into scrape_requests table
  - Returns: { requestId }

/api/process-missing-games
  - Backend processor endpoint (not used by frontend)
  - Reads pending scrape requests
  - Triggers Python scraper
```

---

## Build & Deployment

### Build Configuration
```javascript
// next.config.ts
- TypeScript config
- Tailwind CSS PostCSS plugin
- Image optimization
- Output: standalone (for Docker)
```

### Environment Variables
```
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY
NEXT_PUBLIC_SITE_URL
```

### Deployment Strategy
```
- ISR (Incremental Static Regeneration)
  → Team pages: revalidate every 3600s (1 hour)

- Server Components for metadata generation
- Client Components for interactivity
```

---

## Testing Strategy (Recommended)

### Unit Tests
```
- API functions (api.ts)
- Utility functions (utils.ts)
- Type transformations
```

### Integration Tests
```
- React Query hooks with mock data
- Component rendering with mock hooks
- User interactions (click, type, navigate)
```

### E2E Tests
```
- Critical user flows:
  → Search for team → View details
  → Filter rankings → Navigate to team
  → Compare two teams
  → Submit missing game request
```

---

## Future Enhancements

### Suggested Improvements

1. **Pagination for Rankings**
   - Currently loads all rankings at once
   - Consider infinite scroll or pagination

2. **Advanced Filters**
   - Multiple state selection
   - Power score range filter
   - Games played threshold

3. **Watchlist Dashboard**
   - Dedicated page for watched teams
   - Rank change notifications
   - Recent games for watched teams

4. **PWA (Progressive Web App)**
   - Service worker for offline support
   - Add to homescreen
   - Push notifications

5. **Analytics**
   - Track popular teams
   - Most compared teams
   - Search analytics

6. **Social Features**
   - Share team links (OpenGraph)
   - Embed team cards
   - Twitter/FB integration

7. **Performance**
   - Implement React Server Components more broadly
   - Consider edge runtime for API routes
   - Image optimization (team logos/photos)

---

## Conclusion

PitchRank demonstrates a modern, well-architected React application with:

- **Clean separation of concerns**: API layer, hooks, components
- **Type-safe**: Full TypeScript coverage
- **Performant**: Caching, virtualization, lazy loading, prefetching
- **Accessible**: Keyboard navigation, ARIA labels, semantic HTML
- **Scalable**: React Query for server state, composable components
- **Maintainable**: Clear data flow, consistent patterns, documented

The architecture is production-ready and follows React/Next.js best practices.

---

**Document Version**: 1.0
**Last Updated**: $(date)
**Author**: Claude (Anthropic)
**Review Status**: ✅ Complete
