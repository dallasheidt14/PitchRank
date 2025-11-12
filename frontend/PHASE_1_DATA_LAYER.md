# Phase 1: Data Layer Integration ✅

This document summarizes the data layer integration completed for PitchRank frontend.

## Overview

Phase 1 establishes a robust, typed data layer connecting the frontend to Supabase tables using React Query for caching, error handling, and data synchronization.

## Files Created/Updated

### `/lib/types.ts` (NEW)
TypeScript interfaces matching the Supabase database schema:
- `Team` - Team master data
- `Game` - Game records
- `Ranking` - Ranking data from current_rankings table
- `RankingWithTeam` - Ranking data with team details (from rankings_by_age_gender view)
- `TeamTrajectory` - Performance metrics over time periods
- `GameWithTeams` - Games with enriched team names

### `/lib/api.ts` (UPDATED)
Typed API functions for Supabase queries:

1. **`getRankings(region?, ageGroup?, gender?)`**
   - Fetches rankings from `rankings_by_age_gender` view
   - Supports filtering by state code (region), age group, and gender
   - Returns `RankingWithTeam[]`

2. **`getTeam(id)`**
   - Fetches a single team by `team_id_master` UUID
   - Returns `Team`

3. **`getTeamTrajectory(id, periodDays?)`**
   - Calculates team performance over time periods
   - Aggregates games into configurable time windows (default: 30 days)
   - Returns `TeamTrajectory[]` with metrics per period

4. **`getTeamGames(id, limit?)`**
   - Fetches games for a specific team
   - Enriches games with team names for display
   - Returns `GameWithTeams[]`

### `/lib/hooks.ts` (UPDATED)
React Query hooks with optimized caching:

1. **`useRankings(region?, ageGroup?, gender?)`**
   - Stale time: 5 minutes (rankings update weekly)
   - Cache time: 30 minutes

2. **`useTeam(id)`**
   - Stale time: 10 minutes
   - Cache time: 1 hour
   - Only runs if `id` is provided

3. **`useTeamTrajectory(id, periodDays?)`**
   - Stale time: 5 minutes
   - Cache time: 30 minutes

4. **`useTeamGames(id, limit?)`**
   - Stale time: 2 minutes (games update more frequently)
   - Cache time: 15 minutes

5. **`usePrefetchTeam()`**
   - Helper hook for prefetching team data
   - Useful for prefetching on hover

### `/lib/supabaseClient.ts` (UPDATED)
- Updated to handle missing environment variables gracefully
- Allows build to succeed without env vars (errors at runtime)

### `/app/test/page.tsx` (NEW)
Test page demonstrating data fetching:
- Fetches rankings using `useRankings()` hook
- Displays team names, rankings, and scores
- Shows loading states, error handling, and empty states
- Includes debug information
- Accessible at `/test` route

## Database Schema Mapping

### Tables Used:
- `teams` - Master team list
- `games` - Game history
- `current_rankings` - Current ranking data

### Views Used:
- `rankings_by_age_gender` - Rankings joined with team details

### Key Columns:
- Teams identified by `team_id_master` (UUID)
- Games reference teams via `home_team_master_id` and `away_team_master_id`
- Rankings linked via `team_id` → `teams.team_id_master`

## Caching Strategy

React Query caching is configured per data type:

| Data Type | Stale Time | Cache Time | Rationale |
|-----------|------------|------------|------------|
| Rankings | 5 min | 30 min | Updates weekly, relatively static |
| Team Details | 10 min | 1 hour | Changes infrequently |
| Team Games | 2 min | 15 min | Updates more frequently |
| Team Trajectory | 5 min | 30 min | Calculated from games |

## Error Handling

All API functions include:
- Try-catch error handling
- Console error logging for debugging
- Proper error propagation to React Query

React Query provides:
- `isError` flag for error state detection
- `error` object with error details
- Automatic retry logic (default: 3 retries)

## Type Safety

- All API functions are fully typed with TypeScript
- Interfaces match Supabase schema exactly
- Type inference works throughout the data layer
- No `any` types used

## Testing

### Test Page: `/test`

The test page demonstrates:
1. ✅ Data fetching from Supabase
2. ✅ Loading states with skeletons
3. ✅ Error handling and display
4. ✅ Empty state handling
5. ✅ Data display (team names, rankings, scores)

### To Test:

1. **Set up environment variables** (create `.env.local`):
   ```env
   NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
   NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
   ```

2. **Start dev server**:
   ```bash
   npm run dev
   ```

3. **Navigate to** `http://localhost:3000/test`

4. **Verify**:
   - Data loads without errors
   - Team names display correctly
   - Rankings show proper values
   - No CORS errors in console
   - No undefined values

## Prefetching Patterns

### Example: Prefetch on Hover

```typescript
import { usePrefetchTeam } from '@/lib/hooks';

function TeamLink({ teamId }: { teamId: string }) {
  const prefetchTeam = usePrefetchTeam();
  
  return (
    <Link
      href={`/teams/${teamId}`}
      onMouseEnter={() => prefetchTeam(teamId)}
    >
      Team Name
    </Link>
  );
}
```

### Example: Prefetch in Parent Component

```typescript
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

function ParentComponent() {
  const queryClient = useQueryClient();
  
  useEffect(() => {
    // Prefetch rankings when component mounts
    queryClient.prefetchQuery({
      queryKey: ['rankings'],
      queryFn: () => api.getRankings(),
    });
  }, [queryClient]);
}
```

## Next Steps (Phase 2)

With the data layer complete, Phase 2 will focus on:
- UI layout and components
- Ranking tables and filters
- Team detail pages
- Game history displays
- Charts and visualizations using recharts

## Notes

- All queries respect Supabase RLS (Row Level Security) policies
- The `rankings_by_age_gender` view uses `security_invoker = true` to respect RLS
- Environment variables are validated at runtime, not build time
- The test page uses `dynamic = 'force-dynamic'` to prevent build-time errors

---

**Status:** Phase 1 Complete ✅  
**Date:** Data layer integration completed  
**Next:** Ready for Phase 2 UI development





