# SOS Monotonicity Fixes

**Date:** 2026-03-30
**Status:** Design approved, ready for implementation planning
**Prerequisites:** Cross-age offense fix (2026-03-29), cross-age SOS fix (2026-03-30)

---

## Problem

The SOS normalization pipeline produces non-monotonic output: the final `sos_norm` does not preserve the ordering of raw SOS. In U15M production data:

- **Spearman rank correlation (top 30):** -0.071 (worse than random)
- **10+ teams tied at sos_norm = 1.000**, including teams with 0% win rate
- **6–9 GP Active teams** ranked 500–1400 positions below their raw SOS rank

Two independent root causes, requiring two independent fixes.

### Root Cause A: Connected-Component Normalization

When `COMPONENT_SOS_ENABLED = True`, SOS is percentile-normalized independently within each connected component, then blended with global normalization via alpha weighting. U15M has 162 components (main: 7,593 teams; 161 others: 2–10 teams each).

The top team in every component gets `sos_norm_component = 1.0` regardless of their absolute schedule strength. After alpha-blending and Power-SOS re-normalization (3 iterations), multiple teams converge to `sos_norm = 1.000` — including teams with 0% win rate whose only distinction is being in a small component with high-SOS opponents.

**Case study:** Team `5877fc70` (U15M) — 0% win rate, 12 GP, off_norm=0.005, def_norm=0.261. Raw SOS rank #20 in cohort. Production sos_norm = 1.000.

### Root Cause B: Low-Sample Shrinkage Cliff

`MIN_GAMES_FOR_TOP_SOS = 10` but Active eligibility is `MIN_GAMES_PROVISIONAL = 6`. Teams with 6–9 GP are Active and ranked but have their SOS heavily shrunk toward anchor = 0.35:

| GP | Shrinkage (current) | SOS retained |
|----|---------------------|-------------|
| 6  | 0.60                | 60%         |
| 8  | 0.80                | 80%         |
| 10+| 1.00                | 100%        |

This creates large rank inversions: a team with 6 GP and raw SOS rank #3 gets norm rank #1340 because 40% of its SOS deviation is pulled toward 0.35.

**Case study:** Team `394aa723` (U15M) — 100% win rate, 6 GP, raw SOS 0.867 (rank #3). Production sos_norm = 0.739 (rank #1340).

---

## Fix A: Disable Connected-Component SOS Normalization

### Change

Set `COMPONENT_SOS_ENABLED = False` as the new default in `V53EConfig`.

### What this disables by default

- `find_connected_components()` call for SOS grouping
- Per-component groupby in `_apply_hybrid_norm`
- Alpha-blending logic (`alpha * norm_global + (1-alpha) * norm_component`)
- Diagnostic columns `sos_norm_global`, `sos_norm_component`, `_sos_alpha`

### What stays intact

- All component detection and blending code remains behind the `COMPONENT_SOS_ENABLED` toggle for rollback and A/B validation
- `_hybrid_sos_norm` function (percentile + z-score blend) unchanged
- Power-SOS co-calculation unchanged (calls `_apply_hybrid_norm`, which now uses global-only groups)
- SCF dampening unchanged (handles regional bubbles independently)

### Behavior when disabled

`_apply_hybrid_norm` already handles this — when `COMPONENT_SOS_ENABLED = False`, it skips component groupby and uses `norm_global` directly (line 1687–1689 of existing code). No code change needed in the function itself.

### Expected impact

- Eliminates pathological multi-team sos_norm=1.000 ceiling ties
- Restores cross-component comparability
- 0%-win-rate teams lose inflated sos_norm
- Secondary ecosystems (small components) see narrower SOS spread globally — this correctly reflects their absolute schedule strength rather than inflating intra-component ranking

### Rollback

`cfg.COMPONENT_SOS_ENABLED = True` restores previous behavior with no code changes.

---

## Fix B: Lower SOS Shrinkage Threshold to 6

### Change

`MIN_GAMES_FOR_TOP_SOS = 6` (from 10). Aligns SOS trust with Active eligibility (`MIN_GAMES_PROVISIONAL = 6`).

### Shrinkage formula

Unchanged: `sos_norm = anchor + (gp / threshold) * (sos_norm - anchor)` with `SOS_SHRINKAGE_ANCHOR = 0.35`.

### Before/after for Active teams

| GP | Current (threshold=10) | New (threshold=6) |
|----|----------------------|-------------------|
| 3  | 30% retained         | 50% retained      |
| 4  | 40% retained         | 67% retained      |
| 5  | 50% retained         | 83% retained      |
| 6  | 60% retained         | **100% (no shrinkage)** |
| 7  | 70% retained         | **100%** |
| 8  | 80% retained         | **100%** |
| 9  | 90% retained         | **100%** |
| 10+| 100%                 | 100% |

### Rationale

The system already declares 6 GP = Active = ranked. Off_norm and def_norm are computed from the same 6 games with zero shrinkage. SOS is a weighted average of opponent strengths — more stable per-game than offense or defense. Shrinking only SOS contradicts the eligibility decision.

### Expected impact

- 6–9 GP Active teams get full SOS credit
- Eliminates "ranked but shrunk" cliff
- Sub-6-GP teams (Not Enough Ranked Games) still appropriately shrunk
- Main risk: some 6-GP teams with lucky opponent samples may get inflated SOS

### Rollback

`cfg.MIN_GAMES_FOR_TOP_SOS = 10` restores previous behavior.

---

## Config Changes

Both changes are config-default-only. No structural code changes.

| Field | Old Default | New Default | File |
|-------|-------------|-------------|------|
| `COMPONENT_SOS_ENABLED` | `True` | `False` | `src/etl/v53e.py` (V53EConfig) |
| `MIN_GAMES_FOR_TOP_SOS` | `10` | `6` | `src/etl/v53e.py` (V53EConfig) |

---

## Validation

### Success criteria

1. **Monotonicity improvement:** Top-30 Spearman correlation (raw SOS rank vs sos_norm rank) improves from -0.071 to > 0.80 for U15M
2. **No pathological ceiling ties:** No large multi-team ceiling ties — true numeric ties after full-precision normalization are acceptable, but the pathological flat ceiling (10+ teams at exactly 1.000) must be eliminated
3. **6–9 GP distribution shift (B1 validation):**
   - For each GP bucket (6, 7, 8, 9): compare sos_norm distribution before/after
   - Median shift < 0.15
   - No team with win_rate < 20% gets sos_norm > 0.90
   - Count of 6–9 GP teams above key SOS thresholds (>0.80, >0.90, >0.95) before/after — confirm no tail explosion
4. **Same-age guardrail:** A cohort with no cross-age games produces identical results with both fix A toggled on/off (since fix A is a default change, old code path is intact)
5. **Existing tests pass:** All 340+ unit tests unaffected
6. **Case study spot-checks:**
   - DFW Tejanos (`5877fc70`): sos_norm should drop from 1.000 to a value reflecting actual schedule quality
   - Team `394aa723` (6 GP, raw rank #3): sos_norm should rise from 0.739 to near its global percentile
   - OJB FC, SE Black, Phoenix: verify no regression

### Production validation

After ranking workflow completes:
- Cohort mean sos_norm should remain ~0.500 (percentile normalization is redistributive)
- Top-of-cohort membership: compare before/after for U15M, U14M, U12M
- Spot-check known case studies

---

## Implementation Order

1. Fix A: Change `COMPONENT_SOS_ENABLED` default to `False`
2. Fix B: Change `MIN_GAMES_FOR_TOP_SOS` default to `6`
3. Tests: Write failing tests first, then verify they pass with new defaults
4. Validation script: Instrument before/after comparison for the 6–9 GP distribution gate
5. Full test suite + production run

Fixes are independent — no ordering dependency. Sequencing A before B is preferred because A eliminates the ceiling ties that would otherwise confuse B's validation.

---

## Files

| File | Action | What |
|------|--------|------|
| `src/etl/v53e.py` | Modify | Two config default changes in V53EConfig |
| `tests/unit/test_cross_age_opponent_adjustment.py` | Modify | Add monotonicity and shrinkage tests |
| `scripts/sos_monotonicity_trace.py` | Modify | Add before/after distribution comparison for validation |

---

## Risk Mitigation

- Both fixes are config-default changes — zero structural code modification
- Old behavior fully restorable via config toggle
- A/B comparison possible by running with old defaults on the same data
- SOS feeds into Power-SOS, PageRank, SCF, PowerScore — monitoring cohort mean stability confirms no systemic shift
- Low-sample shrinkage still active below 6 GP — no unprotected small samples
