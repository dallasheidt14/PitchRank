# Team Merge Feature Implementation Plan

## Option 1 (Redirect Merge) + Option 8 (Intelligent Suggestions)

This document provides a comprehensive, phased implementation plan for the team merge feature with all identified safety measures incorporated.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MERGE RESOLUTION FLOW                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐     ┌──────────────────┐     ┌────────────────┐  │
│  │    games     │     │  team_merge_map  │     │     teams      │  │
│  │              │     │                  │     │                │  │
│  │ home_team_id─┼────►│ deprecated_id    │     │ team_id_master │  │
│  │ away_team_id │     │ canonical_id ────┼────►│ is_deprecated  │  │
│  └──────────────┘     └──────────────────┘     └────────────────┘  │
│         │                      │                       │           │
│         ▼                      ▼                       ▼           │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              COALESCE(mm.canonical_id, g.team_id)           │   │
│  │                    = Resolved Team ID                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## PHASE 1: Database Foundation

### 1.1 Add Deprecation Flag to Teams Table

**File:** `supabase/migrations/YYYYMMDD000001_add_team_deprecation.sql`

```sql
-- Add soft deprecation column (never delete teams!)
ALTER TABLE teams
ADD COLUMN IF NOT EXISTS is_deprecated BOOLEAN DEFAULT FALSE;

-- Add index for filtering active teams
CREATE INDEX IF NOT EXISTS idx_teams_active
ON teams(team_id_master)
WHERE is_deprecated = FALSE;

-- Update existing views to exclude deprecated teams by default
COMMENT ON COLUMN teams.is_deprecated IS
  'Soft deletion flag. Deprecated teams are excluded from rankings but preserved for historical integrity.';
```

### 1.2 Create Team Merge Map Table

**File:** `supabase/migrations/YYYYMMDD000002_create_team_merge_map.sql`

```sql
-- Core merge redirect table
CREATE TABLE IF NOT EXISTS team_merge_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deprecated_team_id UUID NOT NULL UNIQUE REFERENCES teams(team_id_master),
    canonical_team_id UUID NOT NULL REFERENCES teams(team_id_master),
    merged_at TIMESTAMPTZ DEFAULT NOW(),
    merged_by TEXT NOT NULL,
    merge_reason TEXT,
    confidence_score FLOAT,  -- From Option 8 suggestions
    suggestion_signals JSONB, -- Store the signals that led to this merge

    -- Prevent self-merge
    CONSTRAINT no_self_merge CHECK (deprecated_team_id != canonical_team_id)
);

-- Index for fast lookups
CREATE INDEX idx_merge_map_deprecated ON team_merge_map(deprecated_team_id);
CREATE INDEX idx_merge_map_canonical ON team_merge_map(canonical_team_id);

-- Prevent merge chains (A→B→C) and circular merges
CREATE OR REPLACE FUNCTION prevent_merge_chains()
RETURNS TRIGGER AS $$
BEGIN
    -- Cannot merge into a team that is itself deprecated/merged
    IF EXISTS (
        SELECT 1 FROM team_merge_map
        WHERE deprecated_team_id = NEW.canonical_team_id
    ) THEN
        RAISE EXCEPTION 'Cannot merge into team % - it is already merged into another team (would create chain)',
            NEW.canonical_team_id;
    END IF;

    -- Cannot deprecate a team that is the canonical target of other merges
    IF EXISTS (
        SELECT 1 FROM team_merge_map
        WHERE canonical_team_id = NEW.deprecated_team_id
    ) THEN
        RAISE EXCEPTION 'Cannot deprecate team % - other teams are already merged into it. Merge those first.',
            NEW.deprecated_team_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER check_merge_chains
    BEFORE INSERT OR UPDATE ON team_merge_map
    FOR EACH ROW
    EXECUTE FUNCTION prevent_merge_chains();
```

### 1.3 Create Merge Audit Table

**File:** `supabase/migrations/YYYYMMDD000003_create_team_merge_audit.sql`

```sql
-- Comprehensive audit trail for merge operations
CREATE TABLE IF NOT EXISTS team_merge_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merge_id UUID REFERENCES team_merge_map(id),
    deprecated_team_id UUID NOT NULL,
    canonical_team_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('merge', 'unmerge', 'cascade_alias')),

    -- Snapshot of state before merge
    deprecated_team_snapshot JSONB,  -- Full team record before deprecation
    games_affected INTEGER,
    aliases_updated INTEGER,
    rankings_recalculated BOOLEAN DEFAULT FALSE,

    -- Who and when
    performed_by TEXT NOT NULL,
    performed_at TIMESTAMPTZ DEFAULT NOW(),

    -- For reversibility
    reverted_at TIMESTAMPTZ,
    reverted_by TEXT,
    revert_reason TEXT
);

CREATE INDEX idx_merge_audit_deprecated ON team_merge_audit(deprecated_team_id);
CREATE INDEX idx_merge_audit_canonical ON team_merge_audit(canonical_team_id);
CREATE INDEX idx_merge_audit_date ON team_merge_audit(performed_at DESC);
```

### 1.4 Create Merge Resolution Function

**File:** `supabase/migrations/YYYYMMDD000004_merge_resolution_functions.sql`

```sql
-- Resolve a single team_id to its canonical form
CREATE OR REPLACE FUNCTION resolve_team_id(team_id UUID)
RETURNS UUID AS $$
DECLARE
    resolved_id UUID;
BEGIN
    SELECT COALESCE(mm.canonical_team_id, team_id)
    INTO resolved_id
    FROM (SELECT team_id AS tid) t
    LEFT JOIN team_merge_map mm ON t.tid = mm.deprecated_team_id;

    RETURN COALESCE(resolved_id, team_id);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Execute a merge operation with full safety checks
CREATE OR REPLACE FUNCTION execute_team_merge(
    p_deprecated_team_id UUID,
    p_canonical_team_id UUID,
    p_merged_by TEXT,
    p_merge_reason TEXT DEFAULT NULL,
    p_confidence_score FLOAT DEFAULT NULL,
    p_suggestion_signals JSONB DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    v_merge_id UUID;
    v_deprecated_snapshot JSONB;
    v_aliases_updated INTEGER;
    v_games_affected INTEGER;
BEGIN
    -- 1. Validate teams exist and are not already deprecated
    IF NOT EXISTS (SELECT 1 FROM teams WHERE team_id_master = p_deprecated_team_id) THEN
        RAISE EXCEPTION 'Deprecated team % does not exist', p_deprecated_team_id;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM teams WHERE team_id_master = p_canonical_team_id) THEN
        RAISE EXCEPTION 'Canonical team % does not exist', p_canonical_team_id;
    END IF;

    IF EXISTS (SELECT 1 FROM teams WHERE team_id_master = p_deprecated_team_id AND is_deprecated = TRUE) THEN
        RAISE EXCEPTION 'Team % is already deprecated', p_deprecated_team_id;
    END IF;

    -- 2. Snapshot the deprecated team before changes
    SELECT to_jsonb(t.*) INTO v_deprecated_snapshot
    FROM teams t WHERE team_id_master = p_deprecated_team_id;

    -- 3. Count affected games (for audit)
    SELECT COUNT(*) INTO v_games_affected
    FROM games
    WHERE home_team_master_id = p_deprecated_team_id
       OR away_team_master_id = p_deprecated_team_id;

    -- 4. Create merge map entry (triggers chain prevention)
    INSERT INTO team_merge_map (
        deprecated_team_id, canonical_team_id, merged_by,
        merge_reason, confidence_score, suggestion_signals
    )
    VALUES (
        p_deprecated_team_id, p_canonical_team_id, p_merged_by,
        p_merge_reason, p_confidence_score, p_suggestion_signals
    )
    RETURNING id INTO v_merge_id;

    -- 5. Cascade update team_alias_map
    UPDATE team_alias_map
    SET team_id_master = p_canonical_team_id
    WHERE team_id_master = p_deprecated_team_id;

    GET DIAGNOSTICS v_aliases_updated = ROW_COUNT;

    -- 6. Mark deprecated team
    UPDATE teams
    SET is_deprecated = TRUE, updated_at = NOW()
    WHERE team_id_master = p_deprecated_team_id;

    -- 7. Create audit record
    INSERT INTO team_merge_audit (
        merge_id, deprecated_team_id, canonical_team_id, action,
        deprecated_team_snapshot, games_affected, aliases_updated,
        performed_by
    )
    VALUES (
        v_merge_id, p_deprecated_team_id, p_canonical_team_id, 'merge',
        v_deprecated_snapshot, v_games_affected, v_aliases_updated,
        p_merged_by
    );

    -- 8. Return summary
    RETURN jsonb_build_object(
        'success', TRUE,
        'merge_id', v_merge_id,
        'deprecated_team_id', p_deprecated_team_id,
        'canonical_team_id', p_canonical_team_id,
        'games_affected', v_games_affected,
        'aliases_updated', v_aliases_updated
    );

EXCEPTION WHEN OTHERS THEN
    RETURN jsonb_build_object(
        'success', FALSE,
        'error', SQLERRM
    );
END;
$$ LANGUAGE plpgsql;

-- Revert a merge operation
CREATE OR REPLACE FUNCTION revert_team_merge(
    p_merge_id UUID,
    p_reverted_by TEXT,
    p_revert_reason TEXT
)
RETURNS JSONB AS $$
DECLARE
    v_deprecated_team_id UUID;
    v_canonical_team_id UUID;
    v_aliases_reverted INTEGER;
BEGIN
    -- Get merge details
    SELECT deprecated_team_id, canonical_team_id
    INTO v_deprecated_team_id, v_canonical_team_id
    FROM team_merge_map WHERE id = p_merge_id;

    IF v_deprecated_team_id IS NULL THEN
        RAISE EXCEPTION 'Merge % not found', p_merge_id;
    END IF;

    -- 1. Revert alias mappings
    UPDATE team_alias_map
    SET team_id_master = v_deprecated_team_id
    WHERE team_id_master = v_canonical_team_id
      AND provider_team_id IN (
          -- Only revert aliases that were originally for this team
          SELECT DISTINCT home_provider_id FROM games WHERE home_team_master_id = v_deprecated_team_id
          UNION
          SELECT DISTINCT away_provider_id FROM games WHERE away_team_master_id = v_deprecated_team_id
      );

    GET DIAGNOSTICS v_aliases_reverted = ROW_COUNT;

    -- 2. Un-deprecate the team
    UPDATE teams
    SET is_deprecated = FALSE, updated_at = NOW()
    WHERE team_id_master = v_deprecated_team_id;

    -- 3. Remove merge map entry
    DELETE FROM team_merge_map WHERE id = p_merge_id;

    -- 4. Update audit record
    UPDATE team_merge_audit
    SET reverted_at = NOW(), reverted_by = p_reverted_by, revert_reason = p_revert_reason
    WHERE merge_id = p_merge_id;

    RETURN jsonb_build_object(
        'success', TRUE,
        'deprecated_team_id', v_deprecated_team_id,
        'canonical_team_id', v_canonical_team_id,
        'aliases_reverted', v_aliases_reverted
    );

EXCEPTION WHEN OTHERS THEN
    RETURN jsonb_build_object(
        'success', FALSE,
        'error', SQLERRM
    );
END;
$$ LANGUAGE plpgsql;
```

### 1.5 Update Rankings Views with Merge Resolution

**File:** `supabase/migrations/YYYYMMDD000005_update_views_merge_resolution.sql`

```sql
-- Update rankings_view to resolve merged teams
CREATE OR REPLACE VIEW rankings_view AS
SELECT
    COALESCE(mm.canonical_team_id, t.team_id_master) as team_id_master,
    t.team_name,
    t.club_name,
    t.age_group,
    t.gender,
    t.state_code,
    r.national_rank,
    r.state_rank,
    r.power_score_final,
    r.powerscore_ml,
    r.games_played,
    r.wins,
    r.losses,
    r.draws,
    r.sos_norm,
    r.off_norm,
    r.def_norm,
    r.status,
    r.last_game_date,
    r.rank_change_7d,
    r.rank_change_30d
FROM rankings_full r
JOIN teams t ON r.team_id = t.team_id_master
LEFT JOIN team_merge_map mm ON t.team_id_master = mm.deprecated_team_id
WHERE t.is_deprecated = FALSE OR mm.canonical_team_id IS NOT NULL;

-- Similarly update state_rankings_view
CREATE OR REPLACE VIEW state_rankings_view AS
SELECT
    COALESCE(mm.canonical_team_id, t.team_id_master) as team_id_master,
    t.team_name,
    t.club_name,
    t.age_group,
    t.gender,
    t.state_code,
    r.national_rank,
    r.state_rank,
    r.power_score_final,
    r.powerscore_ml,
    r.games_played,
    r.wins,
    r.losses,
    r.draws,
    r.sos_norm,
    r.sos_norm_state,
    r.off_norm,
    r.def_norm,
    r.status,
    r.last_game_date,
    r.rank_change_7d,
    r.rank_change_30d
FROM rankings_full r
JOIN teams t ON r.team_id = t.team_id_master
LEFT JOIN team_merge_map mm ON t.team_id_master = mm.deprecated_team_id
WHERE t.is_deprecated = FALSE OR mm.canonical_team_id IS NOT NULL;
```

---

## PHASE 2: Backend Merge Resolution

### 2.1 Create Merge Resolution Utility

**File:** `src/utils/merge_resolver.py`

```python
"""
Team merge resolution utilities.
Resolves deprecated team IDs to their canonical form.
"""
from typing import Dict, Optional, Set
import pandas as pd
from supabase import Client

class MergeResolver:
    """Resolves deprecated team IDs to canonical team IDs."""

    def __init__(self, supabase_client: Client):
        self.client = supabase_client
        self._merge_map: Dict[str, str] = {}
        self._version: Optional[str] = None

    def load_merge_map(self) -> None:
        """Load current merge mappings from database."""
        response = self.client.table('team_merge_map').select(
            'deprecated_team_id, canonical_team_id'
        ).execute()

        self._merge_map = {
            str(row['deprecated_team_id']): str(row['canonical_team_id'])
            for row in response.data
        }

        # Version hash for cache invalidation
        import hashlib
        map_str = ''.join(sorted(f"{k}:{v}" for k, v in self._merge_map.items()))
        self._version = hashlib.md5(map_str.encode()).hexdigest()[:8]

    def resolve(self, team_id: str) -> str:
        """Resolve a single team ID to its canonical form."""
        return self._merge_map.get(str(team_id), str(team_id))

    def resolve_series(self, series: pd.Series) -> pd.Series:
        """Resolve a pandas Series of team IDs."""
        return series.astype(str).map(lambda x: self._merge_map.get(x, x))

    def resolve_dataframe(self, df: pd.DataFrame, columns: list) -> pd.DataFrame:
        """Resolve multiple team ID columns in a DataFrame."""
        df = df.copy()
        for col in columns:
            if col in df.columns:
                df[col] = self.resolve_series(df[col])
        return df

    @property
    def version(self) -> str:
        """Get version hash for cache key inclusion."""
        if self._version is None:
            self.load_merge_map()
        return self._version

    @property
    def has_merges(self) -> bool:
        """Check if any merges exist."""
        return len(self._merge_map) > 0

    def get_deprecated_teams(self) -> Set[str]:
        """Get set of all deprecated team IDs."""
        return set(self._merge_map.keys())

    def get_canonical_teams(self) -> Set[str]:
        """Get set of all canonical team IDs."""
        return set(self._merge_map.values())
```

### 2.2 Update Data Adapter

**File:** `src/rankings/data_adapter.py` (modifications)

```python
# Add import at top
from src.utils.merge_resolver import MergeResolver

async def fetch_games_for_rankings(
    supabase_client: Client,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
    merge_resolver: Optional[MergeResolver] = None,  # NEW PARAMETER
) -> pd.DataFrame:
    """
    Fetch games for ranking calculation with merge resolution.

    Args:
        supabase_client: Supabase client
        lookback_days: Days of history to include
        provider_filter: Optional provider filter
        merge_resolver: Optional MergeResolver instance for team ID resolution
    """
    # ... existing fetch logic ...

    games_df = pd.DataFrame(all_games)

    # Apply merge resolution if resolver provided
    if merge_resolver is not None and merge_resolver.has_merges:
        games_df = merge_resolver.resolve_dataframe(
            games_df,
            columns=['home_team_master_id', 'away_team_master_id']
        )
        logger.info(f"Applied merge resolution (version: {merge_resolver.version})")

    return games_df
```

### 2.3 Update Calculator Cache Key

**File:** `src/rankings/calculator.py` (modifications)

```python
# In compute_rankings_with_ml function, modify cache key generation:

async def compute_rankings_with_ml(
    games_df: pd.DataFrame,
    supabase_client: Client,
    lookback_days: int = 365,
    force_rebuild: bool = False,
    provider_filter: Optional[str] = None,
    merge_version: Optional[str] = None,  # NEW PARAMETER
) -> Dict[str, pd.DataFrame]:
    """
    Compute rankings with ML adjustment.

    Args:
        merge_version: Version hash from MergeResolver for cache invalidation
    """
    # Modified cache key to include merge version
    game_ids = games_df["id"].astype(str).tolist() if "id" in games_df.columns else []
    hash_input = "".join(sorted(game_ids)) + str(lookback_days) + (provider_filter or "")

    # Include merge version in cache key
    if merge_version:
        hash_input += f"_merge_{merge_version}"

    cache_key = hashlib.md5(hash_input.encode()).hexdigest()

    # ... rest of function ...
```

### 2.4 Update Main Ranking Script

**File:** `scripts/calculate_rankings.py` (modifications)

```python
# Add merge resolution before ranking calculation

from src.utils.merge_resolver import MergeResolver

async def main():
    # ... existing setup ...

    # Initialize merge resolver
    merge_resolver = MergeResolver(supabase_client)
    merge_resolver.load_merge_map()

    if merge_resolver.has_merges:
        logger.info(f"Loaded {len(merge_resolver.get_deprecated_teams())} team merges")

    # Fetch games with merge resolution
    games_df = await fetch_games_for_rankings(
        supabase_client,
        lookback_days=lookback_days,
        provider_filter=provider_filter,
        merge_resolver=merge_resolver,  # Pass resolver
    )

    # Compute rankings with merge version for cache
    results = await compute_rankings_with_ml(
        games_df=games_df,
        supabase_client=supabase_client,
        lookback_days=lookback_days,
        force_rebuild=force_rebuild,
        provider_filter=provider_filter,
        merge_version=merge_resolver.version,  # Include for cache key
    )

    # ... rest of function ...
```

---

## PHASE 3: Frontend Updates

### 3.1 Add Merge Resolution Hook

**File:** `frontend/lib/mergeResolver.ts`

```typescript
import { createClient } from '@supabase/supabase-js';

interface MergeMap {
  [deprecatedId: string]: string;
}

let mergeMap: MergeMap | null = null;
let mergeMapPromise: Promise<MergeMap> | null = null;

export async function loadMergeMap(): Promise<MergeMap> {
  if (mergeMap) return mergeMap;

  if (mergeMapPromise) return mergeMapPromise;

  mergeMapPromise = (async () => {
    const supabase = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
    );

    const { data, error } = await supabase
      .from('team_merge_map')
      .select('deprecated_team_id, canonical_team_id');

    if (error) {
      console.error('Failed to load merge map:', error);
      return {};
    }

    mergeMap = {};
    for (const row of data || []) {
      mergeMap[row.deprecated_team_id] = row.canonical_team_id;
    }

    return mergeMap;
  })();

  return mergeMapPromise;
}

export function resolveTeamId(teamId: string, map: MergeMap): string {
  return map[teamId] || teamId;
}

export function invalidateMergeMap(): void {
  mergeMap = null;
  mergeMapPromise = null;
}
```

### 3.2 Update Team Page with Redirect

**File:** `frontend/app/teams/[id]/page.tsx` (modifications)

```typescript
import { loadMergeMap, resolveTeamId } from '@/lib/mergeResolver';
import { redirect } from 'next/navigation';

export default async function TeamPage({ params }: { params: { id: string } }) {
  const resolvedParams = await params;
  const teamId = resolvedParams.id;

  // Check if this is a deprecated team that should redirect
  const mergeMap = await loadMergeMap();
  const canonicalId = resolveTeamId(teamId, mergeMap);

  if (canonicalId !== teamId) {
    // Redirect to canonical team page
    redirect(`/teams/${canonicalId}`);
  }

  // ... rest of existing page logic ...
}
```

### 3.3 Update Watchlist to Handle Merges

**File:** `frontend/lib/watchlist.ts` (modifications)

```typescript
import { loadMergeMap, resolveTeamId } from './mergeResolver';

export async function getWatchedTeamsResolved(): Promise<string[]> {
  const watchedIds = getWatchedTeams();
  const mergeMap = await loadMergeMap();

  // Resolve all team IDs and deduplicate
  const resolvedIds = new Set<string>();
  for (const id of watchedIds) {
    resolvedIds.add(resolveTeamId(id, mergeMap));
  }

  // If any IDs were resolved, update localStorage
  const resolvedArray = Array.from(resolvedIds);
  if (resolvedArray.length !== watchedIds.length ||
      !resolvedArray.every((id, i) => id === watchedIds[i])) {
    localStorage.setItem('pitchrank_watchedTeams', JSON.stringify(resolvedArray));
  }

  return resolvedArray;
}
```

### 3.4 Create Merge Admin API

**File:** `frontend/app/api/merge-teams/route.ts`

```typescript
import { createClient } from '@supabase/supabase-js';
import { NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const {
      deprecatedTeamId,
      canonicalTeamId,
      mergedBy,
      mergeReason,
      confidenceScore,
      suggestionSignals
    } = await request.json();

    // Validate required fields
    if (!deprecatedTeamId || !canonicalTeamId || !mergedBy) {
      return NextResponse.json(
        { error: 'Missing required fields' },
        { status: 400 }
      );
    }

    const supabase = createClient(
      process.env.SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!
    );

    // Execute merge via stored function
    const { data, error } = await supabase.rpc('execute_team_merge', {
      p_deprecated_team_id: deprecatedTeamId,
      p_canonical_team_id: canonicalTeamId,
      p_merged_by: mergedBy,
      p_merge_reason: mergeReason || null,
      p_confidence_score: confidenceScore || null,
      p_suggestion_signals: suggestionSignals || null,
    });

    if (error) {
      console.error('Merge error:', error);
      return NextResponse.json(
        { error: error.message },
        { status: 500 }
      );
    }

    if (!data.success) {
      return NextResponse.json(
        { error: data.error },
        { status: 400 }
      );
    }

    return NextResponse.json(data);

  } catch (error) {
    console.error('Merge API error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

// Revert a merge
export async function DELETE(request: NextRequest) {
  try {
    const { mergeId, revertedBy, revertReason } = await request.json();

    if (!mergeId || !revertedBy) {
      return NextResponse.json(
        { error: 'Missing required fields' },
        { status: 400 }
      );
    }

    const supabase = createClient(
      process.env.SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!
    );

    const { data, error } = await supabase.rpc('revert_team_merge', {
      p_merge_id: mergeId,
      p_reverted_by: revertedBy,
      p_revert_reason: revertReason || null,
    });

    if (error) {
      return NextResponse.json(
        { error: error.message },
        { status: 500 }
      );
    }

    return NextResponse.json(data);

  } catch (error) {
    console.error('Revert API error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
```

---

## PHASE 4: Option 8 - Intelligent Merge Suggestions

### 4.1 Create Merge Suggestion Engine

**File:** `src/merge/suggestion_engine.py`

```python
"""
Intelligent merge suggestion engine (Option 8).
Analyzes teams to identify likely duplicates.
"""
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
from rapidfuzz import fuzz
from supabase import Client

@dataclass
class MergeSuggestion:
    """A suggested team merge with confidence signals."""
    team_a_id: str
    team_b_id: str
    team_a_name: str
    team_b_name: str
    final_score: float
    signals: Dict[str, float]
    recommended_canonical: str  # Which team should be canonical
    recommendation_reason: str

class MergeSuggestionEngine:
    """
    Analyzes teams to identify likely duplicates based on multiple signals:
    - Name similarity
    - Opponent overlap
    - Schedule correlation
    - Geography consistency
    - Performance fingerprint
    """

    # Signal weights (tuned based on your recommendation)
    WEIGHTS = {
        'name_similarity': 0.20,
        'opponent_overlap': 0.40,  # Strongest signal
        'schedule_alignment': 0.25,
        'geography': 0.10,
        'performance_fingerprint': 0.05,
    }

    # Thresholds
    HIGH_CONFIDENCE = 0.92
    LIKELY_MATCH = 0.85

    def __init__(self, supabase_client: Client):
        self.client = supabase_client

    def find_suggestions(
        self,
        age_group: str,
        gender: str,
        min_games: int = 5,
        limit: int = 50
    ) -> List[MergeSuggestion]:
        """
        Find merge suggestions for teams in a specific cohort.

        Args:
            age_group: e.g., 'u12'
            gender: 'Male' or 'Female'
            min_games: Minimum games required for comparison
            limit: Maximum suggestions to return
        """
        # 1. Get all active teams in cohort with game counts
        teams = self._get_cohort_teams(age_group, gender, min_games)

        if len(teams) < 2:
            return []

        # 2. Calculate pairwise signals
        suggestions = []
        team_ids = list(teams.keys())

        for i, team_a_id in enumerate(team_ids):
            for team_b_id in team_ids[i+1:]:
                signals = self._calculate_signals(
                    team_a_id, team_b_id,
                    teams[team_a_id], teams[team_b_id]
                )

                final_score = sum(
                    signals[k] * self.WEIGHTS[k]
                    for k in self.WEIGHTS
                )

                if final_score >= self.LIKELY_MATCH:
                    canonical, reason = self._recommend_canonical(
                        team_a_id, team_b_id,
                        teams[team_a_id], teams[team_b_id]
                    )

                    suggestions.append(MergeSuggestion(
                        team_a_id=team_a_id,
                        team_b_id=team_b_id,
                        team_a_name=teams[team_a_id]['team_name'],
                        team_b_name=teams[team_b_id]['team_name'],
                        final_score=final_score,
                        signals=signals,
                        recommended_canonical=canonical,
                        recommendation_reason=reason,
                    ))

        # Sort by score descending and limit
        suggestions.sort(key=lambda x: x.final_score, reverse=True)
        return suggestions[:limit]

    def _get_cohort_teams(
        self,
        age_group: str,
        gender: str,
        min_games: int
    ) -> Dict[str, Dict]:
        """Get all teams in cohort with metadata."""
        response = self.client.table('teams').select(
            'team_id_master, team_name, club_name, state_code'
        ).eq('age_group', age_group).eq('gender', gender).eq(
            'is_deprecated', False
        ).execute()

        teams = {}
        for row in response.data:
            team_id = str(row['team_id_master'])

            # Get game count
            games_resp = self.client.table('games').select(
                'id', count='exact'
            ).or_(
                f'home_team_master_id.eq.{team_id},'
                f'away_team_master_id.eq.{team_id}'
            ).execute()

            game_count = games_resp.count or 0
            if game_count >= min_games:
                teams[team_id] = {
                    **row,
                    'game_count': game_count
                }

        return teams

    def _calculate_signals(
        self,
        team_a_id: str,
        team_b_id: str,
        team_a: Dict,
        team_b: Dict,
    ) -> Dict[str, float]:
        """Calculate all signal scores for a pair of teams."""
        return {
            'name_similarity': self._name_similarity(team_a, team_b),
            'opponent_overlap': self._opponent_overlap(team_a_id, team_b_id),
            'schedule_alignment': self._schedule_alignment(team_a_id, team_b_id),
            'geography': self._geography_score(team_a, team_b),
            'performance_fingerprint': self._performance_fingerprint(team_a_id, team_b_id),
        }

    def _name_similarity(self, team_a: Dict, team_b: Dict) -> float:
        """Calculate name similarity using fuzzy matching."""
        name_a = self._normalize_name(team_a['team_name'])
        name_b = self._normalize_name(team_b['team_name'])

        # Use token set ratio for best match on names with different word orders
        name_score = fuzz.token_set_ratio(name_a, name_b) / 100.0

        # Also compare club names if available
        club_a = team_a.get('club_name', '')
        club_b = team_b.get('club_name', '')

        if club_a and club_b:
            club_score = fuzz.token_set_ratio(
                self._normalize_name(club_a),
                self._normalize_name(club_b)
            ) / 100.0
            return 0.7 * name_score + 0.3 * club_score

        return name_score

    def _normalize_name(self, name: str) -> str:
        """Normalize team name for comparison."""
        if not name:
            return ''

        name = name.lower()

        # Remove common suffixes
        for suffix in [' fc', ' sc', ' academy', ' soccer', ' club',
                      ' youth', ' boys', ' girls', ' mls next']:
            name = name.replace(suffix, '')

        # Remove years/birth years (e.g., "2010", "2012")
        import re
        name = re.sub(r'\b20\d{2}\b', '', name)

        # Collapse whitespace
        name = ' '.join(name.split())

        return name.strip()

    def _opponent_overlap(self, team_a_id: str, team_b_id: str) -> float:
        """
        Calculate Jaccard overlap of opponents.
        This is the strongest signal for duplicate detection.
        """
        # Get opponents for team A
        resp_a = self.client.table('games').select(
            'home_team_master_id, away_team_master_id'
        ).or_(
            f'home_team_master_id.eq.{team_a_id},'
            f'away_team_master_id.eq.{team_a_id}'
        ).execute()

        opponents_a = set()
        for g in resp_a.data:
            opp = g['away_team_master_id'] if g['home_team_master_id'] == team_a_id else g['home_team_master_id']
            if opp:
                opponents_a.add(opp)

        # Get opponents for team B
        resp_b = self.client.table('games').select(
            'home_team_master_id, away_team_master_id'
        ).or_(
            f'home_team_master_id.eq.{team_b_id},'
            f'away_team_master_id.eq.{team_b_id}'
        ).execute()

        opponents_b = set()
        for g in resp_b.data:
            opp = g['away_team_master_id'] if g['home_team_master_id'] == team_b_id else g['home_team_master_id']
            if opp:
                opponents_b.add(opp)

        # Remove each other from opponent sets
        opponents_a.discard(team_b_id)
        opponents_b.discard(team_a_id)

        # Calculate Jaccard similarity
        if not opponents_a and not opponents_b:
            return 0.0

        intersection = len(opponents_a & opponents_b)
        union = len(opponents_a | opponents_b)

        return intersection / union if union > 0 else 0.0

    def _schedule_alignment(self, team_a_id: str, team_b_id: str) -> float:
        """Calculate how well game dates align between teams."""
        # Get game dates for team A
        resp_a = self.client.table('games').select('game_date').or_(
            f'home_team_master_id.eq.{team_a_id},'
            f'away_team_master_id.eq.{team_a_id}'
        ).execute()
        dates_a = set(g['game_date'] for g in resp_a.data)

        # Get game dates for team B
        resp_b = self.client.table('games').select('game_date').or_(
            f'home_team_master_id.eq.{team_b_id},'
            f'away_team_master_id.eq.{team_b_id}'
        ).execute()
        dates_b = set(g['game_date'] for g in resp_b.data)

        if not dates_a or not dates_b:
            return 0.0

        # Calculate overlap (same dates = likely same team at same events)
        intersection = len(dates_a & dates_b)
        union = len(dates_a | dates_b)

        return intersection / union if union > 0 else 0.0

    def _geography_score(self, team_a: Dict, team_b: Dict) -> float:
        """Score based on geographic consistency."""
        state_a = team_a.get('state_code', '')
        state_b = team_b.get('state_code', '')

        if not state_a or not state_b:
            return 0.5  # Unknown, neutral

        if state_a == state_b:
            return 1.0  # Same state, likely

        # Check if neighboring states (simplified)
        # You could expand this with actual neighbor relationships
        return 0.3  # Different states, less likely

    def _performance_fingerprint(self, team_a_id: str, team_b_id: str) -> float:
        """
        Compare performance patterns (goal differential, win rate).
        Least reliable signal, used only as tie-breaker.
        """
        # Get performance stats for team A
        stats_a = self._get_team_stats(team_a_id)
        stats_b = self._get_team_stats(team_b_id)

        if not stats_a or not stats_b:
            return 0.5

        # Compare win rates
        win_rate_diff = abs(stats_a['win_rate'] - stats_b['win_rate'])

        # Compare goal differential per game
        gd_diff = abs(stats_a['gd_per_game'] - stats_b['gd_per_game'])

        # Lower differences = higher similarity
        win_score = max(0, 1 - win_rate_diff * 2)
        gd_score = max(0, 1 - gd_diff / 3)

        return 0.5 * win_score + 0.5 * gd_score

    def _get_team_stats(self, team_id: str) -> Optional[Dict]:
        """Get basic performance stats for a team."""
        resp = self.client.table('games').select(
            'home_team_master_id, away_team_master_id, '
            'home_score, away_score, result'
        ).or_(
            f'home_team_master_id.eq.{team_id},'
            f'away_team_master_id.eq.{team_id}'
        ).execute()

        if not resp.data:
            return None

        wins = 0
        total = 0
        goals_for = 0
        goals_against = 0

        for g in resp.data:
            is_home = g['home_team_master_id'] == team_id
            home_score = g['home_score'] or 0
            away_score = g['away_score'] or 0

            if is_home:
                goals_for += home_score
                goals_against += away_score
                if home_score > away_score:
                    wins += 1
            else:
                goals_for += away_score
                goals_against += home_score
                if away_score > home_score:
                    wins += 1

            total += 1

        if total == 0:
            return None

        return {
            'win_rate': wins / total,
            'gd_per_game': (goals_for - goals_against) / total,
            'games': total,
        }

    def _recommend_canonical(
        self,
        team_a_id: str,
        team_b_id: str,
        team_a: Dict,
        team_b: Dict
    ) -> Tuple[str, str]:
        """
        Recommend which team should be canonical.
        Prefer: more games, longer history, cleaner name.
        """
        reasons = []

        games_a = team_a.get('game_count', 0)
        games_b = team_b.get('game_count', 0)

        if games_a > games_b * 1.5:
            reasons.append(f"Team A has more games ({games_a} vs {games_b})")
            return team_a_id, '; '.join(reasons)
        elif games_b > games_a * 1.5:
            reasons.append(f"Team B has more games ({games_b} vs {games_a})")
            return team_b_id, '; '.join(reasons)

        # Prefer cleaner/shorter names
        name_a = team_a.get('team_name', '')
        name_b = team_b.get('team_name', '')

        if len(name_a) < len(name_b) * 0.8:
            reasons.append("Team A has cleaner name")
            return team_a_id, '; '.join(reasons)
        elif len(name_b) < len(name_a) * 0.8:
            reasons.append("Team B has cleaner name")
            return team_b_id, '; '.join(reasons)

        # Default to first team
        reasons.append("Similar characteristics, defaulting to first team")
        return team_a_id, '; '.join(reasons)
```

### 4.2 Create Suggestions API

**File:** `frontend/app/api/merge-suggestions/route.ts`

```typescript
import { createClient } from '@supabase/supabase-js';
import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  try {
    const searchParams = request.nextUrl.searchParams;
    const ageGroup = searchParams.get('age_group');
    const gender = searchParams.get('gender');
    const minConfidence = parseFloat(searchParams.get('min_confidence') || '0.85');

    if (!ageGroup || !gender) {
      return NextResponse.json(
        { error: 'age_group and gender are required' },
        { status: 400 }
      );
    }

    // Call Python suggestion engine via edge function or direct DB query
    // For now, return mock structure - implement via Python backend
    const supabase = createClient(
      process.env.SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!
    );

    // This would be replaced with actual suggestion engine call
    const suggestions = await generateSuggestions(supabase, ageGroup, gender, minConfidence);

    return NextResponse.json({ suggestions });

  } catch (error) {
    console.error('Suggestions API error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

async function generateSuggestions(
  supabase: any,
  ageGroup: string,
  gender: string,
  minConfidence: number
) {
  // Placeholder - implement via Python backend or edge function
  return [];
}
```

---

## PHASE 5: Testing & Validation

### 5.1 Unit Tests

**File:** `tests/unit/test_merge_resolver.py`

```python
import pytest
from src.utils.merge_resolver import MergeResolver
from unittest.mock import Mock, MagicMock

class TestMergeResolver:
    def test_resolve_unmapped_team(self):
        """Unmapped team IDs should return unchanged."""
        client = Mock()
        client.table.return_value.select.return_value.execute.return_value = Mock(data=[])

        resolver = MergeResolver(client)
        resolver.load_merge_map()

        assert resolver.resolve('team-123') == 'team-123'

    def test_resolve_mapped_team(self):
        """Mapped team IDs should return canonical ID."""
        client = Mock()
        client.table.return_value.select.return_value.execute.return_value = Mock(
            data=[{'deprecated_team_id': 'old-id', 'canonical_team_id': 'new-id'}]
        )

        resolver = MergeResolver(client)
        resolver.load_merge_map()

        assert resolver.resolve('old-id') == 'new-id'
        assert resolver.resolve('new-id') == 'new-id'  # Canonical stays same

    def test_version_changes_with_map(self):
        """Version should change when map changes."""
        client = Mock()

        # First load
        client.table.return_value.select.return_value.execute.return_value = Mock(data=[])
        resolver = MergeResolver(client)
        resolver.load_merge_map()
        v1 = resolver.version

        # Second load with different data
        client.table.return_value.select.return_value.execute.return_value = Mock(
            data=[{'deprecated_team_id': 'a', 'canonical_team_id': 'b'}]
        )
        resolver._merge_map = {}  # Reset
        resolver._version = None
        resolver.load_merge_map()
        v2 = resolver.version

        assert v1 != v2
```

### 5.2 Integration Tests

**File:** `tests/integration/test_merge_flow.py`

```python
import pytest
from supabase import create_client

@pytest.fixture
def supabase():
    return create_client(
        os.environ['SUPABASE_URL'],
        os.environ['SUPABASE_SERVICE_ROLE_KEY']
    )

class TestMergeFlow:
    def test_execute_merge(self, supabase):
        """Test complete merge flow."""
        # Create test teams
        # Execute merge
        # Verify alias cascade
        # Verify audit log
        # Verify revert works
        pass

    def test_chain_prevention(self, supabase):
        """Test that merge chains are prevented."""
        pass

    def test_circular_prevention(self, supabase):
        """Test that circular merges are prevented."""
        pass
```

---

## Rollback Procedures

### Emergency Rollback

If merge causes issues:

```sql
-- 1. Find the problematic merge
SELECT * FROM team_merge_audit
WHERE performed_at > NOW() - INTERVAL '24 hours'
ORDER BY performed_at DESC;

-- 2. Revert via function
SELECT revert_team_merge(
    '<merge_id>',
    'admin_username',
    'Emergency rollback - rankings issue'
);

-- 3. Force ranking recalculation
-- Run: python scripts/calculate_rankings.py --force-rebuild

-- 4. Clear frontend cache (users need to refresh)
```

### Full Feature Rollback

To completely remove merge feature:

```sql
-- 1. Revert all merges
DO $$
DECLARE
    m RECORD;
BEGIN
    FOR m IN SELECT id FROM team_merge_map LOOP
        PERFORM revert_team_merge(m.id, 'system', 'Feature rollback');
    END LOOP;
END $$;

-- 2. Drop merge tables (after confirming data is safe)
DROP TABLE IF EXISTS team_merge_audit;
DROP TABLE IF EXISTS team_merge_map;

-- 3. Remove is_deprecated column
ALTER TABLE teams DROP COLUMN IF EXISTS is_deprecated;
```

---

## Implementation Timeline

| Phase | Description | Dependencies | Estimated Effort |
|-------|-------------|--------------|------------------|
| 1.1-1.3 | Database schema | None | 1 day |
| 1.4 | Merge functions | 1.1-1.3 | 1 day |
| 1.5 | View updates | 1.4 | 0.5 day |
| 2.1-2.4 | Backend resolver | Phase 1 | 2 days |
| 3.1-3.4 | Frontend updates | Phase 1 | 2 days |
| 4.1-4.2 | Option 8 engine | Phase 2 | 3 days |
| 5.1-5.2 | Testing | All | 2 days |

**Total: ~11-12 days**

---

## Success Criteria

- [ ] Merges execute atomically with full audit trail
- [ ] Chain/circular merges are prevented at DB level
- [ ] Rankings recalculate correctly with merged teams
- [ ] Cache invalidates on merge
- [ ] Frontend redirects deprecated team pages
- [ ] Watchlists migrate to canonical teams
- [ ] All merges are reversible
- [ ] Option 8 suggests merges with >85% accuracy
