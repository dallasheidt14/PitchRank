# U14 Male AZ Rankings Audit Report

**Date:** 2026-02-09
**Snapshot analyzed:** `data/validation/rankings_after_v54_20251124_103408.csv` (latest with anchor scaling)
**Cohort:** U14 Male, state_code = AZ
**Active teams:** 98 (of 3,661 nationally)

---

## v53e Engine Overview

The v53e engine computes rankings through 10+ layers:

| Layer | Purpose | Key Parameters |
|-------|---------|----------------|
| 1 | Window filter | 365 days lookback |
| 2 | Outlier guard + GD cap | z=2.5, GD cap=6 |
| 3 | Recency weights | Exponential decay (rate=0.05) |
| 4 | Ridge defense | RIDGE_GA=0.25 |
| 5 | Adaptive K + team outlier guard | alpha=0.5, beta=0.6 |
| 6 | Performance (over/underperformance) | PERF_BLEND_WEIGHT=0.15 |
| 7 | Bayesian shrinkage | tau=8.0 |
| 8 | SOS (3 iterations + PageRank dampening) | SOS_WEIGHT=0.50, alpha=0.85 |
| 8b | Schedule Connectivity Factor (SCF) | SCF_FLOOR=0.4, MIN_BRIDGE=2 |
| 8c | Power-SOS co-calculation | 3 iterations, damping=0.7 |
| 9 | Normalize OFF/DEF (zscore -> sigmoid) | Per-cohort |
| 10 | PowerScore = 0.25*OFF + 0.25*DEF + 0.50*SOS + 0.15*Perf | Normalized by 1.075 |

After v53e, Layer 13 (ML) applies XGBoost-based predictive adjustment, and `compute_all_cohorts()` applies anchor scaling (U14 anchor = 0.70).

### PowerScore Formula

```
powerscore_core = (0.25 * off_norm + 0.25 * def_norm + 0.50 * sos_norm + 0.15 * perf_centered) / 1.075
powerscore_adj = powerscore_core * provisional_mult
power_score_final = (ps_adj + ml_delta * ml_scale) * anchor   [capped at anchor]
```

Where `ml_scale` = 0 when `sos_norm < 0.45`, ramps to 1 when `sos_norm >= 0.60`.

---

## CRITICAL FINDING: Modular11 HD/AD Teams Missing From Rankings

### Phoenix Rising FC U14 HD — Case Study

**Team:** Phoenix Rising FC U14 HD (ID: `79c926e1-c42f-404f-afbd-4ef1b7eb2893`)
**Division:** HD (High Development) — MLS NEXT-affiliated league (Modular11 provider)

**The Problem:** This team plays elite HD division opponents — LAFC U14 HD, ALBION SC San Diego U14 HD, City SC San Diego U14 HD, FC Golden State U14 HD, LA Bulls U14 HD, Chula Vista FC U14 HD — but their SOS appears weak because **none of these opponents exist in the rankings**.

**Root Cause:** The entire Modular11 HD/AD division ecosystem is missing from the ranking engine.

| Check | Result |
|-------|--------|
| PRFC U14 HD in rankings snapshot | **NOT FOUND** |
| PRFC U14 HD opponents in rankings | **0 of 13 found** |
| Total HD teams in modular11 registry | 147 |
| HD teams in rankings snapshot | **0 of 147** |
| Modular11 provider registered? | Yes (`b376e2a4-4b81-47be-b2aa-a06ba0616110`) |
| Modular11 import pipeline built? | Yes (`Modular11GameMatcher` in `enhanced_pipeline.py`) |
| Weekly update logs mentioning modular11 | **Zero** |

**Timeline:**
- **2025-11-24:** Latest validation snapshot taken — no modular11 data exists yet
- **2025-12-02:** First modular11 scrape (17,402 games)
- **2025-12-27:** Large modular11 scrape (20,068 games including 3,794 U14 HD games)
- **2026-01-16:** Latest modular11 scrape (3,828 games)

**The import pipeline (`import_games_enhanced.py`) supports modular11** with a dedicated `Modular11GameMatcher`, but no weekly update log shows modular11 imports were ever executed. The games are scraped into `scrapers/modular11_scraper/output/` but were never fed into the database `games` table.

**Impact:**
- **All 147 HD division teams** are invisible to the ranking engine
- **All HD opponents** default to `UNRANKED_SOS_BASE = 0.35` (barely above minimum)
- Any team whose schedule is primarily HD/AD games will have artificially deflated SOS
- This affects PRFC U14 HD, RSL Arizona U14 HD, SC Del Sol U14 HD, LAFC U14 HD, ALBION SC teams, and 140+ others nationally

**PRFC U14 HD's actual schedule (from modular11 scraper):**
```
2025-09-13  vs FC Golden State U14 HD       L 0-1
2025-09-14  vs Las Vegas Sports Academy HD  W 2-0
2025-10-05  vs ALBION SC Las Vegas U14 HD   L 1-2
2025-10-11  vs LAFC U14 HD                  L 0-3
2025-10-19  vs RSL Arizona Mesa U14 HD      W 10-1
2025-10-24  vs SC Del Sol U14 HD            L 2-4
2025-10-26  vs ALBION SC San Diego U14 HD   D 2-2
2025-11-01  vs City SC San Diego U14 HD     L 2-4
2025-11-02  vs City SC Southwest U14 HD     W 5-2
2025-11-08  vs Chula Vista FC U14 HD        L 0-3
2025-11-15  vs RSL Arizona U14 HD           W 3-0
2025-11-22  vs LA Bulls U14 HD              L 1-2
2025-11-23  vs ALBION SC Los Angeles U14 HD W 2-0
```

These are strong opponents (MLS NEXT affiliates, top clubs nationally), but the ranking engine treats every one of them as strength 0.35 because their games haven't been imported.

**Fix Required:** Run `import_games_enhanced.py` with the modular11 scraper output to populate the `games` table with HD/AD league games. Then recalculate rankings.

---

## Additional Audit Findings

### Finding 1: SOS Weight Distribution for Top Teams

**Severity: Low - Working As Designed**

SOS accounts for ~52.8% of the effective PowerScore for top AZ teams. This is intentional — schedule strength should be the dominant differentiator. The config weights (OFF=0.25, DEF=0.25, SOS=0.50, Perf=0.15, normalized by /1.075) produce this balance.

**Component breakdown for top 10 AZ:**
```
OFF: 21.8%  DEF: 25.4%  SOS: 52.8%
```

**Notable cases where SOS tells the correct story:**
- **AZ Thundercats 2012** (AZ #23, Nat #388): OFF=0.855, DEF=0.926 but SOS=0.365. They dominate FBSL-tier opponents but haven't proven themselves against quality. The SOS penalty is correct — beating weak teams shouldn't rank you higher than competing with strong ones.
- **Scottsdale City 2012 Boys** (AZ #34, Nat #697): OFF=0.327, DEF=0.456, SOS=0.945. They lose a lot in tough leagues. SOS rightfully acknowledges the quality of opposition even when results aren't great.

### Finding 2: Next Level Soccer (NLS) Club Dominance - Possible SOS Bubble

**Severity: Medium**

Next Level Soccer (AZ) has 6 teams in the AZ top 30 (teams operate as "Southeast" and "Northwest" brands):

| AZ Rank | Team | PS_final |
|---------|------|----------|
| 1 | Southeast 2012 Boys Black | 0.6813 |
| 3 | Northwest 2012 Boys Black | 0.6345 |
| 5 | Southeast 2012 Boys Blue | 0.6096 |
| 7 | Northwest 2012 Boys Red | 0.5990 |
| 8 | Southeast 2012 Boys Red | 0.5985 |
| 30 | Southeast 2012 Boys Green | 0.4929 |

These teams likely play each other frequently in intra-club scrimmages or league play. The SOS_REPEAT_CAP=2 limits any single opponent to 2 counted games for SOS, but with 6 teams in the same club, cross-team inflation is still possible. The SCF (Schedule Connectivity Factor) should help here since all are in AZ (same state), but if they're playing tournaments in other states, they'd get full SCF credit.

**Recommendation:** Consider whether intra-club games should receive reduced SOS weight, or whether the SOS_REPEAT_CAP should apply at the club level rather than team level.

### Finding 3: ML Layer Behavior - Mixed Direction

**Severity: Low**

Of the top 20 AZ teams, 10 are boosted by ML and 10 are lowered. Notable ML movements:

**ML Boosting (expected - teams overperforming expectations):**
- AZ #1 Southeast 2012 Boys Black: adj=0.9296 -> ml=0.9733 (+0.0437)
- AZ #6 CCV Stars 12 Boys ECNL: adj=0.8125 -> ml=0.8601 (+0.0476)
- AZ #9 East Valley NSFC: adj=0.7952 -> ml=0.8477 (+0.0525)

**ML Lowering (teams underperforming expectations):**
- AZ #12 PRFC SC 12B NL Premier 1 Pacific: adj=0.8478 -> ml=0.8085 (-0.0393)
- AZ #18 CDO 12B Premier: adj=0.8110 -> ml=0.7692 (-0.0419)
- AZ #19 AZ Arsenal 12 Boys Club Premier 2: adj=0.8053 -> ml=0.7618 (-0.0436)

The ML corrections appear reasonable - they adjust teams based on actual game-level residuals. No systematic bias detected.

### Finding 4: SOS-Conditioned ML Scaling Creates Discrepancies

**Severity: Medium**

The SOS-conditioned ML scaling (`ml_scale = 0 when sos_norm < 0.45`) means teams with low SOS should have `power_score_final = powerscore_adj * anchor`. However, the audit found ~50 teams where the actual `power_score_final` differs from the expected value by 1-4%.

**Root cause:** The SOS-conditioned ML scaling in `compute_all_cohorts()` (calculator.py:760-818) operates on `sos_norm` from v53e's per-cohort normalization. But by the time `compute_all_cohorts()` runs, the `sos_norm` values are from the Power-SOS co-calculation (which uses `powerscore_adj` including SOS). This creates a subtle feedback where the ML conditioning threshold uses a different SOS normalization than what was used to compute the base PowerScore.

**Example discrepancies:**
```
AZ#23 AZ Thundercats 2012:     sos=0.365 ml_scale=0.00 expected=0.4749 actual=0.5104 (disc=0.0355)
AZ#49 Scottsdale Sandsharks W: sos=0.106 ml_scale=0.00 expected=0.3363 actual=0.3730 (disc=0.0368)
AZ#62 AZ Arsenal Teal SD:      sos=0.112 ml_scale=0.00 expected=0.2523 actual=0.2928 (disc=0.0404)
```

These teams all have `sos_norm < 0.45`, so `ml_scale = 0.00` and `power_score_final` should equal `powerscore_adj * 0.70`. The discrepancy suggests the anchor scaling is using `powerscore_ml` as the base even when ML should have zero authority.

**Likely code issue:** In `calculator.py:792`, `base = (ps_adj + ml_delta * ml_scale)`. When `ml_scale = 0`, `base = ps_adj`, which is correct. But `ps_ml` may have already been modified by Layer 13 in a way that `ps_ml != ps_adj + pure_ml_delta`. The Layer 13 adjustment includes normalization steps that can shift the base. This means `ml_delta = ps_ml - ps_adj` doesn't purely represent the ML adjustment -- it includes normalization artifacts.

### Finding 5: LOW_SAMPLE Teams With Inflated Rankings

**Severity: Low**

Some teams with very few games (LOW_SAMPLE flag, <10 games) appear at relatively high positions:

| AZ Rank | Team | GP | PS_final | SOS |
|---------|------|----|----------|-----|
| 33 | RATTLESNAKES | 8 | 0.4675 | 0.340 |
| 39 | FCDA 2012B Red NL | 8 | 0.4368 | 0.742 |
| 42 | Yuma Synergy 12B | 6 | 0.4256 | 0.381 |

The quadratic SOS shrinkage (`shrink_factor = (gp/10)^2`) does reduce these teams' SOS influence:
- 8 games: shrink_factor = 0.64 (retains 64% of SOS deviation from 0.5)
- 6 games: shrink_factor = 0.36 (retains 36%)

However, their OFF/DEF metrics may be inflated from small sample sizes. The Bayesian shrinkage (tau=8.0) helps, but 6-8 games may still produce unreliable estimates. The current `MIN_GAMES_PROVISIONAL=5` threshold is low enough that these teams get full "Active" status with only 85-95% of their PowerScore (provisional_mult).

### Finding 6: Strong Teams Penalized by Weak Schedule

**Severity: Medium - Structural Issue**

Teams with strong OFF+DEF metrics but low SOS are significantly penalized:

| Team | OFF | DEF | Avg | SOS | PS_final | Nat Rank |
|------|-----|-----|-----|-----|----------|----------|
| AZ Thundercats 2012 | 0.855 | 0.926 | 0.891 | 0.365 | 0.5104 | #388 |
| RATTLESNAKES | 0.869 | 0.808 | 0.839 | 0.340 | 0.4675 | #668 |
| JEDI 12B | 0.671 | 0.929 | 0.800 | 0.283 | 0.4108 | #1131 |

AZ Thundercats in particular has the highest combined OFF+DEF in AZ (avg 0.891) but ranks #23 due to SOS=0.365. These are likely teams playing in lower-tier local leagues (FBSL, Renegades) where they dominate. The SOS penalty is arguably correct (they haven't proven themselves against strong opposition), but the magnitude of the penalty may be excessive given the 50% SOS weight.

### Finding 7: Anchor Scaling Properly Applied (Latest Snapshot)

**Severity: None - Resolved**

The earlier validation snapshot (`rankings_after_v54_20251123_194206.csv`) had `power_score_final == powerscore_ml` with NO anchor scaling (max U14 PS_final = 1.0 instead of 0.70). The latest snapshot (`20251124_103408`) correctly applies anchor scaling with max U14 PS_final = 0.7000.

**Verification:**
```
u10: max=0.4000 (anchor 0.400) - OK
u11: max=0.4750 (anchor 0.475) - OK
u14: max=0.7000 (anchor 0.700) - OK
u18: max=0.7528 (anchor 1.000) - OK (below cap, just reflects team quality)
```

---

## Summary of Issues by Severity

| # | Finding | Severity | Actionable? |
|---|---------|----------|-------------|
| **CRITICAL** | **Modular11 HD/AD games never imported — 147+ teams invisible** | **CRITICAL** | **Run import_games_enhanced.py with modular11 data** |
| 1 | SOS weight distribution for top teams | Low | Working as designed |
| 2 | NLS club SOS bubble (6 teams in top 30) | Medium | Consider club-level repeat cap |
| 3 | ML layer mixed direction | Low | Working as designed |
| 4 | SOS-conditioned ML scaling discrepancy | Medium | Code fix in calculator.py |
| 5 | LOW_SAMPLE teams at mid-high ranks | Low | Could increase MIN_GAMES_PROVISIONAL |
| 6 | Strong OFF/DEF penalized by weak SOS | Low | Working as designed (see Finding 1) |
| 7 | Anchor scaling fixed in latest | None | Already resolved |

---

## Specific Ranking Concerns

The rankings that seem most "off" for U14 Male AZ:

1. **AZ Thundercats (#23 AZ, #388 nationally)** - Best combined OFF+DEF in state but ranked behind 22 teams due to weak schedule. If they're genuinely elite, they should be ranking tournaments against stronger teams to prove it. The ranking is correct per the algorithm but may feel unfair.

2. **Scottsdale City 2012 Boys (#34 AZ, #697 nationally)** - Very weak offense (0.327) and defense (0.456) but propped up to #34 by SOS=0.945. They play in strong leagues/tournaments but lose most games. The algorithm correctly reflects their schedule quality but arguably over-rewards losing to good teams.

3. **Southeast 2012 Boys Black (#1 AZ, #9 nationally)** - Correctly ranked as top AZ team. Strong defense (0.848), excellent SOS (0.976), and massive performance overperformance (+0.434). The ML boost (+0.0437) is warranted.

4. **Phoenix United 2012 Elite (#2 AZ, #27 nationally)** - Best offense in AZ (0.909) with strong SOS (0.966). ML lowers them slightly (-0.0316) suggesting they may be slightly overperforming their underlying quality. Still clearly a top-3 AZ team.
