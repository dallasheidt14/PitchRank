# SOS Cross-Age Anchor Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply age-anchor scaling to cross-age opponent strength lookups in the SOS calculation so that teams playing older opponents get proper schedule-strength credit.

**Architecture:** Modify two closure functions (`get_opponent_strength` and `get_opponent_sos`) inside `compute_rankings` to apply `opp_anchor / team_anchor` scaling when resolving opponents through the `global_strength_map` fallback. Same-cohort lookups remain unchanged. New independent config toggle `CROSS_AGE_SOS_ADJUST_ENABLED`.

**Tech Stack:** Python 3.11, pandas, numpy, pytest

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/etl/v53e.py` | Modify | Config field, opp_age_map, two closure modifications |
| `tests/unit/test_cross_age_opponent_adjustment.py` | Modify | Add SOS-specific tests |

---

### Task 1: Add config toggle and write failing SOS test

**Files:**
- Modify: `src/etl/v53e.py` (V53EConfig, line 121)
- Modify: `tests/unit/test_cross_age_opponent_adjustment.py`

- [ ] **Step 1: Add config field**

In `src/etl/v53e.py`, after line 121 (`CROSS_AGE_OPPONENT_ADJUST_ENABLED`), add:

```python
    CROSS_AGE_SOS_ADJUST_ENABLED: bool = True  # Scale cross-age opponent strength in SOS by age anchor ratio
```

- [ ] **Step 2: Write the failing SOS cross-age test**

Append to `tests/unit/test_cross_age_opponent_adjustment.py`:

```python
class TestSOSCrossAgeScaling:
    """Test that SOS properly credits cross-age opponents via anchor scaling."""

    def test_cross_age_team_gets_higher_sos_with_scaling(self):
        """team_cross plays U13 opponents (via global_strength_map). With SOS
        cross-age scaling enabled, those opponents should be valued higher
        than their raw abs_strength, boosting team_cross's SOS.

        Compare SOS between team_same (all U12 opponents) and team_cross
        (all U13 opponents). Without the fix, team_cross gets lower SOS
        because U13 opponents are not in the U12 cohort's base_strength_map
        and fall back to global_strength_map at raw (unscaled) values.
        With the fix, the anchor ratio (U13/U12 = 1.136) boosts those
        opponents' strength, raising team_cross's SOS.
        """
        cfg = V53EConfig()
        games = _build_cross_age_league()

        # Build global_strength_map from U13 cohort
        u13_games = games[
            (games["age"] == "13") & (games["gender"] == "male")
        ].copy()
        u13_result = compute_rankings(u13_games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        global_strength_map = dict(
            zip(u13_result["teams"]["team_id"].astype(str),
                u13_result["teams"]["abs_strength"].astype(float))
        )

        # Run U12 cohort with global_strength_map
        u12_games = games[
            (games["age"] == "12") & (games["gender"] == "male")
        ].copy()
        result = compute_rankings(
            u12_games, today=pd.Timestamp("2026-03-01"), cfg=cfg,
            global_strength_map=global_strength_map,
        )
        teams = result["teams"]

        same = teams[teams["team_id"] == "team_same"].iloc[0]
        cross = teams[teams["team_id"] == "team_cross"].iloc[0]

        # team_cross plays U13 opponents who should get anchor-scaled strength
        # in SOS. This should give team_cross a competitive SOS.
        # Without the fix, cross-age opponents fall back to unscaled global values.
        # We check that the SOS gap is not too large (< 0.20).
        sos_gap = same["sos_norm"] - cross["sos_norm"]
        assert sos_gap < 0.20, (
            f"SOS gap too large: team_same sos_norm={same['sos_norm']:.3f}, "
            f"team_cross sos_norm={cross['sos_norm']:.3f}, gap={sos_gap:.3f}. "
            f"Cross-age SOS scaling should credit U13 opponents more."
        )
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py::TestSOSCrossAgeScaling::test_cross_age_team_gets_higher_sos_with_scaling -v`
Expected: FAIL — the SOS gap will be > 0.20 because no anchor scaling is applied yet

- [ ] **Step 4: Commit**

```bash
cd C:/PitchRank
git add src/etl/v53e.py tests/unit/test_cross_age_opponent_adjustment.py
git commit -m "test: add failing SOS cross-age scaling test + config toggle"
```

---

### Task 2: Implement SOS cross-age anchor scaling

**Files:**
- Modify: `src/etl/v53e.py` (SOS section, around lines 1369-1392)

- [ ] **Step 1: Add opp_age_map and scaling setup before get_opponent_strength**

Find the comment block (around line 1369):
```python
    # Use base strength for initial SOS calculation (Pass 1)
    # This represents how good opponents are at OFF/DEF
    # For cross-age/cross-gender opponents, use global_strength_map if available
```

Replace everything from that comment through the `get_opponent_strength` closure (through line 1391) with:

```python
    # Use base strength for initial SOS calculation (Pass 1)
    # This represents how good opponents are at OFF/DEF
    # For cross-age/cross-gender opponents, use global_strength_map if available

    # Build opp_age_map for cross-age SOS anchor scaling
    opp_age_map = {}
    if "opp_age" in g_sos.columns:
        for opp_id, opp_age in zip(g_sos["opp_id"], g_sos["opp_age"]):
            if opp_id not in opp_age_map:
                try:
                    opp_age_map[opp_id] = int(float(opp_age))
                except (ValueError, TypeError):
                    pass

    # Parse cohort age for anchor ratio computation
    sos_cohort_age = None
    if "age" in g_sos.columns and not g_sos.empty:
        try:
            sos_cohort_age = int(float(g_sos["age"].iloc[0]))
        except (ValueError, TypeError):
            sos_cohort_age = None

    age_anchor_map = _get_age_to_anchor()
    sos_cross_age_active = (
        cfg.CROSS_AGE_SOS_ADJUST_ENABLED
        and global_strength_map
        and sos_cohort_age is not None
    )
    sos_team_anchor = age_anchor_map.get(sos_cohort_age, 1.0) if sos_cross_age_active else 1.0

    # Diagnostic: track cross-age lookups
    cross_age_found = 0
    cross_age_missing = 0

    def get_opponent_strength(opp_id):
        nonlocal cross_age_found, cross_age_missing
        # Same-cohort: use raw value, no scaling
        if opp_id in base_strength_map:
            return base_strength_map[opp_id]
        # Cross-cohort fallback: global map + anchor scaling
        opp_id_str = str(opp_id)
        if global_strength_map and opp_id_str in global_strength_map:
            cross_age_found += 1
            strength = global_strength_map[opp_id_str]
            if sos_cross_age_active:
                opp_age = opp_age_map.get(opp_id)
                if opp_age is not None and opp_age != sos_cohort_age:
                    opp_anchor = age_anchor_map.get(opp_age, 1.0)
                    strength = max(strength * (opp_anchor / sos_team_anchor), cfg.UNRANKED_SOS_BASE)
            return strength
        # Unknown opponent
        cross_age_missing += 1
        return cfg.UNRANKED_SOS_BASE
```

- [ ] **Step 2: Update get_opponent_sos closure for transitive SOS**

Find the `get_opponent_sos` closure (around line 1469). Replace:

```python
        def get_opponent_sos(opp_id):
            if opp_id in opp_sos_map:
                return opp_sos_map[opp_id]
            # For cross-age opponents not in SOS map, use their global strength as proxy
            # global_strength_map uses string keys, so convert opp_id to string
            opp_id_str = str(opp_id)
            if global_strength_map and opp_id_str in global_strength_map:
                return global_strength_map[opp_id_str]
            return cfg.UNRANKED_SOS_BASE
```

With:

```python
        def get_opponent_sos(opp_id):
            # Same-cohort: use raw SOS value, no scaling
            if opp_id in opp_sos_map:
                return opp_sos_map[opp_id]
            # Cross-cohort fallback: global strength + anchor scaling
            opp_id_str = str(opp_id)
            if global_strength_map and opp_id_str in global_strength_map:
                strength = global_strength_map[opp_id_str]
                if sos_cross_age_active:
                    opp_age = opp_age_map.get(opp_id)
                    if opp_age is not None and opp_age != sos_cohort_age:
                        opp_anchor = age_anchor_map.get(opp_age, 1.0)
                        strength = max(strength * (opp_anchor / sos_team_anchor), cfg.UNRANKED_SOS_BASE)
                return strength
            return cfg.UNRANKED_SOS_BASE
```

- [ ] **Step 3: Run the SOS cross-age test**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py::TestSOSCrossAgeScaling -v`
Expected: PASS

- [ ] **Step 4: Run all tests**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py -v`
Expected: All 8 tests pass (7 existing + 1 new)

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank
git add src/etl/v53e.py
git commit -m "feat: apply cross-age anchor scaling to SOS opponent lookups

When CROSS_AGE_SOS_ADJUST_ENABLED is true and an opponent is resolved
via global_strength_map (cross-cohort fallback), scale their strength
by opp_anchor/team_anchor. Same-cohort lookups unchanged."
```

---

### Task 3: Add SOS toggle-off test and no-cross-age guardrail test

**Files:**
- Modify: `tests/unit/test_cross_age_opponent_adjustment.py`

- [ ] **Step 1: Add toggle-off and guardrail tests**

Append to `tests/unit/test_cross_age_opponent_adjustment.py`:

```python
    def test_sos_toggle_off_preserves_old_behavior(self):
        """When CROSS_AGE_SOS_ADJUST_ENABLED is False, SOS should not
        benefit from anchor scaling on cross-age opponents."""
        cfg = V53EConfig()
        cfg.CROSS_AGE_SOS_ADJUST_ENABLED = False
        games = _build_cross_age_league()

        u13_games = games[
            (games["age"] == "13") & (games["gender"] == "male")
        ].copy()
        u13_result = compute_rankings(u13_games, today=pd.Timestamp("2026-03-01"), cfg=cfg)
        global_strength_map = dict(
            zip(u13_result["teams"]["team_id"].astype(str),
                u13_result["teams"]["abs_strength"].astype(float))
        )

        u12_games = games[
            (games["age"] == "12") & (games["gender"] == "male")
        ].copy()

        # Run with SOS scaling OFF
        result_off = compute_rankings(
            u12_games, today=pd.Timestamp("2026-03-01"), cfg=cfg,
            global_strength_map=global_strength_map,
        )

        # Run with SOS scaling ON
        cfg_on = V53EConfig()
        cfg_on.CROSS_AGE_SOS_ADJUST_ENABLED = True
        result_on = compute_rankings(
            u12_games, today=pd.Timestamp("2026-03-01"), cfg=cfg_on,
            global_strength_map=global_strength_map,
        )

        cross_off = result_off["teams"][result_off["teams"]["team_id"] == "team_cross"].iloc[0]
        cross_on = result_on["teams"][result_on["teams"]["team_id"] == "team_cross"].iloc[0]

        # With scaling ON, team_cross should get higher SOS (or equal)
        assert cross_on["sos_norm"] >= cross_off["sos_norm"], (
            f"SOS scaling ON should give >= SOS than OFF for cross-age team. "
            f"ON: {cross_on['sos_norm']:.3f}, OFF: {cross_off['sos_norm']:.3f}"
        )

    def test_no_cross_age_cohort_identical_with_toggle(self):
        """For a cohort with NO cross-age games, toggling
        CROSS_AGE_SOS_ADJUST_ENABLED on/off should produce identical SOS.
        This is the non-regression guardrail."""
        games = _build_same_age_league()

        # Run with SOS scaling OFF
        cfg_off = V53EConfig()
        cfg_off.CROSS_AGE_SOS_ADJUST_ENABLED = False
        result_off = compute_rankings(
            games, today=pd.Timestamp("2026-03-01"), cfg=cfg_off,
            global_strength_map={"fake_team": 0.5},
        )

        # Run with SOS scaling ON
        cfg_on = V53EConfig()
        cfg_on.CROSS_AGE_SOS_ADJUST_ENABLED = True
        result_on = compute_rankings(
            games, today=pd.Timestamp("2026-03-01"), cfg=cfg_on,
            global_strength_map={"fake_team": 0.5},
        )

        teams_off = result_off["teams"].sort_values("team_id").reset_index(drop=True)
        teams_on = result_on["teams"].sort_values("team_id").reset_index(drop=True)

        # Every team's sos_norm should be identical
        for _, (row_off, row_on) in enumerate(zip(
            teams_off.itertuples(), teams_on.itertuples()
        )):
            assert abs(row_off.sos_norm - row_on.sos_norm) < 0.001, (
                f"SOS changed for {row_off.team_id} in a same-age cohort: "
                f"OFF={row_off.sos_norm:.4f}, ON={row_on.sos_norm:.4f}"
            )
```

- [ ] **Step 2: Run all tests**

Run: `cd C:/PitchRank && python -m pytest tests/unit/test_cross_age_opponent_adjustment.py -v`
Expected: All 10 tests pass

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank
git add tests/unit/test_cross_age_opponent_adjustment.py
git commit -m "test: add SOS toggle-off and no-cross-age guardrail tests

Toggle test confirms CROSS_AGE_SOS_ADJUST_ENABLED=False preserves old
behavior. Guardrail test confirms that a cohort with zero cross-age
games produces identical SOS regardless of toggle state."
```

---

### Task 4: Run full test suite and code review

**Files:** None (validation only)

- [ ] **Step 1: Run full unit test suite**

Run: `cd C:/PitchRank && python -m pytest tests/unit/ -v`
Expected: All tests pass (340+)

- [ ] **Step 2: Code review**

Dispatch the code-reviewer agent to review the SOS changes in `src/etl/v53e.py`. Focus on:
- Scaling only applies on global fallback path (not same-cohort)
- `opp_age_map` construction is correct
- `sos_cross_age_active` condition matches spec
- No scoping issues with closures
- No interaction with Power-SOS iteration loop that could cause amplification

- [ ] **Step 3: Commit and push**

```bash
cd C:/PitchRank
git push origin main
```

---

### Task 5: Production validation

**Files:** None (validation only)

- [ ] **Step 1: Trigger ranking workflow**

```bash
cd C:/PitchRank && gh workflow run "Calculate Rankings" --ref main
```

- [ ] **Step 2: After completion, validate SE Black**

Query rankings_full for team_id `05e9e6aa-fba6-40c2-a995-25826d5c3cb8`:
- sos_norm should increase from 0.784 toward 0.85+
- powerscore_ml should increase
- AZ rank should improve from #6

- [ ] **Step 3: Validate cohort stability**

For each cohort, confirm mean sos_norm is ~0.500 (redistributive).

- [ ] **Step 4: Validate Phoenix still correct**

Query rankings_full for team_id `691eb36d-95b2-4a08-bd59-13c1b0e830bb`:
- off_norm should still be ~0.91
- SOS may also improve (Phoenix has cross-age schedule too)
- Should remain #1 in AZ U12M
