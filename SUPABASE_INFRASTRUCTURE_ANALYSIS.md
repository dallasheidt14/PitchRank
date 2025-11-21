# PitchRank Supabase Infrastructure Analysis Report

## Executive Summary
PitchRank uses Supabase as its primary backend infrastructure for managing youth soccer rankings data. The application makes extensive use of pre-computed views, complex queries, and real-time subscriptions.

---

## 1. SUPABASE CONFIGURATION

### Client Setup
**File**: `/home/user/PitchRank/frontend/lib/supabaseClient.ts` (20 lines)

```typescript
- createClient() with NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY
- Fallback empty strings for build-time compatibility
- Runtime validation of environment variables
```

**Infrastructure Impact**:
- Single global Supabase client instance
- Uses anonymous key for all frontend operations
- Server-side operations use service role key via API routes

**Configuration Variables Required**:
```
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY
SUPABASE_SERVICE_KEY (for server-side operations)
```

---

## 2. DATABASE QUERIES - DETAILED ANALYSIS

### Primary Query Hub
**File**: `/home/user/PitchRank/frontend/lib/api.ts` (693 lines)

This is the main API layer with the following operations:

#### A. RANKINGS QUERIES (READ - MEDIUM COMPLEXITY)
**Lines**: 27-63

```typescript
api.getRankings(region?, ageGroup?, gender?)
- Source: rankings_view OR state_rankings_view (conditional)
- Filters: status='Active', age, gender, state (optional)
- Ordering: power_score_final DESC
- Performance: Moderate - filters applied, indexed columns
- Load Pattern: High (homepage, rankings pages, leaderboards)
- Cache: 5 min stale time, 30 min retention
```

**Query Complexity**: MEDIUM
- Conditional table selection based on region
- Multiple filters with indexed columns
- Single table read with ordering

**Infrastructure Impact**: 
- Executes frequently on homepage and rankings pages
- Uses indexed columns for fast filtering
- Should benefit from read replicas

---

#### B. TEAM DETAILS QUERY (READ - HIGH COMPLEXITY)
**Lines**: 70-201

```typescript
api.getTeam(id)
- Multiple sequential queries:
  1. teams table: SELECT * WHERE team_id_master = id (MEDIUM)
  2. rankings_view: SELECT specific fields WHERE team_id_master = id (MEDIUM)
  3. state_rankings_view: SELECT rank_in_state_final (LOW)
  4. games table: SELECT game details WHERE team involved (HIGH)
     - Uses OR condition: home_team_master_id OR away_team_master_id
     - Fetches ALL games for record calculation
  5. teams table (lookup): SELECT team_id_master, team_name, club_name 
     - Batch fetch with IN operator for enrichment
```

**Query Complexity**: HIGH
- 5 sequential database calls per team
- Heavy games table scan (all games for team)
- Client-side calculation of wins/losses/draws
- Fallback logic for missing ranking data

**Performance Concerns**:
- Games table query can be expensive for teams with many games
- No pagination on games fetch
- Client-side win/loss calculation instead of using DB
- Potential N+1 problem if called frequently

**Infrastructure Impact**:
- Very high cost when team page visited
- Large data transfer for teams with 100+ games
- Should cache aggressively (10 min stale, 60 min retention with useQuery)
- Consider pagination for games data

---

#### C. TEAM TRAJECTORY (READ - HIGH COMPLEXITY)
**Lines**: 210-276

```typescript
api.getTeamTrajectory(id, periodDays=30)
- Query: games table - SELECT * WHERE team involved
- Processing: Sort, group by period, calculate metrics
- Client-side calculation: Win%, goals for/against, avg goals
```

**Query Complexity**: HIGH
- Fetches ALL games for team (same cost as getTeam games query)
- Heavy client-side processing
- Calculation of trajectory metrics in JavaScript

**Performance Concerns**:
- Another expensive games table scan
- Duplicates getTeam games query
- Should be consolidated or cached

---

#### D. TEAM GAMES QUERY (READ - HIGH COMPLEXITY)
**Lines**: 284-358

```typescript
api.getTeamGames(id, limit=50)
- Games query: SELECT * WHERE team involved (HIGH)
  - Uses OR: home_team_master_id OR away_team_master_id
  - Limit: 50 (configurable)
  - Order: game_date DESC
- Teams enrichment: SELECT team_id_master, team_name, club_name
  - Batch fetch with IN operator
```

**Query Complexity**: HIGH
- OR condition on games table (potential full scan)
- Secondary teams table lookup
- Limited to 50 rows (good for pagination)

**Infrastructure Impact**:
- High query cost due to OR condition
- Should use composite index on (home_team_master_id, game_date) and (away_team_master_id, game_date)
- Consider pagination higher in UI

---

#### E. COMMON OPPONENTS QUERY (READ - VERY HIGH COMPLEXITY)
**Lines**: 366-474

```typescript
api.getCommonOpponents(team1Id, team2Id)
- Query 1: games for team1 - ALL games (HIGH)
- Query 2: games for team2 - ALL games (HIGH)
- Processing: In-memory Set operations to find common opponents
- Query 3: teams batch lookup for opponent names
```

**Query Complexity**: VERY HIGH
- 2 full game table scans
- In-memory set intersection computation
- Batch team name lookup
- Used for comparison page (likely lower traffic)

**Performance Concerns**:
- Extremely expensive operation
- 2 full scans of games table per comparison
- Should be cached aggressively
- Consider materialized view for frequent comparisons

---

#### F. TEAM RANKINGS BATCH (READ - MEDIUM COMPLEXITY)
**Lines**: 565-604

```typescript
api.getTeamRankings(teamIds[])
- Query: rankings_view WHERE team_id_master IN (teamIds)
- Batch operation with IN clause
```

**Query Complexity**: MEDIUM
- Single query with IN filter
- Indexed primary key lookup
- Good batch operation

**Infrastructure Impact**:
- Efficient batch operation
- Used for watchlist page (multiple teams)
- Should be fast with proper indexes

---

#### G. DATABASE STATS (READ - LOW COMPLEXITY)
**Lines**: 610-640

```typescript
api.getDbStats()
- Uses RPC function: get_db_stats()
- Alternative fallback: Direct count queries on games and rankings_full tables
- Cache: 5 min stale, 30 min retention (via React Query)
```

**Query Complexity**: LOW
- RPC function (optimized)
- Fallback to count queries with filters
- Executes on every homepage load

---

#### H. MATCH PREDICTION (READ - MEDIUM COMPLEXITY)
**Lines**: 507-558

```typescript
api.getMatchPrediction(teamAId, teamBId)
- getTeam(teamAId) - HIGH (see above)
- getTeam(teamBId) - HIGH (see above)
- Games query: SELECT limited fields WHERE game_date >= cutoff
  - Limit: 500 games
  - Date range: Last 60 days
  - Filter: home_score NOT NULL AND away_score NOT NULL
- Client-side ML model execution
```

**Query Complexity**: HIGH
- 2 expensive getTeam calls
- 500-game fetch for prediction model
- CPU-intensive client-side ML calculation

**Infrastructure Impact**:
- Moderate traffic (comparison page)
- 60-day lookback is reasonable
- Should cache results by team pair

---

### React Query Integration
**Files**: 
- `hooks/useRankings.ts`
- `hooks/useTeamSearch.ts`
- `hooks/useScrapeRequestNotifications.ts`

**Cache Settings**:
```typescript
useRankings:
  - staleTime: 5 minutes
  - gcTime: 30 minutes
  
useTeamSearch:
  - staleTime: 10 minutes
  - gcTime: 60 minutes
  - Pagination: Batches of 1000 teams (handles >1000 teams)
```

**Query Complexity**: MEDIUM
- `useTeamSearch` fetches ALL teams with pagination
- Multiple batch queries until exhausted
- Each batch up to 1000 rows

---

## 3. REAL-TIME SUBSCRIPTIONS

### Scrape Request Notifications
**File**: `/home/user/PitchRank/frontend/hooks/useScrapeRequestNotifications.ts` (115 lines)

**Subscription Pattern**:
```typescript
supabase
  .channel('scrape_requests_changes')
  .on('postgres_changes', {
    event: 'UPDATE',
    schema: 'public',
    table: 'scrape_requests',
    filter: 'status=eq.completed'
  }, callback)
  .subscribe()
```

**Infrastructure Impact**:
- **REAL-TIME ENABLED**: Supabase Realtime must be active
- **Channel**: Single persistent channel per browser session
- **Event Type**: UPDATE only
- **Filtering**: Server-side filter on status=completed
- **Client Filter**: Additional localStorage check
- **Subscription Lifecycle**: Connected on mount, cleaned up on unmount
- **Load Pattern**: Low - only tracks submitted requests from current session
- **Storage**: localStorage tracks request IDs per session

**Performance Considerations**:
- Efficient - only listens to completed updates
- Unsubscribes properly on unmount
- Should not cause significant load even with many users
- Row Level Security allows all reads

---

## 4. STORAGE USAGE

**Result**: NO Supabase Storage Buckets Used

The application does not use Supabase Storage for file uploads.

---

## 5. AUTHENTICATION & RLS

### Authentication Pattern
**Service Role Key Usage**:
- `/app/api/process-missing-games/route.ts`: Uses service key for database access
- `/app/api/scrape-missing-game/route.ts`: Uses service key for insert operations

**Client Authentication**:
- Anonymous key for public rankings queries
- All operations are read-only for anonymous users
- No user authentication/login system

### Row Level Security
**Status**: ENABLED

**RLS Policies**:
1. **scrape_requests table**:
   - INSERT: Allowed for all users
   - UPDATE: Only service role
   - SELECT: Allowed for all users

2. **games table**: READ-only for public
3. **teams table**: READ-only for public
4. **rankings_view**: READ-only for public
5. **state_rankings_view**: READ-only for public

---

## 6. RPC FUNCTIONS

### get_db_stats()
**File**: `/supabase/migrations/20251120000001_add_db_stats_function.sql`

```sql
RETURNS TABLE (total_games BIGINT, total_teams BIGINT)

IMPLEMENTATION:
- COUNT games WHERE home_team_master_id IS NOT NULL 
               AND away_team_master_id IS NOT NULL
               AND home_score IS NOT NULL
               AND away_score IS NOT NULL
- COUNT rankings_full WHERE power_score_final IS NOT NULL
```

**Query Complexity**: LOW
- Single aggregate operation
- Used as primary stats display on homepage

**Infrastructure Impact**:
- Efficient alternative to multiple queries
- Can be expensive if called frequently without caching
- Currently cached via React Query (5 min stale time)

---

## 7. EDGE FUNCTIONS

**Status**: NO Edge Functions configured

All backend processing (ranking calculation, scraping) is handled by Python scripts outside of Supabase Edge Functions.

---

## 8. DATABASE STRUCTURE & VIEWS

### Core Tables
1. **teams** (~2,800 rows)
   - Indexes: provider_lookup, name_lookup (GIN trigram), age_gender, state, master_id
   
2. **games** (~16,000+ rows)
   - Indexes: date DESC, home_team, away_team, provider, games_ml_overperformance
   - Heavy query target - composite indexes needed
   
3. **scrape_requests** (small, growing)
   - Indexes: status, pending (filtered)
   
4. **ranking_history** (daily snapshots)
   - Indexes: team_date, date, cohort, composite
   
5. **current_rankings** (cached)
6. **team_alias_map** (mapping)
7. **build_logs** (operational)

### Computed Views
1. **rankings_view** - National rankings
   - Source: rankings_full + teams
   - Fields: 16 columns
   - Performance: Pre-computed in rankings_full
   
2. **state_rankings_view** - State rankings
   - Source: rankings_view filtered
   - Computes: rank_in_state_final via window function
   
3. **team_predictive_view** - ML predictions
   - Source: rankings_full with ML fields
   
4. **rankings_full** - Master computed table
   - Pre-calculated ranks and scores
   - Includes ML adjustments

---

## 9. INFRASTRUCTURE LOAD ANALYSIS

### Query Frequency Estimate (by feature)

| Feature | Query Count | Frequency | Complexity | Impact |
|---------|------------|-----------|-----------|--------|
| Homepage stats | 1 (RPC) | Every visit | LOW | LOW |
| Rankings list | 1 | Every rankings page visit | MEDIUM | MEDIUM |
| Team page | 4-5 | Every team detail page | HIGH | HIGH |
| Team games | 1 | When games loaded | HIGH | MEDIUM |
| Team trajectory | 1 | When trajectory loaded | HIGH | MEDIUM |
| Watchlist | N+1 (batched) | Every watchlist load | MEDIUM | LOW-MEDIUM |
| Compare teams | 2+ | Compare page load | VERY HIGH | MEDIUM |
| Recent movers | 1 | Homepage load | MEDIUM | LOW |
| Scrape status | 1 (realtime) | Per notification | LOW | LOW |

### Potential Performance Bottlenecks

#### 1. GAMES TABLE SCANS (HIGH PRIORITY)
- **Issue**: `api.getTeam()` fetches ALL games for team
- **Impact**: Team pages with 100+ games become slow
- **Current**: No pagination, OR condition inefficient
- **Fix**: 
  - Add composite index on (home_team_master_id, game_date DESC)
  - Add composite index on (away_team_master_id, game_date DESC)
  - Implement pagination (fetch recent 50, load more on demand)
  - Consider materializing recent games in cached table

#### 2. COMMON OPPONENTS CALCULATION (MEDIUM PRIORITY)
- **Issue**: 2 full games table scans + in-memory processing
- **Impact**: Compare page could be slow with large game histories
- **Current**: Not cached between requests
- **Fix**:
  - Implement aggressive client-side caching (1 hour)
  - Consider materialized view if frequently used
  - Limit game history to last 60-90 days instead of all history

#### 3. TEAM TRAJECTORY DUPLICATION (MEDIUM PRIORITY)
- **Issue**: Duplicate games fetch from `getTeam()`
- **Impact**: Fetches same data twice when viewing team page with games and trajectory
- **Current**: No deduplication
- **Fix**:
  - Consolidate into single query
  - Cache trajectory separately

#### 4. BATCH TEAM SEARCH PAGINATION (LOW PRIORITY)
- **Issue**: `useTeamSearch` fetches 1000 teams at a time
- **Impact**: Initial load for GlobalSearch could be 1000+ rows
- **Current**: Decent pagination logic (stops when < 1000 returned)
- **Fix**:
  - Consider infinite scroll instead of loading all
  - Or implement server-side search with limit 100

#### 5. REALTIME SUBSCRIPTION SCALE (LOW PRIORITY)
- **Issue**: Currently 1 subscription per user session
- **Impact**: If many users submit scrape requests, many real-time connections
- **Current**: Efficient with filters
- **Fix**:
  - Monitor connection count
  - Consider broadcast channels instead for high scale

---

## 10. CACHE ANALYSIS

### Current Caching Strategy
```typescript
Rankings:
  - staleTime: 5 min (updates rarely, cached in DB)
  - gcTime: 30 min

Team Search:
  - staleTime: 10 min
  - gcTime: 60 min

Team Details:
  - staleTime: 10 min (via useQuery in watchlist)
  - gcTime: 60 min
```

### Recommended Improvements
- Increase staleTime to 30 min for rankings (update weekly)
- Add aggressive caching for compare operations (1 hour)
- Cache RPC results separately (5 min is good)
- Consider service worker for offline support

---

## 11. SUMMARY: INFRASTRUCTURE REQUIREMENTS

### Current Load Estimate
- **Database Size**: 2,800+ teams, 16,000+ games, growing
- **Query Frequency**: 50-200 queries/second at peak
- **Storage**: ~100 MB - 1 GB range
- **Connections**: 10-50 concurrent users
- **Realtime Connections**: Handful (low demand)

### Recommendations by Priority

**CRITICAL**:
1. Index composite keys on games table (home/away team + date)
2. Implement pagination for games data
3. Add query result caching for expensive operations

**HIGH**:
1. Monitor slow query logs for bottlenecks
2. Enable query performance insights
3. Set up alerting for realtime connection spikes
4. Consider read replicas if query load increases >200 QPS

**MEDIUM**:
1. Consolidate duplicate game queries
2. Implement server-side pagination for team search
3. Cache comparison results (1 hour TTL)

**LOW**:
1. Optimize RPC function with result set pagination
2. Consider materialized views for rankings_full
3. Archive old ranking_history snapshots (>90 days)

---

## 12. KEY METRICS FOR MONITORING

```
1. Query Performance:
   - Avg query time by operation
   - P95 query time (especially games queries)
   - Slow query count

2. Database Load:
   - Active connection count
   - Query queue depth
   - Transaction rate

3. Realtime Subscriptions:
   - Active subscription count
   - Message throughput
   - Error rate

4. Storage:
   - Disk usage trend
   - Games table row count
   - Ranking table row count

5. Application:
   - API endpoint response times
   - Page load times (team page)
   - Cache hit rate
```

---


---

## APPENDIX: FILE INVENTORY & SUPABASE USAGE

### Frontend Files Using Supabase

| File Path | Lines | Type | Usage | Risk Level |
|-----------|-------|------|-------|-----------|
| `/frontend/lib/supabaseClient.ts` | 20 | Config | Client initialization | LOW |
| `/frontend/lib/api.ts` | 693 | API Layer | 8 major query functions | HIGH |
| `/frontend/hooks/useRankings.ts` | 94 | Hook | Rankings query with React Query | MEDIUM |
| `/frontend/hooks/useTeamSearch.ts` | 84 | Hook | Pagination query (1000 batch) | MEDIUM |
| `/frontend/hooks/useScrapeRequestNotifications.ts` | 115 | Hook | Realtime subscription | LOW |
| `/frontend/components/HomeStats.tsx` | 112 | Component | RPC + fallback queries | LOW |
| `/frontend/app/page.tsx` | 100+ | Page | Prefetch rankings on server | MEDIUM |
| `/frontend/app/watchlist/page.tsx` | 200+ | Page | useQueries for multiple teams | MEDIUM |
| `/frontend/app/teams/[id]/page.tsx` | 99 | Page | Team existence check + metadata | MEDIUM |
| `/frontend/app/api/process-missing-games/route.ts` | 102 | API Route | Service key query | LOW |
| `/frontend/app/api/scrape-missing-game/route.ts` | 123 | API Route | Service key insert | LOW |
| `/frontend/components/HomeLeaderboard.tsx` | 80+ | Component | useRankings hook | MEDIUM |
| `/frontend/components/RecentMovers.tsx` | 80+ | Component | useRankings hook + calculations | MEDIUM |
| `/tests/integration/verify_rankings_views.test.ts` | 313 | Test | View schema validation | LOW |

### Database Configuration Files

| File Path | Purpose | Impact |
|-----------|---------|--------|
| `/supabase/config.toml` | Supabase local/remote config | Configuration |
| `/supabase/migrations/` | 37 migration files | Schema evolution |
| `/frontend/lib/types.ts` | TypeScript interfaces | Data contracts |

### Migration Files Summary

**Early Schema (2024)**: 
- `20240101`: Initial schema (teams, games, rankings)
- `20240102`: Safety features
- `20240201`: Indexes, corrections, match review

**RLS & Security (Feb 2024)**:
- `20240215`: Row Level Security implementation

**Ranking System Evolution (Nov 2024-Jan 2025)**:
- `20241106`: View fixes, deprecations
- `20241108`: Index cleanup
- `20250120`: SOS handling, rankings_full creation
- `20250122`: Rank aliases
- `20250123`: Predictive fields, age conversion

**Recent Enhancements (Nov 2025)**:
- `20251113`: New scrape_requests table
- `20251117`: ML overperformance field
- `20251119`: Performance indexes
- `20251120`: Rankings views, db_stats function
- `20251121`: Total games in views
- `20251122`: Rank changes for recent movers
- `20251123`: Ranking history table
- `20251124`: Nullable rank_in_cohort
- `20251125`: Batch update ML performance

---

## KEY QUERY PATTERNS IDENTIFIED

### Pattern 1: Multi-Step Team Details
```typescript
// 5 sequential queries per team page load
1. SELECT * FROM teams WHERE id
2. SELECT fields FROM rankings_view WHERE id
3. SELECT rank FROM state_rankings_view WHERE id
4. SELECT * FROM games WHERE team involved (ALL)
5. SELECT names FROM teams WHERE id IN (list)
```
**Risk**: HIGH - Games table scan can be expensive

### Pattern 2: React Query Caching with Stale Time
```typescript
useQuery({
  queryKey: ['entity', params],
  queryFn: async () => { /* call api */ },
  staleTime: 5 * 60 * 1000,
  gcTime: 30 * 60 * 1000
})
```
**Risk**: MEDIUM - Stale times vary per feature

### Pattern 3: Realtime Updates
```typescript
supabase.channel('events').on('postgres_changes', {...}).subscribe()
```
**Risk**: LOW - Only listens to specific updates

### Pattern 4: Batch Operations
```typescript
// Pagination for team search
.range(offset, offset + BATCH_SIZE - 1)

// Batch team lookups
.in('team_id_master', [ids])
```
**Risk**: LOW - Efficient batch patterns

### Pattern 5: Computed Views
```typescript
// All ranking queries use pre-computed views
.from('rankings_view')
.from('state_rankings_view')
.from('rankings_full')
```
**Risk**: MEDIUM - View performance depends on underlying table

---

## COMPLEXITY SCORING BY QUERY

```
Scoring: 1-5 (1=trivial, 5=critical bottleneck)

api.getRankings() ...................... 2 (MEDIUM)
api.getTeam() ........................... 4 (HIGH)
api.getTeamTrajectory() ................. 4 (HIGH)
api.getTeamGames() ...................... 4 (HIGH)
api.getCommonOpponents() ............... 5 (VERY HIGH)
api.getTeamRankings() ................... 2 (MEDIUM)
api.getDbStats() ........................ 1 (LOW)
api.getPredictive() ..................... 2 (MEDIUM)
api.getMatchPrediction() ................ 4 (HIGH)
useTeamSearch() ......................... 3 (MEDIUM)
useRankings() ........................... 2 (MEDIUM)
useScrapeRequestNotifications() ......... 1 (LOW)
```

---

## PRODUCTION DEPLOYMENT CHECKLIST

- [ ] Enable RLS on all tables
- [ ] Configure read replicas for high-traffic queries
- [ ] Set up connection pooling (recommended: transaction mode)
- [ ] Create composite indexes on (home_team_master_id, game_date) and (away_team_master_id, game_date)
- [ ] Enable query performance monitoring
- [ ] Set up slow query alerts (>500ms)
- [ ] Implement backup policy (daily)
- [ ] Configure WAL archival for point-in-time recovery
- [ ] Enable Realtime only on required tables
- [ ] Test failover and recovery procedures
- [ ] Document all RPC functions and their performance characteristics
- [ ] Set up alerting for:
  - Database size growth
  - Realtime connection spikes
  - Query queue depth
  - Slow query count

---

## ESTIMATED RESOURCE ALLOCATION

Based on analysis:

**Storage**: 
- Teams: ~3 MB (2,800 rows)
- Games: ~50 MB (16,000+ rows, ~3KB/row)
- Ranking tables: ~10 MB
- History/logs: ~20 MB
- **Total**: ~100-150 MB at current scale

**Compute**:
- Peak QPS: 50-200 (estimated)
- Avg query: 10-50ms
- Realtime subscribers: <10 concurrent
- Max connections: 50-100

**Recommendations**:
- Start with Supabase Pro plan ($25/month)
- Monitor growth, upgrade if QPS exceeds 200/sec
- Consider database replication if read traffic >300 QPS
- Archive ranking_history monthly (retention policy)

---

## CONCLUSION

PitchRank has a well-structured Supabase implementation with:

**Strengths**:
- Good use of views and precomputation
- Proper RLS policies in place
- Realtime subscriptions are efficient
- React Query caching reduces load
- Clear separation of API layer

**Weaknesses**:
- Games table queries lack composite indexes
- No pagination on large result sets
- Duplicate queries in some code paths
- Some stale times may be too aggressive

**Action Items** (Priority Order):
1. Add composite indexes for games table (1 hour)
2. Implement games pagination (4 hours)
3. Set up query monitoring (2 hours)
4. Consolidate duplicate queries (8 hours)
5. Increase caching TTL for stable data (2 hours)

