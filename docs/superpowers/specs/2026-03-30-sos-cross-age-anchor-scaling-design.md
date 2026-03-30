# SOS Cross-Age Anchor Scaling

**Date:** 2026-03-30
**Status:** Design approved, ready for implementation planning
**Prerequisite:** Cross-age offense fix (completed 2026-03-29)

---

## Problem

Teams that play a significant portion of their schedule against older opponents get systematically suppressed SOS because the SOS code path uses raw `abs_strength` from `global_strength_map` without age-anchor scaling. A mid-tier U15 opponent registers as abs_strength ~0.50 in SOS, even though beating them as a U14 team is a quality win.

**Case study:** Southeast 2012 Black (U14M, AZ) has the highest off_norm (0.997) and def_norm (1.000) among AZ top 6, but ranks #6 because sos_norm (0.784) is the weakest — driven by 59% cross-age schedule where U15 opponents are undervalued.

## Fix

Apply age-anchor scaling to cross-age opponent strength lookups in the SOS calculation, mirroring the offense fix. When a cross-age opponent is resolved through the global map fallback, scale their strength by `opp_anchor / team_anchor`.

## Scaling rule

- If opponent is found in **same-cohort `base_strength_map`** → use raw value, no scaling
- If opponent is resolved via **cross-cohort `global_strength_map` fallback** → apply `opp_anchor / team_anchor`
- Same-age / same-cohort paths remain completely unchanged

This means anchor scaling triggers on the **lookup source** (global fallback), not on age comparison. An opponent that happens to be in the same-cohort map — regardless of their actual age — gets no scaling. Only the global fallback path scales.

## Config

New independent toggle:

```python
CROSS_AGE_SOS_ADJUST_ENABLED: bool = True
```

This is **separate** from `CROSS_AGE_OPPONENT_ADJUST_ENABLED` (offense path). Reason: SOS has more downstream interactions (Power-SOS co-calculation, PageRank dampening, connected component normalization, SCF), so offense and SOS scaling must be independently testable and reversible.

## Anchor ratio

Same as the offense fix: `opp_anchor / team_anchor` using `AGE_TO_ANCHOR` mapping.

Examples:
- U14 team vs U15 opponent: 0.775 / 0.700 = 1.107x
- U12 team vs U13 opponent: 0.625 / 0.550 = 1.136x
- U13 team vs U12 opponent (playing down): 0.550 / 0.625 = 0.880x

## Code changes

All changes in `src/etl/v53e.py`.

### 1. Add config field

Add `CROSS_AGE_SOS_ADJUST_ENABLED: bool = True` to `V53EConfig` after the existing `CROSS_AGE_OPPONENT_ADJUST_ENABLED` field.

### 2. Build `opp_age_map` before SOS lookups

Before the `get_opponent_strength` closure (around line 1377), build a dict mapping `opp_id → int(opp_age)` from the `g_sos` DataFrame. This provides the opponent's age for anchor ratio computation without changing the `.map()` lookup pattern.

```python
opp_age_map = {}
if "opp_age" in g_sos.columns:
    for opp_id, opp_age in zip(g_sos["opp_id"], g_sos["opp_age"]):
        if opp_id not in opp_age_map:
            try:
                opp_age_map[opp_id] = int(float(opp_age))
            except (ValueError, TypeError):
                pass
```

### 3. Modify `get_opponent_strength` closure

When the opponent is resolved via `global_strength_map` (the cross-cohort fallback) and `CROSS_AGE_SOS_ADJUST_ENABLED` is True, apply anchor scaling before returning.

The key constraint: scaling applies **only** on the global fallback path, not on same-cohort lookups.

```python
def get_opponent_strength(opp_id):
    nonlocal cross_age_found, cross_age_missing
    # Same-cohort: use raw value, no scaling
    if opp_id in base_strength_map:
        return base_strength_map[opp_id]
    # Cross-cohort fallback: global map + optional anchor scaling
    opp_id_str = str(opp_id)
    if global_strength_map and opp_id_str in global_strength_map:
        cross_age_found += 1
        strength = global_strength_map[opp_id_str]
        # Apply anchor scaling if enabled
        if sos_cross_age_active:
            opp_age = opp_age_map.get(opp_id)
            if opp_age is not None and opp_age != cohort_age:
                opp_anchor = age_anchor_map.get(opp_age, 1.0)
                strength = max(strength * (opp_anchor / team_anchor), cfg.UNRANKED_SOS_BASE)
        return strength
    cross_age_missing += 1
    return cfg.UNRANKED_SOS_BASE
```

Where `sos_cross_age_active`, `cohort_age`, `team_anchor`, `age_anchor_map` are set up before the closure:

```python
age_anchor_map = _get_age_to_anchor()
sos_cross_age_active = (
    cfg.CROSS_AGE_SOS_ADJUST_ENABLED
    and global_strength_map
    and cohort_age is not None
)
team_anchor = age_anchor_map.get(cohort_age, 1.0) if sos_cross_age_active else 1.0
```

### 4. Modify `get_opponent_sos` closure

Same pattern for the transitive SOS iteration fallback (around line 1469). When falling back to `global_strength_map`, apply the same anchor scaling.

### 5. Diagnostic logging

After SOS computation, log the average `opp_strength` for cross-age vs same-age games when the feature is active.

## Files

| File | Action | What |
|---|---|---|
| `src/etl/v53e.py` | Modify | Config field, opp_age_map, two closure modifications, logging |
| `tests/unit/test_cross_age_opponent_adjustment.py` | Modify | Add SOS-specific tests |
| `scripts/se_black_diagnostic.py` | Existing | Use for before/after validation |

## Tests

1. **SOS cross-age scaling active test** — build a cross-age league, verify that a team playing older opponents gets higher SOS with the fix than without
2. **SOS toggle-off test** — verify `CROSS_AGE_SOS_ADJUST_ENABLED = False` preserves old behavior
3. **Same-cohort unchanged test** — verify that teams with no cross-age games get identical SOS with and without the flag
4. **Pass 2 SOS test** — verify the fix works through the `pre_sos_state` path (since SOS runs after the pre_sos_state restore, this should work naturally, but verify)

## Expected impact

- SE Black sos_norm should increase from 0.784 toward 0.85+
- Cohort mean sos_norm should remain ~0.500 (percentile normalization is redistributive)
- Teams playing same-age schedules: negligible change
- Teams playing up: SOS increase proportional to cross-age exposure and age gap
- Teams playing down: SOS decrease (their younger opponents are worth less)

## Risk mitigation

SOS feeds into Power-SOS co-calculation (3 iterations), PageRank dampening, connected component normalization, and SCF. The anchor scaling changes the input to all of these. Monitoring plan:
- Run validation script after ranking run
- Check cohort mean stability
- Compare top-of-cohort membership before/after
- Spot-check SE Black and Phoenix as case studies
