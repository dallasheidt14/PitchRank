# SOS Monotonicity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore SOS normalization monotonicity by disabling connected-component normalization and aligning SOS shrinkage threshold with Active eligibility.

**Architecture:** Two independent config-default changes in `V53EConfig`: (1) `COMPONENT_SOS_ENABLED = False` eliminates pathological multi-team ceiling ties from per-component normalization, (2) `MIN_GAMES_FOR_TOP_SOS = 6` removes the shrinkage cliff for Active teams with 6–9 GP. Both old behaviors remain toggleable via config for rollback.

**Tech Stack:** Python 3.11, pandas, numpy, pytest

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/etl/v53e.py` | Modify | Two config default changes in V53EConfig (lines 94, 211) |
| `tests/unit/test_sos_monotonicity.py` | Create | All new tests for monotonicity + shrinkage fixes |
| `scripts/sos_monotonicity_trace.py` | Modify | Add before/after distribution comparison for B1 validation |

---

### Task 1: Write failing tests for Fix A (component normalization)

**Files:**
- Create: `tests/unit/test_sos_monotonicity.py`

- [ ] **Step 1: Create test file with helpers and first failing test**

```python
"""Tests for SOS monotonicity fixes.

Fix A: COMPONENT_SOS_ENABLED = False eliminates pathological ceiling ties.
Fix B: MIN_GAMES_FOR_TOP_SOS = 6 aligns SOS trust with Active eligibility.
"""

import pytest
import pandas as pd
import numpy as np

from src.etl.v53e import V53EConfig, compute_rankings


def _make_game(gid, date, home, away, hs, as_, age="15", gender="male",
               opp_age=None, opp_gender=None):
    """Create home + away perspective rows for a single game."""
    opp_age = opp_age or age
    opp_gender = opp_gender or gender
    return [
        {
            "game_id": str(gid), "date": pd.Timestamp(date),
            "team_id": home, "opp_id": away,
            "age": age, "gender": gender,
            "opp_age": opp_age, "opp_gender": opp_gender,
            "gf": hs, "ga": as_,
        },
        {
            "game_id": str(gid), "date": pd.Timestamp(date),
            "team_id": away, "opp_id": home,
            "age": opp_age, "gender": opp_gender,
            "opp_age": age, "opp_gender": gender,
            "gf": as_, "ga": hs,
        },
    ]


def _build_multi_component_league():
    """Build a league with TWO disconnected components to expose ceiling ties.

    Component A: 10 teams in a round-robin (each plays 9 games).
      team_A0 dominates (5-0 every game), team_A1 is strong (3-1), rest average.

    Component B: 4 teams in a round-robin (each plays 3 games).
      team_B0 dominates (4-0 every game), rest lose.

    The components share no opponents — they are disconnected subgraphs.
    With COMPONENT_SOS_ENABLED=True, the top team in each component
    gets sos_norm_component=1.0, creating ceiling ties.
    With COMPONENT_SOS_ENABLED=False, all 14 teams are normalized in
    one pool, and the top of Component B gets a lower sos_norm
    (because its opponents are weaker globally).
    """
    today = pd.Timestamp("2026-03-01")
    rows = []
    gid = 0

    # Component A: 10 teams, round-robin
    comp_a = [f"team_A{i}" for i in range(10)]
    for i, home in enumerate(comp_a):
        for away in comp_a[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            if home == "team_A0":
                hs, as_ = 5, 0
            elif away == "team_A0":
                hs, as_ = 0, 5
            elif home == "team_A1":
                hs, as_ = 3, 1
            elif away == "team_A1":
                hs, as_ = 1, 3
            else:
                hs, as_ = 2, 1
            rows.extend(_make_game(gid, date, home, away, hs, as_))

    # Component B: 4 teams, round-robin (completely disconnected from A)
    comp_b = [f"team_B{i}" for i in range(4)]
    for i, home in enumerate(comp_b):
        for away in comp_b[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            if home == "team_B0":
                hs, as_ = 4, 0
            elif away == "team_B0":
                hs, as_ = 0, 4
            else:
                hs, as_ = 1, 1
            rows.extend(_make_game(gid, date, home, away, hs, as_))

    return pd.DataFrame(rows)


class TestFixA_ComponentNormalization:
    """Fix A: disabling component normalization eliminates ceiling ties."""

    def test_component_enabled_creates_ceiling_ties(self):
        """With COMPONENT_SOS_ENABLED=True, top teams in separate components
        can both reach sos_norm=1.0 (or very close), even though the small
        component's top team has weaker opponents globally."""
        cfg = V53EConfig()
        cfg.COMPONENT_SOS_ENABLED = True
        games = _build_multi_component_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        # Count teams at the ceiling (sos_norm >= 0.99)
        ceiling_count = (teams["sos_norm"] >= 0.99).sum()
        # With component normalization, multiple teams hit the ceiling
        assert ceiling_count > 1, (
            f"Expected multiple ceiling ties with COMPONENT_SOS_ENABLED=True, "
            f"but only {ceiling_count} team(s) at sos_norm >= 0.99"
        )

    def test_component_disabled_no_pathological_ties(self):
        """With COMPONENT_SOS_ENABLED=False (new default), there should be
        no pathological multi-team ceiling ties. At most 1 team at the
        ceiling per cohort."""
        cfg = V53EConfig()
        cfg.COMPONENT_SOS_ENABLED = False
        games = _build_multi_component_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        # At most 1 team should be at sos_norm >= 0.99
        ceiling_count = (teams["sos_norm"] >= 0.99).sum()
        assert ceiling_count <= 1, (
            f"Expected at most 1 team at ceiling with COMPONENT_SOS_ENABLED=False, "
            f"but found {ceiling_count}. Ceiling teams:\n"
            f"{teams[teams['sos_norm'] >= 0.99][['team_id', 'sos', 'sos_norm']].to_string()}"
        )

    def test_default_config_has_component_disabled(self):
        """The new default for COMPONENT_SOS_ENABLED should be False."""
        cfg = V53EConfig()
        assert cfg.COMPONENT_SOS_ENABLED is False, (
            f"Expected COMPONENT_SOS_ENABLED=False as new default, got {cfg.COMPONENT_SOS_ENABLED}"
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_sos_monotonicity.py::TestFixA_ComponentNormalization -v`

Expected:
- `test_component_enabled_creates_ceiling_ties` — PASS (old behavior still works)
- `test_component_disabled_no_pathological_ties` — PASS (disabled path already exists)
- `test_default_config_has_component_disabled` — FAIL (current default is `True`)

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add tests/unit/test_sos_monotonicity.py
git commit -m "test: add failing test for COMPONENT_SOS_ENABLED default change"
```

---

### Task 2: Implement Fix A — change COMPONENT_SOS_ENABLED default

**Files:**
- Modify: `src/etl/v53e.py` (line 211)

- [ ] **Step 1: Change the default**

In `src/etl/v53e.py`, line 211, change:

```python
    COMPONENT_SOS_ENABLED: bool = True
```

to:

```python
    COMPONENT_SOS_ENABLED: bool = False  # Disabled: global-only SOS normalization prevents ceiling ties
```

- [ ] **Step 2: Run the Fix A tests**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_sos_monotonicity.py::TestFixA_ComponentNormalization -v`

Expected: All 3 PASS

- [ ] **Step 3: Run existing tests to confirm no breakage**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py -v`

Expected: All 10 tests PASS (component normalization toggle doesn't affect cross-age tests since they run single-cohort with small teams)

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank
git add src/etl/v53e.py
git commit -m "fix: disable connected-component SOS normalization by default

COMPONENT_SOS_ENABLED now defaults to False. All teams normalized
in a single [age, gender] pool, eliminating pathological multi-team
ceiling ties at sos_norm=1.000. Old behavior restorable via config."
```

---

### Task 3: Write failing tests for Fix B (shrinkage threshold)

**Files:**
- Modify: `tests/unit/test_sos_monotonicity.py`

- [ ] **Step 1: Add Fix B tests**

Append to `tests/unit/test_sos_monotonicity.py`:

```python
def _build_varied_gp_league():
    """Build a league where teams have varied games played (3 to 12).

    Creates a 12-team league where:
    - team_full: plays all 11 opponents (11 GP) — full sample
    - team_10gp: plays 10 opponents
    - team_9gp: plays 9 opponents
    - ...down to team_3gp: plays 3 opponents

    All teams win their games 3-1 against the same set of opponents
    (a subset of the filler pool), so their raw SOS should be similar.
    The only difference is GP.
    """
    today = pd.Timestamp("2026-03-01")
    rows = []
    gid = 0

    # 12 filler opponents that play each other to establish stable strengths
    fillers = [f"filler_{i}" for i in range(12)]
    for i, home in enumerate(fillers):
        for away in fillers[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game(gid, date, home, away, 2, 1))

    # Teams with varied GP, all winning 3-1
    for gp_count in range(3, 13):
        team_name = f"team_{gp_count}gp"
        for j in range(gp_count):
            gid += 1
            date = today - pd.Timedelta(days=gid)
            opp = fillers[j % len(fillers)]
            rows.extend(_make_game(gid, date, team_name, opp, 3, 1))

    return pd.DataFrame(rows)


class TestFixB_ShrinkageThreshold:
    """Fix B: MIN_GAMES_FOR_TOP_SOS = 6 aligns with Active eligibility."""

    def test_default_threshold_is_6(self):
        """New default MIN_GAMES_FOR_TOP_SOS should be 6."""
        cfg = V53EConfig()
        assert cfg.MIN_GAMES_FOR_TOP_SOS == 6, (
            f"Expected MIN_GAMES_FOR_TOP_SOS=6, got {cfg.MIN_GAMES_FOR_TOP_SOS}"
        )

    def test_6gp_team_not_shrunk(self):
        """A team with exactly 6 GP should have no SOS shrinkage applied
        (sample_flag should be 'OK', not 'LOW_SAMPLE')."""
        cfg = V53EConfig()
        cfg.MIN_GAMES_FOR_TOP_SOS = 6
        cfg.COMPONENT_SOS_ENABLED = False
        games = _build_varied_gp_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        team_6 = teams[teams["team_id"] == "team_6gp"]
        assert len(team_6) == 1, "team_6gp not found in results"
        assert team_6.iloc[0]["sample_flag"] == "OK", (
            f"team_6gp should have sample_flag='OK' with threshold=6, "
            f"got '{team_6.iloc[0]['sample_flag']}'"
        )

    def test_5gp_team_still_shrunk(self):
        """A team with 5 GP should still be shrunk (below the threshold)."""
        cfg = V53EConfig()
        cfg.MIN_GAMES_FOR_TOP_SOS = 6
        cfg.COMPONENT_SOS_ENABLED = False
        games = _build_varied_gp_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        team_5 = teams[teams["team_id"] == "team_5gp"]
        assert len(team_5) == 1, "team_5gp not found in results"
        assert team_5.iloc[0]["sample_flag"] == "LOW_SAMPLE", (
            f"team_5gp should have sample_flag='LOW_SAMPLE' with threshold=6, "
            f"got '{team_5.iloc[0]['sample_flag']}'"
        )

    def test_6gp_to_12gp_sos_ordering_preserved(self):
        """Among teams with 6+ GP playing the same opponents and winning 3-1,
        sos_norm should be roughly similar (no large inversions from shrinkage).
        The max spread among these teams should be < 0.10."""
        cfg = V53EConfig()
        cfg.MIN_GAMES_FOR_TOP_SOS = 6
        cfg.COMPONENT_SOS_ENABLED = False
        games = _build_varied_gp_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        # Get teams with 6+ GP
        ok_teams = teams[
            teams["team_id"].str.match(r"team_\d+gp")
            & (teams["gp"] >= 6)
        ].sort_values("gp")

        assert len(ok_teams) >= 5, f"Expected at least 5 OK teams, got {len(ok_teams)}"

        sos_spread = ok_teams["sos_norm"].max() - ok_teams["sos_norm"].min()
        assert sos_spread < 0.10, (
            f"SOS spread among 6+ GP teams playing same opponents should be < 0.10, "
            f"got {sos_spread:.4f}. Values:\n"
            f"{ok_teams[['team_id', 'gp', 'sos_norm', 'sample_flag']].to_string()}"
        )

    def test_old_threshold_creates_inversions(self):
        """With the old threshold of 10, teams with 6-9 GP should be noticeably
        shrunk compared to teams with 10+ GP, even when playing the same opponents.
        This confirms the old behavior creates the cliff we're fixing."""
        cfg = V53EConfig()
        cfg.MIN_GAMES_FOR_TOP_SOS = 10
        cfg.COMPONENT_SOS_ENABLED = False
        games = _build_varied_gp_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        team_6 = teams[teams["team_id"] == "team_6gp"].iloc[0]
        team_12 = teams[teams["team_id"] == "team_12gp"].iloc[0]

        # With threshold=10, team_6gp should be significantly shrunk vs team_12gp
        gap = team_12["sos_norm"] - team_6["sos_norm"]
        assert gap > 0.05, (
            f"With old threshold=10, expected significant gap between 6gp and 12gp teams. "
            f"6gp={team_6['sos_norm']:.4f}, 12gp={team_12['sos_norm']:.4f}, gap={gap:.4f}"
        )
```

- [ ] **Step 2: Run the tests to verify failures**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_sos_monotonicity.py::TestFixB_ShrinkageThreshold -v`

Expected:
- `test_default_threshold_is_6` — FAIL (current default is 10)
- `test_6gp_team_not_shrunk` — PASS (explicitly sets threshold=6)
- `test_5gp_team_still_shrunk` — PASS (explicitly sets threshold=6)
- `test_6gp_to_12gp_sos_ordering_preserved` — PASS (explicitly sets threshold=6)
- `test_old_threshold_creates_inversions` — PASS (confirms old behavior exists)

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add tests/unit/test_sos_monotonicity.py
git commit -m "test: add failing test for MIN_GAMES_FOR_TOP_SOS default change"
```

---

### Task 4: Implement Fix B — change MIN_GAMES_FOR_TOP_SOS default

**Files:**
- Modify: `src/etl/v53e.py` (line 94)

- [ ] **Step 1: Change the default**

In `src/etl/v53e.py`, line 94, change:

```python
    MIN_GAMES_FOR_TOP_SOS: int = 10  # Post-percentile shrinkage threshold (teams < this shrink toward anchor)
```

to:

```python
    MIN_GAMES_FOR_TOP_SOS: int = 6  # Aligned with Active eligibility (MIN_GAMES_PROVISIONAL)
```

- [ ] **Step 2: Run the Fix B tests**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_sos_monotonicity.py::TestFixB_ShrinkageThreshold -v`

Expected: All 5 PASS

- [ ] **Step 3: Run all monotonicity tests**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_sos_monotonicity.py -v`

Expected: All 8 tests PASS (3 Fix A + 5 Fix B)

- [ ] **Step 4: Run full unit test suite**

Run: `cd C:/PitchRank && python -m pytest tests/unit/ -v`

Expected: All tests PASS (340+)

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank
git add src/etl/v53e.py
git commit -m "fix: lower MIN_GAMES_FOR_TOP_SOS from 10 to 6

Aligns SOS trust with Active eligibility (MIN_GAMES_PROVISIONAL=6).
Teams with 6+ GP no longer have SOS shrunk toward 0.35 anchor.
Sub-6-GP teams still appropriately shrunk. Old behavior restorable
by setting MIN_GAMES_FOR_TOP_SOS=10."
```

---

### Task 5: B1 validation — 6–9 GP distribution comparison

**Files:**
- Modify: `scripts/sos_monotonicity_trace.py`

- [ ] **Step 1: Add before/after comparison function**

Add the following to the end of `scripts/sos_monotonicity_trace.py` (before the `if __name__` block), replacing the existing `section("10. DIAGNOSIS SUMMARY")` block and everything after it through the end of the file:

```python
# ── 10. Fix B validation: 6–9 GP distribution comparison ─────────────────────

section("10. FIX B VALIDATION: 6-9 GP DISTRIBUTION SHIFT")

# Run once with old defaults (threshold=10), once with new (threshold=6)
cfg_old = V53EConfig()
cfg_old.COMPONENT_SOS_ENABLED = False  # Fix A already applied
cfg_old.MIN_GAMES_FOR_TOP_SOS = 10

cfg_new = V53EConfig()
cfg_new.COMPONENT_SOS_ENABLED = False
cfg_new.MIN_GAMES_FOR_TOP_SOS = 6

print("  Running with old threshold (10)...")
result_old = compute_rankings(
    games_df=cohort_games.copy(),
    today=TODAY,
    cfg=cfg_old,
    team_state_map=team_state,
)
teams_old = result_old["teams"]

print("  Running with new threshold (6)...")
result_new = compute_rankings(
    games_df=cohort_games.copy(),
    today=TODAY,
    cfg=cfg_new,
    team_state_map=team_state,
)
teams_new = result_new["teams"]

# Merge old and new on team_id
merged = teams_old[["team_id", "gp", "sos_norm", "win_percentage"]].merge(
    teams_new[["team_id", "sos_norm"]],
    on="team_id",
    suffixes=("_old", "_new"),
)
merged["sos_shift"] = merged["sos_norm_new"] - merged["sos_norm_old"]

# Per-GP bucket analysis
print(f"\n  {'GP':>3} {'Count':>6} {'Med Shift':>10} {'Mean Shift':>11} {'Max Shift':>10} {'p95 Shift':>10}")
print(f"  {'---':>3} {'------':>6} {'----------':>10} {'-----------':>11} {'----------':>10} {'----------':>10}")
for gp_val in range(3, 13):
    bucket = merged[merged["gp"] == gp_val]
    if len(bucket) == 0:
        continue
    med = bucket["sos_shift"].median()
    mean = bucket["sos_shift"].mean()
    mx = bucket["sos_shift"].max()
    p95 = bucket["sos_shift"].quantile(0.95) if len(bucket) >= 5 else mx
    print(f"  {gp_val:>3} {len(bucket):>6} {med:>+10.4f} {mean:>+11.4f} {mx:>+10.4f} {p95:>+10.4f}")

# Threshold checks
for gp_val in [6, 7, 8, 9]:
    bucket = merged[merged["gp"] == gp_val]
    if len(bucket) == 0:
        continue
    med_shift = bucket["sos_shift"].median()
    weak_high = bucket[(bucket["win_percentage"] < 20) & (bucket["sos_norm_new"] > 0.90)]
    print(f"\n  GP={gp_val}: median shift={med_shift:+.4f} (target: < 0.15)")
    if len(weak_high) > 0:
        print(f"  ⚠️  {len(weak_high)} teams with win% < 20 AND sos_norm > 0.90:")
        print(weak_high[["team_id", "gp", "win_percentage", "sos_norm_old", "sos_norm_new", "sos_shift"]].to_string(index=False))
    else:
        print(f"  ✅ No weak teams (win% < 20) with sos_norm > 0.90")

# Threshold-count check: count of 6-9 GP teams above key thresholds
print(f"\n  Threshold-count check (6-9 GP teams):")
gp_6_9 = merged[(merged["gp"] >= 6) & (merged["gp"] <= 9)]
for threshold in [0.80, 0.90, 0.95]:
    old_count = (gp_6_9["sos_norm_old"] > threshold).sum()
    new_count = (gp_6_9["sos_norm_new"] > threshold).sum()
    print(f"  sos_norm > {threshold:.2f}: old={old_count}, new={new_count}, delta={new_count - old_count:+d}")

# Overall Spearman improvement
from scipy.stats import spearmanr

for label, t_df in [("Old (threshold=10)", teams_old), ("New (threshold=6)", teams_new)]:
    t_df = t_df.copy()
    t_df["raw_rank"] = t_df["sos"].rank(ascending=False, method="min")
    t_df["norm_rank"] = t_df["sos_norm"].rank(ascending=False, method="min")
    top30 = t_df.nsmallest(30, "raw_rank")
    rho, _ = spearmanr(top30["raw_rank"], top30["norm_rank"])
    print(f"\n  {label}: Spearman (top 30) = {rho:.4f}")
```

- [ ] **Step 2: Run the validation script**

Run: `cd C:/PitchRank && python scripts/sos_monotonicity_trace.py 2>&1`

Expected output should show:
- Median shift < 0.15 for each GP bucket 6–9
- No teams with win% < 20 AND sos_norm > 0.90
- Threshold-count delta shows controlled increase, not explosion
- Spearman (top 30) improves from ~-0.07 to > 0.80

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add scripts/sos_monotonicity_trace.py
git commit -m "script: add Fix B before/after distribution validation

Compares 6-9 GP team SOS distribution with old (threshold=10) vs
new (threshold=6) defaults. Checks median shift, weak-team inflation,
threshold counts, and Spearman correlation improvement."
```

---

### Task 6: Full test suite + code review

**Files:** None (validation only)

- [ ] **Step 1: Run full unit test suite**

Run: `cd C:/PitchRank && python -m pytest tests/unit/ -v`

Expected: All tests pass (340+)

- [ ] **Step 2: Code review**

Dispatch the code-reviewer agent to review:
- `src/etl/v53e.py` changes (two config defaults)
- `tests/unit/test_sos_monotonicity.py` (new test file)
- Verify: old code paths still intact behind toggles
- Verify: no other code references assume `COMPONENT_SOS_ENABLED=True` or `MIN_GAMES_FOR_TOP_SOS=10`

- [ ] **Step 3: Push to main**

```bash
cd C:/PitchRank
git push origin main
```

---

### Task 7: Production validation

**Files:** None (validation only)

- [ ] **Step 1: Trigger ranking workflow**

```bash
cd C:/PitchRank && gh workflow run "Calculate Rankings" --ref main
```

- [ ] **Step 2: After completion, validate U15M**

Query rankings_full for U15M:
- Count teams with sos_norm = 1.000 — should be at most 1 (was 10+)
- Spot-check DFW Tejanos (`5877fc70`): sos_norm should drop from 1.000
- Spot-check team `394aa723` (6 GP): sos_norm should rise from 0.739

- [ ] **Step 3: Validate cohort stability**

For each cohort, confirm mean sos_norm is ~0.500 (redistributive).

- [ ] **Step 4: Spot-check case studies**

Query rankings_full for:
- SE Black (`05e9e6aa`): sos_norm should remain stable or improve
- Phoenix (`691eb36d`): should remain #1 in AZ U12M
- OJB FC: verify ranking position
