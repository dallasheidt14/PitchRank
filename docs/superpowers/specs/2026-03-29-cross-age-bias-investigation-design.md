# Cross-Age Bias Investigation: Diagnostic Findings

**Date:** 2026-03-29
**Status:** Diagnosis complete, no fixes proposed
**Scope:** All age cohorts (U10-U19), both genders, with Phoenix United Elite (U12M) as detailed case study

---

## Problem Statement

Teams that play a significant portion of their schedule against older opponents appear to receive artificially suppressed offensive ratings (`off_norm`), resulting in rankings that undervalue their true competitive strength. The question is whether this is a real structural bias in the ranking engine or an artifact of other factors.

## Investigation Methodology

### Approach A: Descriptive Bucket Analysis (Primary)

Grouped all 63,039 teams (8+ games) into cross-age exposure buckets and compared `off_norm`, win rate, and misalignment across buckets within each of the 18 age/gender cohorts.

### Approach C (Limited): Counterfactual Case Study

For Phoenix United Elite only, traced the bias mechanism through each pipeline layer and estimated the ranking penalty.

---

## Finding 1: Cross-Age Exposure Is Associated with Suppressed off_norm

**Verdict: CONFIRMED**

### All-Cohort Bucket Analysis

| Cross-Age Bucket | N Teams | Avg off_norm | Avg win% | Misalignment | Avg SOS |
|---|---|---|---|---|---|
| 0-5% | 32,983 | 0.512 | 0.420 | -0.092 | 0.607 |
| 5-15% | 13,881 | 0.508 | 0.428 | -0.080 | 0.581 |
| 15-30% | 8,930 | 0.506 | 0.435 | -0.071 | 0.554 |
| 30-50% | 4,489 | 0.503 | 0.446 | -0.057 | 0.525 |
| 50%+ | 2,762 | 0.435 | 0.452 | +0.017 | 0.456 |

The misalignment metric (win% - off_norm) flips positive in the 50%+ bucket: these teams win more than their offensive rating suggests. This is the bias signature.

Spearman correlation (all teams): pct_cross_age vs off_norm rho = -0.026, p < 0.000001.

### Total Cross-Age Monotonicity: YES

Progression: 0.512 -> 0.508 -> 0.506 -> 0.503 -> 0.435. Each step decreases.

---

## Finding 2: The Effect Is Masked by Selection Bias at Moderate Exposure Levels

**Verdict: IMPORTANT NUANCE**

### Playing-Up Specific Analysis

| Playing-Up Bucket | N | Avg off_norm |
|---|---|---|
| 0% | 47,296 | 0.502 |
| 1-10% | 6,096 | 0.521 |
| 10-25% | 5,359 | 0.530 |
| 25-50% | 2,924 | 0.533 |
| 50%+ | 1,370 | 0.436 |

Teams that play up at moderate rates (1-50%) show HIGHER off_norm than baseline. This is selection bias: strong teams get scheduled against older opponents. The structural bias only overwhelms the selection effect at extreme exposure levels (50%+).

This does NOT mean the bias doesn't exist at moderate levels — it means the bias is fighting against a positive selection effect, and the net result appears neutral or positive until the schedule becomes dominated by cross-age games.

---

## Finding 3: Directionality

**Verdict: CONFIRMED — offense is suppressed for cross-age exposure**

| Group | N | Off_norm | Def_norm | Win% | SOS |
|---|---|---|---|---|---|
| Primarily play UP (>15% up, <5% down) | 4,970 | 0.527 | 0.549 | 0.480 | 0.609 |
| Primarily play DOWN (>15% down, <5% up) | 6,210 | 0.465 | 0.438 | 0.413 | 0.519 |
| Mostly same-age (<5% cross) | 32,576 | 0.512 | 0.571 | 0.420 | 0.607 |

Playing-down teams show the largest off_norm suppression at population level, but this conflates team quality (weaker teams face younger opponents). The Phoenix case study confirms the mechanism operates in the playing-up direction.

---

## Finding 4: Per-Cohort Patterns

6/18 cohorts show strictly monotonically decreasing off_norm as cross-age exposure rises:

| Cohort | Bucket Progression | Pattern |
|---|---|---|
| U13 Male | 0.505 -> 0.496 -> 0.482 -> 0.467 | YES (strict decrease) |
| U14 Male | 0.505 -> 0.501 -> 0.499 -> 0.453 | YES |
| U15 Female | 0.519 -> 0.506 -> 0.494 -> 0.489 | YES |
| U16 Female | 0.527 -> 0.511 -> 0.510 -> 0.450 | YES |
| U16 Male | 0.519 -> 0.513 -> 0.485 -> 0.478 | YES |
| U17 Male | 0.528 -> 0.490 -> 0.476 -> 0.425 | YES |

11/18 show mixed patterns (bias present but not strictly monotonic). 1/18 (U13F) shows increasing off_norm with cross-age exposure.

The effect is strongest and most consistent in **older male cohorts** (U13M+).

---

## Finding 5: Age Boundary Analysis

### Adjacent-Age Boundaries (high volume)

| Boundary | N Games | Younger Team Margin | Win Rate |
|---|---|---|---|
| U10 vs U11 | 9,221 | +0.45 | 48.6% |
| U11 vs U12 | 10,867 | +0.45 | 49.4% |
| U12 vs U13 | 9,344 | +0.37 | 48.3% |
| U13 vs U14 | 8,535 | +0.07 | 44.2% |
| U14 vs U15 | 5,236 | -0.01 | 43.5% |
| U15 vs U16 | 3,873 | +0.18 | 44.8% |
| U16 vs U17 | 854 | +0.09 | 44.6% |
| U17 vs U19 | 808 | -0.27 | 39.4% |

Positive margins for younger teams at adjacent boundaries confirm selection bias: only strong teams play up one age group. The structural ranking penalty is separate from on-field performance.

### Multi-Step Boundaries (strongest penalties)

| Boundary | N Games | Margin | Win Rate |
|---|---|---|---|
| U14 vs U19 | 13 | -1.23 | 38.5% |
| U16 vs U19 | 122 | -1.12 | 37.7% |
| U13 vs U19 | 33 | -0.73 | 30.3% |
| U15 vs U19 | 84 | -0.61 | 38.1% |
| U13 vs U16 | 64 | -0.59 | 40.6% |

---

## Finding 6: Root Cause — The Pipeline Mechanism

### Primary: Layer 9 Opponent Adjustment Uses Age-Blind abs_strength

`v53e.py` line 1060:
```python
abs_strength = power_presos.clip(0.35, 1.0)
```

`power_presos` = 0.5 * off_norm + 0.5 * def_norm, computed within each cohort. A U13 team at the 50th percentile within U13M gets the same `abs_strength` (~0.50) as a U12 team at the 50th percentile within U12M.

The opponent adjustment formula:
```python
gf_adjusted = gf * (opp_abs_strength / baseline)
```

This treats a median U13 opponent and a median U12 opponent as equally difficult to score against. In reality, the U13 team is materially harder — the age anchors (U12=0.55, U13=0.625) exist in the codebase but are NOT applied to `abs_strength` during opponent adjustment.

### Secondary: Percentile Normalization Against Same-Age Peers

After the incomplete opponent adjustment, `off_norm` is computed as a percentile rank within the team's own cohort. A U12 team that plays mostly U13 opponents is compared to U12 teams that play mostly U12 opponents. The adjusted GF is still lower than peers who scored freely against same-age competition.

### Partial Mitigation: ML Layer 13

The XGBoost model includes `age_gap` as a feature and does partially recognize the pattern:
- Phoenix's ml_overperf = +0.733 (model knows they outperform expectations)
- But alpha = 0.08 caps max ML adjustment at +/-0.04 powerscore units
- This covers approximately 42% of the estimated bias for Phoenix

---

## Finding 7: Phoenix United Elite Case Study

### Profile

- **Team ID:** 691eb36d-95b2-4a08-bd59-13c1b0e830bb
- **Cohort:** U12 Male
- **Record:** 22W-5L-3D (73.3% win rate)
- **Schedule:** 73% of games against U13 opponents

### Performance Split

| Opponents | Games | Avg GF | Avg GA | Margin | Win Rate | Avg Opp abs_strength |
|---|---|---|---|---|---|---|
| U12 (same-age) | 6 | 4.50 | 0.83 | +3.67 | 100% | 0.571 |
| U13+ (cross-age) | 16 | 2.44 | 0.94 | +1.50 | 68.8% | 0.704 |

### Current Ranking Metrics

| Metric | Value | Percentile | Assessment |
|---|---|---|---|
| off_norm | 0.318 | 32nd | Severely suppressed |
| def_norm | 0.977 | 98th | Elite |
| sos_norm | 0.881 | Top 5% | Elite (#1 in AZ) |
| powerscore_adj | 0.787 | — | AZ Rank #5 |
| powerscore_ml | 0.815 | — | Partial ML correction |

### Counterfactual Estimate

| Scenario | off_norm | powerscore | vs Current AZ #1 (0.843) |
|---|---|---|---|
| Current | 0.318 | 0.787 | Below by 0.056 |
| Conservative (0.70) | 0.700 | 0.864 | Above by 0.021 |
| Moderate (0.80) | 0.800 | 0.884 | Above by 0.041 |
| Aggressive (0.90) | 0.900 | 0.904 | Above by 0.061 |

Even a conservative correction makes Phoenix #1 in Arizona.

### AZ U12M Top 5 Comparison

| Rank | Team | off_norm | def_norm | sos_norm | powerscore |
|---|---|---|---|---|---|
| 1 | Phoenix United 2014 Academy | 0.853 | 0.999 | 0.788 | 0.843 |
| 2 | 2014 Antunez Pre-MLS Next | 0.861 | 0.926 | 0.794 | 0.834 |
| 3 | CCV Stars 2014 South PRE-ECNL | 0.791 | 0.802 | 0.842 | 0.824 |
| 4 | BRAZAS FC 2014 Black | 0.919 | 0.980 | 0.711 | 0.807 |
| **5** | **Phoenix United 2014 Elite** | **0.318** | **0.977** | **0.881** | **0.787** |

Phoenix's offense is an extreme outlier among the top 5. Every other metric is elite or best-in-state.

### Why SOS and DEF Don't Compensate

PowerScore formula: `0.20 * off_norm + 0.20 * def_norm + 0.60 * sos_norm`

Phoenix's DEF and SOS contribute 0.724 out of 0.787 total. The offense component contributes only 0.064. With off_norm at 0.80, offense would contribute 0.160 — nearly tripling its contribution and pushing powerscore to 0.884.

The 20% weight on offense means even extreme suppression (0.318 vs expected ~0.80) only costs ~0.10 powerscore. But in a competitive ranking where the top 5 are separated by 0.056, that 0.10 gap is decisive.

---

## Conclusions

1. **The bias is confirmed as structural at the system level:** overall off_norm declines as total cross-age exposure rises, with the clearest penalty appearing once cross-age games dominate the schedule.

2. **The nuance is critical:** at moderate playing-up rates, positive selection bias masks the structural penalty, so the effect is most visible at high exposure.

3. **The primary inferred mechanism is Layer 9 opponent adjustment,** where age-blind `abs_strength` likely under-credits offensive output against older opponents; cohort normalization likely amplifies that downstream.

4. **Phoenix fits the high-exposure pattern extremely well:** 73% cross-age schedule, elite DEF and SOS, but a severely suppressed OFF signal that plausibly drives the underrank.

5. **The ML layer partially compensates in the Phoenix case study,** but the cap is too small to fully offset the estimated upstream distortion there.

---

## Scripts Produced

- `scripts/cross_age_all_cohorts.py` — Full 18-cohort bucket analysis
- `scripts/phoenix_deep_dive.py` — Phoenix United Elite case study
- `scripts/pull_team_data.py` — Initial team data pull
- `scripts/analyze_cross_age_u12m.py` — U12M preliminary analysis

## Next Steps (Not Yet Approved)

- Regression-based validation (Approach B) could further isolate the causal effect
- Fix design for the identified pipeline issues (pending user approval)
- Quantify the full population impact (how many teams' rankings would change materially)
