# Strength of Schedule (SOS) Algorithm Deep Review

## Executive Summary

**Problem**: Phoenix Rising plays opponents with high `power_score_final` (0.40-0.55) but has low SOS (0.37) and ranks 77th in Arizona.

**Root Cause**: The SOS algorithm uses a different definition of "opponent strength" than what appears in rankings:
- **SOS uses**: `(off_norm + def_norm) / 2 × anchor` (off/def only)
- **Rankings show**: `(0.25×off + 0.25×def + 0.50×sos + perf) × anchor` (includes opponent's SOS)

An opponent with mediocre off/def but tough schedule will rank high in power_score_final but contribute less to your SOS.

---

## Current Algorithm Flow

### Layer 8: SOS Calculation (v53e.py:570-736)

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Build Opponent Strength Map                            │
│  ─────────────────────────────────────                          │
│  opponent_strength = (0.5 × off_norm + 0.5 × def_norm) × anchor │
│                                                                  │
│  NOTE: Does NOT include opponent's SOS (to avoid circularity)   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: Direct SOS (Pass 1)                                    │
│  ───────────────────────────                                    │
│  SOS_direct = weighted_average(opponent_strength for each game) │
│                                                                  │
│  Weights: recency × context × adaptive_k                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: Iterative SOS (3 passes)                               │
│  ────────────────────────────────                               │
│  For each iteration:                                            │
│    SOS_trans = weighted_average(opponent's current SOS)         │
│    SOS = 0.80 × SOS_direct + 0.20 × SOS_trans                   │
│                                                                  │
│  Transitivity lambda = 0.20 (only 20% from opponent's SOS)      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: Normalize Within Cohort                                │
│  ───────────────────────────────                                │
│  sos_norm = percentile_rank(SOS) within (age, gender)           │
│                                                                  │
│  Result: 0.0 = weakest schedule, 1.0 = toughest schedule        │
└─────────────────────────────────────────────────────────────────┘
```

### The Disconnect Illustrated

| Opponent | off_norm | def_norm | sos_norm | power_score_final | Contribution to YOUR SOS |
|----------|----------|----------|----------|-------------------|--------------------------|
| Team A   | 0.80     | 0.70     | 0.50     | 0.60              | 0.53 (strong)            |
| Team B   | 0.50     | 0.50     | 0.95     | 0.60              | 0.35 (weak)              |

Both teams have the same power_score_final (0.60), but:
- Team A contributes 0.53 to your SOS (strong off/def)
- Team B contributes 0.35 to your SOS (weak off/def, strong schedule)

**User expectation**: "I played two 0.60 teams, same SOS contribution"
**Algorithm reality**: "You played one strong team (A) and one weaker team (B)"

---

## Options Analysis

### Option 1: Increase Transitivity Weight

**Change**: Increase `SOS_TRANSITIVITY_LAMBDA` from 0.20 to 0.40-0.50

```python
# Current (v53e.py:58)
SOS_TRANSITIVITY_LAMBDA: float = 0.20  # 80% direct, 20% transitive

# Proposed
SOS_TRANSITIVITY_LAMBDA: float = 0.50  # 50% direct, 50% transitive
```

| Aspect | Assessment |
|--------|------------|
| **Complexity** | Low - single config change |
| **Effectiveness** | Medium - partially captures opponent's schedule |
| **Risk** | Low - reversible, tunable |
| **Breaking Changes** | All SOS values shift, rankings change |

**Pros:**
- Simple, one-line change
- Partially addresses the issue
- Easy to tune/rollback

**Cons:**
- Still doesn't fully match power_score_final
- May cause instability if too high (convergence issues)

---

### Option 2: Multi-Pass Power-SOS Co-Calculation (RECOMMENDED)

**Concept**: Calculate power and SOS together iteratively until convergence.

```
┌──────────────────────────────────────────────────────────────┐
│  PASS 1: Initial Power (no SOS)                              │
│  ──────────────────────────────                              │
│  power_initial = 0.5 × off_norm + 0.5 × def_norm             │
│  (Same as current power_presos)                              │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  PASS 2: Calculate SOS using Pass 1 Power                    │
│  ──────────────────────────────────────                      │
│  opponent_strength = opponent's power_initial × anchor       │
│  SOS = weighted_average(opponent_strength)                   │
│  sos_norm = percentile_rank(SOS)                             │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  PASS 3: Final Power (includes SOS)                          │
│  ──────────────────────────────────                          │
│  power_final = 0.25×off + 0.25×def + 0.50×sos_norm + perf    │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  PASS 4: Refined SOS (using Pass 3 Power) - OPTIONAL         │
│  ─────────────────────────────────────────────               │
│  opponent_strength = opponent's power_final × anchor         │
│  SOS_refined = weighted_average(opponent_strength)           │
│                                                              │
│  Repeat until convergence (delta < threshold)                │
└──────────────────────────────────────────────────────────────┘
```

| Aspect | Assessment |
|--------|------------|
| **Complexity** | High - requires restructuring SOS calculation |
| **Effectiveness** | High - fully captures opponent's ranking |
| **Risk** | Medium - more moving parts |
| **Breaking Changes** | Significant SOS shift, all rankings change |

**Pros:**
- Matches user expectation: "I played strong ranked teams"
- Mathematically rigorous (iterative convergence)
- No circularity issues (each pass uses previous pass's values)
- Existing Pass 1/Pass 2 architecture can be extended

**Cons:**
- More complex implementation
- 2-3x slower computation
- Larger ranking shifts than Option 1

---

### Option 3: Hybrid Approach (Quick Win + Long-term Fix)

**Phase 1 (Immediate)**: Increase transitivity to 0.40
**Phase 2 (Later)**: Implement full multi-pass calculation

This allows immediate improvement while planning the larger refactor.

---

## Breaking Changes Analysis

### What Will Change

| Metric | Current | After Option 1 (λ=0.40) | After Option 2 |
|--------|---------|-------------------------|----------------|
| SOS values | Based on off/def only | 40% from opponent SOS | Based on opponent power |
| SOS range | Similar across states | More differentiation | Matches power_score correlation |
| Top team SOS | May not correlate with power | Better correlation | Strong correlation |

### Dependencies to Update

1. **rankings_full table**: SOS values change
2. **rankings_view / state_rankings_view**: Display new values
3. **ML Layer 13**: May need retuning (uses SOS for weighting)
4. **Historical comparisons**: All invalid after change

### Migration Path

1. Run rankings with new algorithm
2. Compare before/after distributions
3. Validate top teams have sensible SOS
4. Update any downstream systems

---

## Recommendation

### Short-term (Now): Option 1 - Increase Transitivity

```python
# v53e.py line 58
SOS_TRANSITIVITY_LAMBDA: float = 0.40  # Changed from 0.20
```

**Expected impact**:
- SOS will better reflect opponent's schedule quality
- Moderate ranking shifts
- Quick to implement and test

### Long-term (Future): Option 2 - Multi-Pass Co-Calculation

Restructure to calculate:
1. Initial power (off/def only)
2. SOS (using initial power)
3. Final power (including SOS)
4. Optional: Refined SOS (using final power)

This provides the mathematically correct solution where SOS reflects playing strong *ranked* teams, not just teams with good off/def.

---

## Code Locations

| Component | File | Lines |
|-----------|------|-------|
| SOS Config | `src/etl/v53e.py` | 54-67 |
| Opponent Strength Map | `src/etl/v53e.py` | 615-625 |
| Direct SOS Calculation | `src/etl/v53e.py` | 650-663 |
| Iterative SOS | `src/etl/v53e.py` | 676-726 |
| SOS Normalization | `src/etl/v53e.py` | 757-771 |
| Multi-pass Architecture | `src/rankings/calculator.py` | 402-456 |

---

## Questions for Decision

1. **Acceptable ranking shift?** Option 1 causes moderate shift, Option 2 causes larger shift
2. **Timeline?** Option 1 can ship today, Option 2 needs 1-2 days of implementation
3. **Validation approach?** How will you verify the new rankings make sense?
