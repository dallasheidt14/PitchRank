# Cross-Age Opponent Adjustment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the age-blind opponent adjustment in Layer 9 so that cross-age opponents receive age-scaled `abs_strength`, properly crediting offensive output against older/stronger opponents.

**Architecture:** Introduce age-anchor scaling into the `_adjust_for_opponent_strength` function by passing `global_strength_map` (already available in Pass 2) and the `AGE_TO_ANCHOR` mapping. When an opponent is from a different age group, their `abs_strength` is scaled by the ratio of opponent anchor to team anchor before computing the multiplier. This is a targeted change to one function + its call site, with a new config toggle for safe rollout.

**Tech Stack:** Python 3.11, pandas, numpy, pytest

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/etl/v53e.py` | Modify | Add `global_strength_map` and age-anchor scaling to opponent adjustment |
| `src/rankings/constants.py` | Read-only | Existing `AGE_TO_ANCHOR` mapping (no changes needed) |
| `src/rankings/calculator.py` | Read-only | Already passes `global_strength_map` in Pass 2 (no changes needed) |
| `tests/unit/test_cross_age_opponent_adjustment.py` | Create | Tests for age-scaled opponent adjustment |
| `scripts/validate_cross_age_fix.py` | Create | Before/after comparison on live data for Phoenix United Elite |

---

### Task 1: Add test for same-age opponent adjustment (baseline — no behavior change expected)

**Files:**
- Create: `tests/unit/test_cross_age_opponent_adjustment.py`

- [ ] **Step 1: Write the baseline test**

This test confirms that same-age opponent adjustment is unchanged by the fix. All opponents are the same age group as the team.

```python
"""Tests for cross-age opponent adjustment in v53e Layer 9."""

import pytest
import pandas as pd
import numpy as np

from src.etl.v53e import V53EConfig, compute_rankings


def _make_game_pair(gid, date, home, away, hs, as_, age="12", gender="male",
                    opp_age=None, opp_gender=None):
    """Create home + away perspective rows for a single game."""
    opp_age = opp_age or age
    opp_gender = opp_gender or gender
    return [
        {
            "game_id": gid,
            "date": pd.Timestamp(date),
            "team_id": home,
            "opp_id": away,
            "age": age,
            "gender": gender,
            "opp_age": opp_age,
            "opp_gender": opp_gender,
            "gf": hs,
            "ga": as_,
        },
        {
            "game_id": gid,
            "date": pd.Timestamp(date),
            "team_id": away,
            "opp_id": home,
            "age": opp_age,
            "gender": opp_gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": as_,
            "ga": hs,
        },
    ]


def _build_same_age_league(today=None):
    """Build a league where all teams are the same age group (U12M).

    8 teams, each playing 8 games. One dominant team (team_A) that
    wins all games with high GF. Used as baseline to confirm same-age
    adjustment is unchanged.
    """
    if today is None:
        today = pd.Timestamp("2026-03-01")

    teams = [f"team_{chr(65 + i)}" for i in range(8)]  # team_A through team_H
    rows = []
    gid = 0

    # Round-robin: each team plays each other once
    for i, home in enumerate(teams):
        for away in teams[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            # team_A dominates (5-0), others are average (2-1 or 1-2)
            if home == "team_A":
                hs, as_ = 5, 0
            elif away == "team_A":
                hs, as_ = 0, 5
            else:
                hs, as_ = 2, 1
            rows.extend(_make_game_pair(str(gid), date, home, away, hs, as_))

    return pd.DataFrame(rows)


class TestSameAgeBaseline:
    """Confirm same-age opponent adjustment produces expected rankings."""

    def test_dominant_team_has_highest_off_norm(self):
        """team_A scores 5 goals every game and should have the highest off_norm."""
        cfg = V53EConfig()
        games = _build_same_age_league()
        result = compute_rankings(games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        teams = result["teams"]

        team_a = teams[teams["team_id"] == "team_A"].iloc[0]
        other_off_norms = teams[teams["team_id"] != "team_A"]["off_norm"]

        assert team_a["off_norm"] > other_off_norms.max(), (
            f"team_A off_norm ({team_a['off_norm']:.3f}) should be highest, "
            f"but max other is {other_off_norms.max():.3f}"
        )
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py::TestSameAgeBaseline::test_dominant_team_has_highest_off_norm -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add tests/unit/test_cross_age_opponent_adjustment.py
git commit -m "test: add baseline same-age opponent adjustment test"
```

---

### Task 2: Add test for cross-age opponent adjustment (the failing test)

**Files:**
- Modify: `tests/unit/test_cross_age_opponent_adjustment.py`

- [ ] **Step 1: Write the cross-age test that exposes the bias**

This test creates two identical teams (same skill level, same record against peers) but one plays mostly U13 opponents while the other plays U12 opponents. Currently, the cross-age team will have lower off_norm. After the fix, the gap should shrink significantly.

Append to `tests/unit/test_cross_age_opponent_adjustment.py`:

```python
def _build_cross_age_league(today=None):
    """Build a league with cross-age matchups to expose the bias.

    Two strong U12 teams:
    - team_same: plays 8 games vs U12 opponents, scores 4 GF per game
    - team_cross: plays 2 games vs U12 (scores 4 GF), 6 games vs U13 (scores 2 GF)

    Both teams are equally dominant against their age-appropriate competition.
    team_cross scores fewer goals because U13 opponents are harder, not because
    they are worse at offense.

    Additional U12 and U13 teams fill out the league so normalization works.
    """
    if today is None:
        today = pd.Timestamp("2026-03-01")

    rows = []
    gid = 0

    u12_fillers = [f"u12_filler_{i}" for i in range(8)]
    u13_fillers = [f"u13_filler_{i}" for i in range(8)]

    # team_same: 8 games vs U12 opponents, all 4-1 wins
    for i, opp in enumerate(u12_fillers):
        gid += 1
        date = today - pd.Timedelta(days=gid)
        rows.extend(_make_game_pair(str(gid), date, "team_same", opp, 4, 1,
                                    age="12", gender="male"))

    # team_cross: 2 games vs U12 (4-1 wins), 6 games vs U13 (2-1 wins)
    for i in range(2):
        gid += 1
        date = today - pd.Timedelta(days=gid)
        rows.extend(_make_game_pair(str(gid), date, "team_cross", u12_fillers[i], 4, 1,
                                    age="12", gender="male"))

    for i in range(6):
        gid += 1
        date = today - pd.Timedelta(days=gid)
        # Cross-age: team_cross is U12, opponent is U13
        rows.extend(_make_game_pair(str(gid), date, "team_cross", u13_fillers[i], 2, 1,
                                    age="12", gender="male",
                                    opp_age="13", opp_gender="male"))

    # U12 fillers play each other (so they have enough games for normalization)
    for i, home in enumerate(u12_fillers):
        for away in u12_fillers[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game_pair(str(gid), date, home, away, 2, 1))

    # U13 fillers play each other (so they have strength in global_strength_map)
    for i, home in enumerate(u13_fillers):
        for away in u13_fillers[i + 1:]:
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game_pair(str(gid), date, home, away, 2, 1,
                                        age="13", gender="male"))

    return pd.DataFrame(rows)


class TestCrossAgeAdjustment:
    """Test that cross-age opponent adjustment properly credits offense."""

    def test_cross_age_team_off_norm_not_suppressed(self):
        """team_cross plays mostly U13 opponents and should NOT have dramatically
        lower off_norm than team_same, because the opponent adjustment should
        account for the age gap.

        Acceptance criterion: team_cross off_norm must be within 0.15 of
        team_same off_norm. Without the fix, the gap is typically > 0.30.
        """
        cfg = V53EConfig()
        games = _build_cross_age_league()

        # Build global_strength_map from U13 cohort (simulating Pass 2)
        # First run U13 cohort to get their strengths
        u13_games = games[
            (games["age"] == "13") & (games["gender"] == "male")
        ].copy()
        if not u13_games.empty:
            u13_result = compute_rankings(
                u13_games, today=pd.Timestamp("2026-03-01"), cfg=cfg
            )
            u13_teams = u13_result["teams"]
            global_strength_map = dict(
                zip(u13_teams["team_id"].astype(str), u13_teams["abs_strength"].astype(float))
            )
        else:
            global_strength_map = {}

        # Now run U12 cohort with global_strength_map (Pass 2 behavior)
        u12_games = games[
            (games["age"] == "12") & (games["gender"] == "male")
        ].copy()
        result = compute_rankings(
            u12_games,
            today=pd.Timestamp("2026-03-01"),
            cfg=cfg,
            global_strength_map=global_strength_map,
        )
        teams = result["teams"]

        same = teams[teams["team_id"] == "team_same"].iloc[0]
        cross = teams[teams["team_id"] == "team_cross"].iloc[0]

        gap = same["off_norm"] - cross["off_norm"]
        assert gap < 0.15, (
            f"Cross-age off_norm gap too large: team_same={same['off_norm']:.3f}, "
            f"team_cross={cross['off_norm']:.3f}, gap={gap:.3f}. "
            f"Opponent adjustment should compensate for age difficulty."
        )
```

- [ ] **Step 2: Run test to verify it fails (proving the bias exists)**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py::TestCrossAgeAdjustment::test_cross_age_team_off_norm_not_suppressed -v`
Expected: FAIL — gap will be > 0.15 because opponent adjustment is currently age-blind

- [ ] **Step 3: Commit the failing test**

```bash
cd C:/PitchRank
git add tests/unit/test_cross_age_opponent_adjustment.py
git commit -m "test: add failing cross-age opponent adjustment test

Demonstrates that teams playing older opponents get suppressed off_norm
because abs_strength in Layer 9 is age-blind. Test expects gap < 0.15
between same-age and cross-age teams with equivalent dominance."
```

---

### Task 3: Add config toggle for cross-age opponent adjustment

**Files:**
- Modify: `src/etl/v53e.py` (V53EConfig class, lines 110-114)

- [ ] **Step 1: Add the config flag**

Add a new config field to `V53EConfig` after the existing opponent adjustment fields (line 114):

```python
    CROSS_AGE_OPPONENT_ADJUST_ENABLED: bool = True  # Scale abs_strength by age anchor ratio for cross-age opponents
```

- [ ] **Step 2: Run existing tests to confirm nothing breaks**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py::TestSameAgeBaseline -v`
Expected: PASS (config field with no logic yet changes nothing)

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add src/etl/v53e.py
git commit -m "feat: add CROSS_AGE_OPPONENT_ADJUST_ENABLED config toggle"
```

---

### Task 4: Implement age-scaled opponent strength in `_adjust_for_opponent_strength`

**Files:**
- Modify: `src/etl/v53e.py` (function `_adjust_for_opponent_strength`, lines 761-811)

This is the core fix. The function needs to:
1. Accept `global_strength_map` and `age_anchor_map` as optional parameters
2. Accept the team's own age (for computing anchor ratios)
3. When a cross-age opponent is found, scale their strength by the anchor ratio

- [ ] **Step 1: Update function signature and opponent strength lookup**

Replace the current `_adjust_for_opponent_strength` function (lines 761-811) with:

```python
def _adjust_for_opponent_strength(
    games: pd.DataFrame,
    strength_map: Dict[str, float],
    cfg: V53EConfig,
    baseline: Optional[float] = None,
    global_strength_map: Optional[Dict[str, float]] = None,
    age_anchor_map: Optional[Dict[int, float]] = None,
    team_age: Optional[int] = None,
) -> pd.DataFrame:
    """
    Adjust goals for/against based on opponent strength to fix double-counting problem.

    For offense: Scoring against STRONG opponents gets MORE credit (multiplier > 1)
    For defense: Allowing goals to STRONG opponents gets LESS penalty (multiplier < 1)

    When cross-age adjustment is enabled (cfg.CROSS_AGE_OPPONENT_ADJUST_ENABLED),
    opponents from different age groups have their strength scaled by the ratio of
    their age anchor to the team's age anchor. This accounts for the inherent
    difficulty gap between age groups — a median U13 team is harder to score against
    than a median U12 team.

    Args:
        games: DataFrame with columns [gf, ga, opp_id, opp_age, w_game]
        strength_map: Dict mapping team_id to strength (0-1) for same-cohort teams
        cfg: Configuration
        baseline: Reference strength for adjustment (defaults to cfg.OPPONENT_ADJUST_BASELINE)
        global_strength_map: Dict mapping team_id to strength for ALL cohorts (Pass 2)
        age_anchor_map: Dict mapping integer age to anchor value (e.g., {12: 0.55, 13: 0.625})
        team_age: Integer age of the team being adjusted (e.g., 12 for U12)

    Returns:
        DataFrame with additional columns [gf_adjusted, ga_adjusted]
    """
    g = games.copy()

    # Use provided baseline or fall back to config
    if baseline is None:
        baseline = cfg.OPPONENT_ADJUST_BASELINE

    # Determine if cross-age scaling is active
    cross_age_active = (
        cfg.CROSS_AGE_OPPONENT_ADJUST_ENABLED
        and global_strength_map
        and age_anchor_map
        and team_age is not None
    )

    team_anchor = age_anchor_map.get(team_age, 1.0) if cross_age_active else 1.0

    def _get_opp_strength(row):
        opp_id = row["opp_id"]

        # First try same-cohort strength map
        strength = strength_map.get(opp_id)

        # Fall back to global map for cross-age opponents
        if strength is None and global_strength_map:
            strength = global_strength_map.get(str(opp_id))

        # Final fallback: unranked baseline
        if strength is None:
            strength = cfg.UNRANKED_SOS_BASE

        # Apply cross-age anchor scaling if enabled
        if cross_age_active:
            try:
                opp_age = int(float(row.get("opp_age", team_age)))
            except (ValueError, TypeError):
                opp_age = team_age

            if opp_age != team_age:
                opp_anchor = age_anchor_map.get(opp_age, 1.0)
                anchor_ratio = opp_anchor / team_anchor
                strength = strength * anchor_ratio

        return max(strength, cfg.UNRANKED_SOS_BASE)

    g["opp_strength"] = g.apply(_get_opp_strength, axis=1)

    # Calculate adjustment multipliers
    # Offense: score against strong opponent = more credit
    g["off_multiplier"] = (g["opp_strength"] / baseline).clip(
        cfg.OPPONENT_ADJUST_CLIP_MIN, cfg.OPPONENT_ADJUST_CLIP_MAX
    )

    # Defense: allow goals to strong opponent = less penalty
    g["def_multiplier"] = (baseline / g["opp_strength"]).clip(
        cfg.OPPONENT_ADJUST_CLIP_MIN, cfg.OPPONENT_ADJUST_CLIP_MAX
    )

    # Apply adjustments
    g["gf_adjusted"] = g["gf"] * g["off_multiplier"]
    g["ga_adjusted"] = g["ga"] * g["def_multiplier"]

    return g
```

- [ ] **Step 2: Run baseline test to confirm same-age behavior is unchanged**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py::TestSameAgeBaseline -v`
Expected: PASS (same-age games have no anchor ratio scaling)

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add src/etl/v53e.py
git commit -m "feat: add age-anchor scaling to _adjust_for_opponent_strength

When CROSS_AGE_OPPONENT_ADJUST_ENABLED is true, cross-age opponents get
their abs_strength scaled by opp_anchor/team_anchor before computing the
adjustment multiplier. A median U13 opponent now registers as harder than
a median U12 opponent, properly crediting offensive output against older
competition."
```

---

### Task 5: Wire up the new parameters at the call site in `compute_rankings`

**Files:**
- Modify: `src/etl/v53e.py` (lines 1068-1084, the opponent adjustment call site)

- [ ] **Step 1: Import AGE_TO_ANCHOR and update the call site**

First, add the import at the top of the file (with the other imports from rankings):

```python
from src.rankings.constants import AGE_TO_ANCHOR
```

Then update the opponent adjustment call site (around line 1084). Replace:

```python
            # Adjust games for opponent strength
            g_adjusted = _adjust_for_opponent_strength(g, strength_map, cfg, baseline=baseline)
```

With:

```python
            # Determine team age for cross-age scaling
            # All games in this cohort have the same team age
            cohort_age = None
            if "age" in g.columns and not g.empty:
                try:
                    cohort_age = int(float(g["age"].iloc[0]))
                except (ValueError, TypeError):
                    cohort_age = None

            # Adjust games for opponent strength (with cross-age scaling in Pass 2)
            g_adjusted = _adjust_for_opponent_strength(
                g,
                strength_map,
                cfg,
                baseline=baseline,
                global_strength_map=global_strength_map,
                age_anchor_map=AGE_TO_ANCHOR,
                team_age=cohort_age,
            )
```

- [ ] **Step 2: Run the cross-age test to see if it now passes**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py::TestCrossAgeAdjustment::test_cross_age_team_off_norm_not_suppressed -v`
Expected: PASS — the gap should now be < 0.15

- [ ] **Step 3: Run all tests to confirm no regressions**

Run: `cd C:/PitchRank && python -m pytest tests/unit/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank
git add src/etl/v53e.py
git commit -m "feat: wire cross-age opponent adjustment into compute_rankings

Pass global_strength_map, AGE_TO_ANCHOR, and cohort age to the opponent
adjustment function. In Pass 2, cross-age opponents now get age-scaled
strength values, fixing the systematic offense suppression for teams
that play up in age."
```

---

### Task 6: Add edge case tests

**Files:**
- Modify: `tests/unit/test_cross_age_opponent_adjustment.py`

- [ ] **Step 1: Add test for toggle-off behavior**

Append to `tests/unit/test_cross_age_opponent_adjustment.py`:

```python
class TestCrossAgeToggle:
    """Test that the cross-age adjustment can be toggled off."""

    def test_disabled_flag_preserves_old_behavior(self):
        """When CROSS_AGE_OPPONENT_ADJUST_ENABLED is False, the cross-age
        team should have a larger off_norm gap (old behavior)."""
        cfg = V53EConfig()
        cfg.CROSS_AGE_OPPONENT_ADJUST_ENABLED = False
        games = _build_cross_age_league()

        # Build global_strength_map from U13 cohort
        u13_games = games[
            (games["age"] == "13") & (games["gender"] == "male")
        ].copy()
        if not u13_games.empty:
            u13_result = compute_rankings(
                u13_games, today=pd.Timestamp("2026-03-01"), cfg=cfg
            )
            u13_teams = u13_result["teams"]
            global_strength_map = dict(
                zip(u13_teams["team_id"].astype(str), u13_teams["abs_strength"].astype(float))
            )
        else:
            global_strength_map = {}

        u12_games = games[
            (games["age"] == "12") & (games["gender"] == "male")
        ].copy()
        result = compute_rankings(
            u12_games,
            today=pd.Timestamp("2026-03-01"),
            cfg=cfg,
            global_strength_map=global_strength_map,
        )
        teams = result["teams"]

        same = teams[teams["team_id"] == "team_same"].iloc[0]
        cross = teams[teams["team_id"] == "team_cross"].iloc[0]

        gap = same["off_norm"] - cross["off_norm"]
        # With the flag off, the old bias should remain — gap should be larger
        assert gap > 0.10, (
            f"With cross-age adjustment disabled, gap should be larger than 0.10, "
            f"but got {gap:.3f}"
        )


class TestCrossAgeEdgeCases:
    """Edge cases for cross-age opponent adjustment."""

    def test_no_global_strength_map_falls_back_gracefully(self):
        """When global_strength_map is None (Pass 1), cross-age opponents
        should fall back to UNRANKED_SOS_BASE without error."""
        cfg = V53EConfig()
        games = _build_cross_age_league()
        u12_games = games[
            (games["age"] == "12") & (games["gender"] == "male")
        ].copy()

        # Pass 1: no global_strength_map
        result = compute_rankings(
            u12_games,
            today=pd.Timestamp("2026-03-01"),
            cfg=cfg,
            global_strength_map=None,
        )
        teams = result["teams"]
        # Should complete without error; team_cross should exist
        assert "team_cross" in teams["team_id"].values

    def test_playing_down_reduces_credit(self):
        """A U13 team playing U12 opponents should NOT get inflated off_norm.
        The anchor ratio should reduce credit for scoring against younger teams."""
        today = pd.Timestamp("2026-03-01")
        rows = []
        gid = 0

        u13_fillers = [f"u13_fill_{i}" for i in range(8)]
        u12_fillers = [f"u12_fill_{i}" for i in range(8)]

        # team_down: U13 team that plays 6 games vs U12 (easy 4-0 wins)
        # and 2 games vs U13 (2-1 wins)
        for i in range(6):
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game_pair(str(gid), date, "team_down", u12_fillers[i], 4, 0,
                                        age="13", gender="male",
                                        opp_age="12", opp_gender="male"))
        for i in range(2):
            gid += 1
            date = today - pd.Timedelta(days=gid)
            rows.extend(_make_game_pair(str(gid), date, "team_down", u13_fillers[i], 2, 1,
                                        age="13", gender="male"))

        # team_honest: U13 team that plays 8 games vs U13 (2-1 wins)
        for i in range(8):
            gid += 1
            date = today - pd.Timedelta(days=gid)
            opp = u13_fillers[i] if i < 8 else f"u13_extra_{i}"
            rows.extend(_make_game_pair(str(gid), date, "team_honest", u13_fillers[i % 8], 2, 1,
                                        age="13", gender="male"))

        # U13 fillers play each other
        for i, home in enumerate(u13_fillers):
            for away in u13_fillers[i + 1:]:
                gid += 1
                date = today - pd.Timedelta(days=gid)
                rows.extend(_make_game_pair(str(gid), date, home, away, 2, 1,
                                            age="13", gender="male"))

        # U12 fillers play each other (for global_strength_map)
        for i, home in enumerate(u12_fillers):
            for away in u12_fillers[i + 1:]:
                gid += 1
                date = today - pd.Timedelta(days=gid)
                rows.extend(_make_game_pair(str(gid), date, home, away, 2, 1,
                                            age="12", gender="male"))

        games = pd.DataFrame(rows)

        # Build global_strength_map from U12 cohort
        u12_games = games[(games["age"] == "12") & (games["gender"] == "male")].copy()
        u12_result = compute_rankings(u12_games, today=today, cfg=V53EConfig())
        global_strength_map = dict(
            zip(u12_result["teams"]["team_id"].astype(str),
                u12_result["teams"]["abs_strength"].astype(float))
        )

        # Run U13 cohort with global map
        u13_games = games[(games["age"] == "13") & (games["gender"] == "male")].copy()
        result = compute_rankings(
            u13_games, today=today, cfg=V53EConfig(),
            global_strength_map=global_strength_map,
        )
        teams = result["teams"]

        down = teams[teams["team_id"] == "team_down"].iloc[0]
        honest = teams[teams["team_id"] == "team_honest"].iloc[0]

        # team_down's 4-0 wins against U12 should get LESS credit (anchor ratio < 1)
        # So team_down should NOT have dramatically higher off_norm than team_honest
        gap = down["off_norm"] - honest["off_norm"]
        assert gap < 0.30, (
            f"Playing-down team should not get excessive off_norm boost: "
            f"team_down={down['off_norm']:.3f}, team_honest={honest['off_norm']:.3f}, gap={gap:.3f}"
        )
```

- [ ] **Step 2: Run all new tests**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add tests/unit/test_cross_age_opponent_adjustment.py
git commit -m "test: add toggle-off and edge case tests for cross-age adjustment

Covers: disabled flag preserves old behavior, graceful fallback when
global_strength_map is None (Pass 1), and playing-down anchor scaling
reduces credit for scoring against younger opponents."
```

---

### Task 7: Add diagnostic logging for cross-age adjustments

**Files:**
- Modify: `src/etl/v53e.py` (after the opponent adjustment call, around line 1132)

- [ ] **Step 1: Add logging after opponent adjustment**

After the existing diagnostic logging (line 1132-1140), add cross-age specific diagnostics. Insert after the `logger.info("✅ Opponent-adjusted offense/defense applied successfully")` line:

```python
            # Diagnostic: cross-age opponent adjustment impact
            if cfg.CROSS_AGE_OPPONENT_ADJUST_ENABLED and global_strength_map:
                cross_age_games = g_adjusted[g_adjusted["opp_age"].astype(str) != g_adjusted["age"].astype(str)]
                if not cross_age_games.empty:
                    avg_multiplier_cross = cross_age_games["off_multiplier"].mean()
                    avg_multiplier_same = g_adjusted[
                        g_adjusted["opp_age"].astype(str) == g_adjusted["age"].astype(str)
                    ]["off_multiplier"].mean()
                    logger.info(
                        f"📊 Cross-age opponent adjustment: "
                        f"cross_age_games={len(cross_age_games)}, "
                        f"avg_off_mult_cross={avg_multiplier_cross:.3f}, "
                        f"avg_off_mult_same={avg_multiplier_same:.3f}"
                    )
```

- [ ] **Step 2: Run all tests**

Run: `cd C:/PitchRank && python -m pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add src/etl/v53e.py
git commit -m "feat: add diagnostic logging for cross-age opponent adjustment

Logs average off_multiplier for cross-age vs same-age games when the
cross-age adjustment is active. Helps monitor the impact during rollout."
```

---

### Task 8: Create live data validation script

**Files:**
- Create: `scripts/validate_cross_age_fix.py`

- [ ] **Step 1: Write the validation script**

This script runs the ranking engine on live data with the fix enabled vs disabled, comparing Phoenix United Elite's metrics.

```python
"""Validate cross-age opponent adjustment fix using live data.

Runs the ranking engine twice for the U12M cohort:
1. With CROSS_AGE_OPPONENT_ADJUST_ENABLED = False (old behavior)
2. With CROSS_AGE_OPPONENT_ADJUST_ENABLED = True (new behavior)

Compares Phoenix United Elite (691eb36d-95b2-4a08-bd59-13c1b0e830bb)
metrics between the two runs.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from supabase import create_client

from config.settings import SUPABASE_URL, SUPABASE_KEY, V53E_CONFIG, ML_CONFIG
from src.etl.v53e import V53EConfig, compute_rankings
from src.rankings.data_adapter import fetch_games_for_rankings
from src.rankings.constants import AGE_TO_ANCHOR

PHOENIX_ID = "691eb36d-95b2-4a08-bd59-13c1b0e830bb"


async def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Fetching games...")
    games_df = await fetch_games_for_rankings(supabase, lookback_days=365)

    # Filter to U12M and U13M cohorts
    u12m_games = games_df[
        (games_df["age"].astype(str) == "12") & (games_df["gender"].str.lower() == "male")
    ].copy()
    u13m_games = games_df[
        (games_df["age"].astype(str) == "13") & (games_df["gender"].str.lower() == "male")
    ].copy()

    print(f"U12M games: {len(u12m_games)}, U13M games: {len(u13m_games)}")

    # Build global_strength_map from U13M cohort (Pass 1 simulation)
    cfg = V53EConfig(**V53E_CONFIG)
    u13_result = compute_rankings(u13m_games, cfg=cfg)
    global_strength_map = dict(
        zip(
            u13_result["teams"]["team_id"].astype(str),
            u13_result["teams"]["abs_strength"].astype(float),
        )
    )

    # Run 1: Old behavior (cross-age adjustment disabled)
    cfg_old = V53EConfig(**V53E_CONFIG)
    cfg_old.CROSS_AGE_OPPONENT_ADJUST_ENABLED = False
    result_old = compute_rankings(
        u12m_games, cfg=cfg_old, global_strength_map=global_strength_map
    )

    # Run 2: New behavior (cross-age adjustment enabled)
    cfg_new = V53EConfig(**V53E_CONFIG)
    cfg_new.CROSS_AGE_OPPONENT_ADJUST_ENABLED = True
    result_new = compute_rankings(
        u12m_games, cfg=cfg_new, global_strength_map=global_strength_map
    )

    # Compare Phoenix
    teams_old = result_old["teams"]
    teams_new = result_new["teams"]

    phoenix_old = teams_old[teams_old["team_id"] == PHOENIX_ID]
    phoenix_new = teams_new[teams_new["team_id"] == PHOENIX_ID]

    if phoenix_old.empty or phoenix_new.empty:
        print(f"ERROR: Phoenix not found in results. Check team_id {PHOENIX_ID}")
        return

    po = phoenix_old.iloc[0]
    pn = phoenix_new.iloc[0]

    print("\n" + "=" * 70)
    print("PHOENIX UNITED ELITE (U12M) — BEFORE vs AFTER CROSS-AGE FIX")
    print("=" * 70)
    metrics = ["off_raw", "off_norm", "def_norm", "sos_norm", "powerscore_adj", "abs_strength"]
    print(f"{'Metric':<20} {'Before':>10} {'After':>10} {'Delta':>10}")
    print("-" * 50)
    for m in metrics:
        old_val = po.get(m, float("nan"))
        new_val = pn.get(m, float("nan"))
        delta = new_val - old_val if pd.notna(old_val) and pd.notna(new_val) else float("nan")
        print(f"{m:<20} {old_val:>10.4f} {new_val:>10.4f} {delta:>+10.4f}")

    # Show top 10 AZ U12M teams in both scenarios
    # (Would need state_code from teams table — skip for now, focus on Phoenix)

    print("\n" + "=" * 70)
    print("COHORT-WIDE IMPACT")
    print("=" * 70)
    off_norm_shift = teams_new["off_norm"].mean() - teams_old["off_norm"].mean()
    print(f"Mean off_norm shift: {off_norm_shift:+.4f}")
    print(f"Std off_norm old: {teams_old['off_norm'].std():.4f}, new: {teams_new['off_norm'].std():.4f}")

    # Identify teams with largest positive shift (most helped by fix)
    merged = teams_old[["team_id", "off_norm"]].merge(
        teams_new[["team_id", "off_norm"]], on="team_id", suffixes=("_old", "_new")
    )
    merged["off_norm_delta"] = merged["off_norm_new"] - merged["off_norm_old"]
    top_helped = merged.nlargest(10, "off_norm_delta")
    print(f"\nTop 10 teams most helped (off_norm increase):")
    for _, row in top_helped.iterrows():
        print(f"  {row['team_id']}: {row['off_norm_old']:.3f} -> {row['off_norm_new']:.3f} ({row['off_norm_delta']:+.3f})")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the validation script**

Run: `cd C:/PitchRank && python scripts/validate_cross_age_fix.py`

Expected: Phoenix's off_norm should increase significantly (0.318 -> somewhere in the 0.50-0.80 range). If the script has import issues, debug and fix — the exact imports may need adjustment based on the actual module structure.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add scripts/validate_cross_age_fix.py
git commit -m "feat: add live data validation script for cross-age fix

Runs the U12M ranking engine with and without cross-age adjustment,
comparing Phoenix United Elite metrics. Also reports cohort-wide
impact and most-helped teams."
```

---

### Task 9: Run full test suite and validate

**Files:** None (validation only)

- [ ] **Step 1: Run all unit tests**

Run: `cd C:/PitchRank && python -m pytest tests/unit/ -v`
Expected: All tests pass

- [ ] **Step 2: Run the validation script and review Phoenix results**

Run: `cd C:/PitchRank && python scripts/validate_cross_age_fix.py`

Review the output. Key success criteria:
- Phoenix off_norm increases from 0.318 to at least 0.50
- Phoenix powerscore_adj increases (closer to 0.84+ range)
- Cohort-wide mean off_norm shift is near zero (this is a redistribution, not inflation)
- No other team is dramatically hurt by the change

- [ ] **Step 3: If validation passes, create a final commit**

```bash
cd C:/PitchRank
git add -A
git commit -m "feat: cross-age opponent adjustment — complete implementation

Fixes systematic off_norm suppression for teams playing older opponents.
Layer 9 opponent adjustment now scales abs_strength by the age anchor
ratio (opp_anchor/team_anchor) for cross-age games in Pass 2.

Key changes:
- _adjust_for_opponent_strength accepts global_strength_map + age anchors
- compute_rankings passes these in the opponent adjustment call
- New config toggle: CROSS_AGE_OPPONENT_ADJUST_ENABLED (default: True)
- Diagnostic logging for cross-age adjustment impact
- Full test coverage including edge cases and toggle-off behavior
- Live validation script for Phoenix United Elite case study"
```
