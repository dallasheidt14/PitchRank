#!/usr/bin/env python3
"""
Unit test for the merge resolution pipeline in data_adapter.py.

This script simulates the exact pipeline used in fetch_games_for_rankings
with mock data to verify merge resolution correctly combines deprecated
team games with canonical team games.

Run: python scripts/test_merge_pipeline.py
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from unittest.mock import MagicMock

# Import MergeResolver directly (avoiding __init__.py import chains)
import importlib.util
spec = importlib.util.spec_from_file_location("merge_resolver", str(Path(__file__).parent.parent / "src/utils/merge_resolver.py"))
merge_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_mod)
MergeResolver = merge_mod.MergeResolver

# Test configuration
CANONICAL_ID = '691eb36d-95b2-4a08-bd59-13c1b0e830bb'
DEPRECATED_ID = '1ad83e6f-aaaa-bbbb-cccc-dddddddddddd'
OPPONENT_A = 'aaaaaaaa-1111-2222-3333-444444444444'
OPPONENT_B = 'bbbbbbbb-1111-2222-3333-444444444444'
OPPONENT_C = 'cccccccc-1111-2222-3333-444444444444'


def test_merge_resolution():
    """Test that merge resolution combines deprecated and canonical team games."""
    print("=" * 70)
    print("TEST: Merge resolution pipeline")
    print("=" * 70)

    # ---- Setup: Create a mock MergeResolver ----
    resolver = MergeResolver.__new__(MergeResolver)
    resolver._merge_map = {DEPRECATED_ID: CANONICAL_ID}
    resolver._version = "test123"
    resolver._loaded = True
    resolver.client = None

    assert resolver.has_merges, "has_merges should be True"
    assert resolver.resolve(DEPRECATED_ID) == CANONICAL_ID, "resolve should map deprecated to canonical"
    assert resolver.resolve(CANONICAL_ID) == CANONICAL_ID, "resolve should leave canonical unchanged"
    print("✅ MergeResolver setup OK")

    # ---- Setup: Create mock perspective rows ----
    # Simulate what fetch_games_for_rankings produces BEFORE merge resolution
    # Canonical team has 3 games, deprecated team has 5 games
    rows = []

    # Canonical team games (home perspective)
    for i in range(3):
        rows.append({
            'game_id': f'canonical_game_{i}',
            'id': f'uuid_canonical_{i}',
            'date': pd.Timestamp('2026-01-15') + pd.Timedelta(days=i),
            'team_id': CANONICAL_ID,
            'opp_id': OPPONENT_A,
            'home_team_master_id': CANONICAL_ID,
            'age': '12',
            'gender': 'male',
            'opp_age': '12',
            'opp_gender': 'male',
            'gf': 2.0,
            'ga': 1.0,
        })

    # Deprecated team games (home perspective)
    for i in range(5):
        rows.append({
            'game_id': f'deprecated_game_{i}',
            'id': f'uuid_deprecated_{i}',
            'date': pd.Timestamp('2026-02-01') + pd.Timedelta(days=i),
            'team_id': DEPRECATED_ID,
            'opp_id': OPPONENT_B,
            'home_team_master_id': DEPRECATED_ID,
            'age': '12',
            'gender': 'male',
            'opp_age': '12',
            'opp_gender': 'male',
            'gf': 3.0,
            'ga': 0.0,
        })

    # Opponent perspective rows (opponents playing against deprecated team)
    for i in range(5):
        rows.append({
            'game_id': f'deprecated_game_{i}',
            'id': f'uuid_deprecated_{i}',
            'date': pd.Timestamp('2026-02-01') + pd.Timedelta(days=i),
            'team_id': OPPONENT_B,
            'opp_id': DEPRECATED_ID,
            'home_team_master_id': DEPRECATED_ID,
            'age': '12',
            'gender': 'male',
            'opp_age': '12',
            'opp_gender': 'male',
            'gf': 0.0,
            'ga': 3.0,
        })

    v53e_df = pd.DataFrame(rows)
    print(f"✅ Created {len(v53e_df)} perspective rows (3 canonical + 5 deprecated + 5 opponent)")

    # Build team maps (as data_adapter.py does)
    team_age_map = {
        CANONICAL_ID: '12',
        DEPRECATED_ID: '12',
        OPPONENT_A: '12',
        OPPONENT_B: '12',
    }
    team_gender_map = {
        CANONICAL_ID: 'male',
        DEPRECATED_ID: 'male',
        OPPONENT_A: 'male',
        OPPONENT_B: 'male',
    }

    # Build deprecated_team_ids set (as data_adapter.py does)
    deprecated_team_ids = {DEPRECATED_ID}

    # ---- PRE-MERGE STATE ----
    canon_before = (v53e_df['team_id'] == CANONICAL_ID).sum()
    dep_before = (v53e_df['team_id'] == DEPRECATED_ID).sum()
    print(f"\n--- Pre-merge state ---")
    print(f"  canonical as team_id: {canon_before}")
    print(f"  deprecated as team_id: {dep_before}")

    # ---- APPLY MERGE RESOLUTION (exact same code as data_adapter.py) ----
    print(f"\n--- Applying merge resolution ---")
    v53e_df = resolver.resolve_dataframe(v53e_df, ['team_id', 'opp_id'])

    # Re-map age/gender
    v53e_df['age'] = v53e_df['team_id'].map(team_age_map).fillna(v53e_df['age'])
    v53e_df['gender'] = v53e_df['team_id'].map(team_gender_map).fillna(v53e_df['gender'])
    v53e_df['opp_age'] = v53e_df['opp_id'].map(team_age_map).fillna(v53e_df['opp_age'])
    v53e_df['opp_gender'] = v53e_df['opp_id'].map(team_gender_map).fillna(v53e_df['opp_gender'])

    # ---- POST-MERGE STATE ----
    canon_after = (v53e_df['team_id'] == CANONICAL_ID).sum()
    dep_after = (v53e_df['team_id'] == DEPRECATED_ID).sum()
    print(f"  canonical as team_id: {canon_after}")
    print(f"  deprecated as team_id: {dep_after}")

    # ---- DEPRECATED FILTER (exact same code as data_adapter.py) ----
    if deprecated_team_ids:
        before_filter = len(v53e_df)
        v53e_df = v53e_df[~v53e_df['team_id'].astype(str).isin(deprecated_team_ids)]
        removed = before_filter - len(v53e_df)
        print(f"\n--- Deprecated filter ---")
        print(f"  Removed {removed} rows")

    canon_final = (v53e_df['team_id'] == CANONICAL_ID).sum()
    print(f"\n--- Final state ---")
    print(f"  canonical as team_id: {canon_final}")
    print(f"  Total rows: {len(v53e_df)}")

    # ---- ASSERTIONS ----
    print(f"\n--- Assertions ---")

    # After merge, deprecated team's 5 games should be attributed to canonical
    assert dep_after == 0, f"FAIL: deprecated team still has {dep_after} rows after merge"
    print("✅ No deprecated team_id rows remain after merge resolution")

    # Canonical should now have 3 + 5 = 8 perspective rows
    assert canon_after == 8, f"FAIL: canonical has {canon_after} rows, expected 8"
    print("✅ Canonical team has 8 perspective rows (3 own + 5 merged)")

    # No rows should be removed by deprecated filter (all resolved)
    assert removed == 0, f"FAIL: deprecated filter removed {removed} rows, expected 0"
    print("✅ Deprecated filter removed 0 rows (all properly resolved)")

    # Final canonical count should be 8
    assert canon_final == 8, f"FAIL: final canonical has {canon_final} rows, expected 8"
    print("✅ Final canonical team count: 8 perspective rows")

    # Opponent B's opp_id should now point to canonical
    opp_b_rows = v53e_df[v53e_df['team_id'] == OPPONENT_B]
    opp_b_opp_ids = opp_b_rows['opp_id'].unique()
    assert CANONICAL_ID in opp_b_opp_ids, f"FAIL: Opponent B's opp_id doesn't include canonical"
    assert DEPRECATED_ID not in opp_b_opp_ids, f"FAIL: Opponent B's opp_id still has deprecated"
    print("✅ Opponent's opp_id correctly resolved to canonical")

    print("\n" + "=" * 70)
    print("ALL TESTS PASSED")
    print("=" * 70)
    print("\nConclusion: The merge resolution LOGIC is correct.")
    print("If the bug persists in production, the issue is likely:")
    print("  1. merge_resolver.has_merges is False (map didn't load)")
    print("  2. The merge map doesn't contain the expected entry")
    print("  3. UUID format mismatch between merge map and game data")
    print("\nRun: python scripts/diagnose_merge.py --canonical <canonical_team_id>")
    print("to check the production data.")


if __name__ == '__main__':
    test_merge_pipeline()
