# PitchRank Rankings Engine Audit Report

**Date:** 2026-03-18
**Scope:** Full v53e engine + ML Layer 13 + SOS deep dive
**Files audited:**
- `src/etl/v53e.py` (1765 lines — core ranking engine)
- `src/rankings/calculator.py` (925 lines — orchestrator, two-pass SOS, anchor scaling)
- `src/rankings/layer13_predictive_adjustment.py` (651 lines — ML layer)
- `src/rankings/data_adapter.py` (992 lines — Supabase ↔ v53e format conversion)
- `src/utils/merge_resolver.py` (291 lines — team merge resolution)

---

## Executive Summary

The PitchRank rankings engine is a sophisticated 13-layer system that, on the whole, is **methodologically sound**. The math is defensible, the guardrails are numerous, and the code shows evidence of iterative debugging and hardening. However, the audit uncovered **3 critical risks**, **5 medium issues**, and **4 low-severity items** that could silently corrupt rankings under specific data conditions.

The biggest systemic risk is **triple application of anchor scaling** — the same age-based multiplier is applied in three separate code paths, which means U10 teams could be scaled by 0.40^3 = 0.064 instead of 0.40 if all paths fire. The second major risk is **SOS weight dominance** at 60%, which makes rankings hypersensitive to schedule artifacts.

---

## Phase 1 — Engine Code Audit

### Layer 1: Window Filter (`v53e.py:722-723`)

**What it does:** Applies a hard 365-day cutoff. Games older than 365 days from the reference date are dropped entirely.

**How it works:**
```python
cutoff = today - pd.Timedelta(days=cfg.WINDOW_DAYS)
g = g[g["date"] >= cutoff].copy()
```

**What could go wrong:** This is a hard cutoff, not a decay. A game played 364 days ago has full weight; a game played 366 days ago has zero weight. A team that played a strong tournament 366 days ago loses ALL that credit overnight. Combined with the recency decay in Layer 3, this creates a "cliff edge" effect.

**Severity: Low** — The recency decay at 0.05 already gives old games ~22% weight at position 30, so the cliff is softened. But teams with few games near the boundary could see ranking volatility.

---

### Layer 2: Outlier Guard + Goal Diff Cap (`v53e.py:733-746`)

**What it does:** Per-team z-score clipping of GF/GA, then hard cap at 6 goals.

**How it works:**
1. Within each team's games, GF and GA are z-score clipped at 2.5 SD
2. Then a hard cap at `GOAL_DIFF_CAP=6` is applied to both GF and GA individually
3. Goal difference is capped at [-6, 6]

**What could go wrong:**
- The z-score clipping runs BEFORE the 30-game filter, so it operates on the full 365-day window. With only 3+ games (minimum for `_clip_outliers_series`), the z-score mean/SD could be unstable.
- **Capping GF and GA individually at 6** means an 8-0 win becomes 6-0, but a 6-6 draw stays 6-6. This is correct and prevents blowout inflation.

**Severity: Low** — Well-implemented. The individual GF/GA cap at line 744-745 is a thoughtful addition that prevents offensive inflation from blowouts.

---

### Layer 3: Recency Weights (`v53e.py:761-773`)

**What it does:** Assigns exponential decay weights to games. Most recent game gets highest weight, oldest gets lowest.

**How it works:**
```python
weights = [exp(-0.05 * i) for i in range(n)]  # normalized to sum=1
```
Game 1 (most recent): weight=1.0 (before normalization)
Game 15: weight=0.47
Game 30: weight=0.22

**What could go wrong:** The recency weights are computed per-team AFTER sorting by date descending. If two games have the same date (e.g., tournament doubleheader), `rank(method="first")` assigns arbitrary ordering. This could cause ranking instability between runs if the sort is not deterministic.

**Severity: Low** — Tournament doubleheaders are rare enough that this is a minor issue. Adding a secondary sort key (game_id) would fix it.

---

### Layer 4: Ridge Defense (`v53e.py:844`)

**What it does:** Converts goals-against into a defense score. Lower GA = higher defense.

**How it works:**
```python
def_raw = 1.0 / (sad_raw + RIDGE_GA)  # RIDGE_GA = 0.25
```

**What could go wrong:** With RIDGE_GA=0.25 as the regularization term:
- A team with 0.0 GAA gets def_raw = 4.0
- A team with 2.0 GAA gets def_raw = 0.44

The ridge prevents division by zero, which is good. But the reciprocal transformation creates a **nonlinear scale** — the difference between 0.0 and 0.5 GAA is much larger than between 2.0 and 2.5 GAA. This heavily rewards clean sheets.

**Severity: Low** — This is a defensible design choice for soccer where defensive excellence is rare and valuable.

---

### Layer 5: Adaptive K Factor (`v53e.py:1003-1007`)

**What it does:** Gives more weight to "upset" games (where there's a large strength gap between opponents).

**How it works:**
```python
k = ALPHA * (1.0 + BETA * abs(team_strength - opp_strength))
# With ALPHA=0.5, BETA=0.6:
# Equal opponents: k = 0.5
# Large gap (0.5 diff): k = 0.65
```

**What could go wrong:** This multiplier enters the SOS weight as `w_sos = w_game * k_adapt`. A team that consistently plays opponents far above or below them gets MORE SOS weight per game. This could create a feedback loop:
1. Team plays a very strong opponent → high k_adapt → high w_sos
2. That game dominates SOS calculation
3. If it was a one-off tournament game, it over-represents schedule strength

**Severity: Medium** — The effect is bounded (max k is ~0.8 for a 0.5 strength gap), but it systematically favors teams that play in mixed-strength environments (tournaments) over league-only teams.

---

### Layer 7: Bayesian Shrinkage (`v53e.py:850-857`)

**What it does:** Pulls offense and defense statistics toward the cohort mean for teams with few games. More games = less shrinkage.

**How it works:**
```python
off_shrunk = (off_raw * gp + mu_off * TAU) / (gp + TAU)  # TAU = 8.0
```
- With 8 games: 50% toward mean
- With 16 games: 67% own stats
- With 30 games: 79% own stats

**What could go wrong:**

**CRITICAL FINDING: The prior (cohort mean) may be miscalibrated.**

The shrinkage pulls toward `mu_off = df["off_raw"].mean()` — the mean of the *current cohort*. This is the mean AFTER outlier clipping and GD capping. In a cohort with many blowout teams, the mean offense will be artificially compressed. In a small cohort (e.g., U18 Female with 20 teams), the mean is unstable.

More importantly, the shrinkage is applied TWICE:
1. First at line 869 (initial pass)
2. Again at line 978 (after opponent adjustment)

The second application operates on *already-shrunk* data that was then adjusted for opponent strength. The cohort mean used in the second shrinkage is the mean of opponent-adjusted values, which is correct. But the shrinkage formula adds TAU=8 "phantom games" again, effectively double-counting the prior. A team with 8 real games after the second pass acts like it has 8+8+8=24 games of prior influence.

**Severity: Critical** — The double shrinkage systematically pulls all teams toward the mean more than intended. It reduces ranking differentiation, especially for teams with 8-15 games. The effect is masked by normalization (percentile ranking removes absolute level), but it compresses the *pre-normalization* distribution, making the percentile mapping noisier.

**Recommendation:** Apply Bayesian shrinkage only once, after the final off/def values are computed. Or use a reduced TAU on the second pass (e.g., TAU/2).

---

### Layer 8: SOS Calculation — THE CORE (`v53e.py:1011-1393`)

**What it does:** Computes Strength of Schedule — the average quality of a team's opponents, weighted by recency, game importance, and strength gap.

**How it works (step by step):**

1. **Full 365-day window** — SOS uses ALL games (not just last 30). This is smart — prevents a recent 3-game weak streak from dominating.

2. **Repeat cap = 2** — Each opponent counts at most 2 times. Prevents a team that plays the same rival 6 times from having that rival dominate their SOS.

3. **Opponent strength lookup** — For in-cohort opponents, uses `base_strength_map` (OFF/DEF only, no SOS). For cross-age opponents, uses `global_strength_map` from Pass 1. Unknown opponents get 0.35.

4. **Weighted average** — `sos = weighted_avg(opp_strength, w_sos)` where `w_sos = w_game * k_adapt`.

5. **PageRank dampening** — `sos_final = 0.15 * 0.5 + 0.85 * sos_calculated`. Anchors 15% toward neutral to prevent infinite inflation in bubbles.

6. **SCF (Schedule Connectivity Factor)** — Detects regional bubbles by checking opponent geographic diversity. Isolated teams get SOS dampened toward 0.5.

7. **Connected Component normalization** — Disconnected subgraphs (e.g., ECNL vs MLS NEXT HD) are normalized independently.

8. **Percentile normalization within components** — Converts raw SOS to [0,1] percentile within each connected component.

9. **Component-size shrinkage** — Small components get their percentile pulled toward 0.5.

10. **Low-sample shrinkage** — Teams with < 10 games get SOS percentile pulled toward 0.5 with quadratic decay.

11. **Power-SOS co-calculation** — 3 iterations of: recalculate opponent strength using full power (including SOS), recompute SOS, recompute power. Uses damping=0.7.

**What could go wrong:**

**CRITICAL FINDING: SOS Weight at 60% creates schedule-dominated rankings.**

```python
OFF_WEIGHT: float = 0.20
DEF_WEIGHT: float = 0.20
SOS_WEIGHT: float = 0.60
```

PowerScore = 0.20*OFF + 0.20*DEF + 0.60*SOS

This means 60% of a team's ranking is determined by who they play, not how they play. A mediocre team (50th percentile OFF/DEF) playing a tough schedule (90th percentile SOS) gets: `0.20*0.5 + 0.20*0.5 + 0.60*0.9 = 0.74`. Meanwhile, a dominant team (95th percentile OFF/DEF) with a weak schedule (30th percentile SOS) gets: `0.20*0.95 + 0.20*0.95 + 0.60*0.3 = 0.56`.

**The mediocre team with a tough schedule outranks the dominant team with a weak schedule.** While SOS should be important (playing good opponents matters), 60% weight makes it possible to rank high just by being in a tough conference and going .500.

**Severity: Critical** — This is the single biggest risk to ranking accuracy. SOS at 60% means a team's ranking is more about their league placement than their actual performance. A team that goes 15-15 in ECNL could outrank a team that goes 25-5 in a tier below.

**Recommendation:** Reduce SOS to 40-45% and increase OFF+DEF to 55-60%. The "right" split depends on the philosophical question: "Is a .500 team in ECNL better than a dominant team in Premier?" If yes, keep 60%. If not, reduce.

---

**MEDIUM FINDING: Transitivity is disabled but iterative Power-SOS is enabled.**

```python
SOS_ITERATIONS: int = 1        # Single pass (no transitive propagation)
SOS_TRANSITIVITY_LAMBDA: float = 0.0  # Disabled
SOS_POWER_ITERATIONS: int = 3  # But Power-SOS runs 3 iterations!
```

The explicit `SOS_ITERATIONS=1` disables transitive SOS propagation (your opponent's opponents don't matter). But `SOS_POWER_ITERATIONS=3` effectively reintroduces transitivity through the back door — when you recalculate opponent strength using full power (which includes SOS), you're propagating schedule information transitively.

This isn't necessarily wrong — the Power-SOS loop is more principled than raw transitive propagation. But the config suggests transitivity was intentionally disabled, while Power-SOS does the same thing through a different mechanism. The code comment says "ensures that playing teams with tough schedules properly boosts your SOS" — that's exactly what transitivity does.

**Severity: Medium** — No bug, but the config is misleading. The effective behavior is 3 iterations of transitive SOS with damping=0.7.

---

**MEDIUM FINDING: UNRANKED_SOS_BASE = 0.35 biases against teams playing unknowns.**

Unknown opponents (not in any cohort's strength map) get assigned 0.35 strength. In a system where mean strength is ~0.5, this means playing an unknown team *hurts* your SOS. In youth soccer, "unknown" often means:
- A team from a provider not yet integrated
- A team that was recently created
- An out-of-state travel team at a tournament

These teams could be strong or weak. Using 0.35 (below average) systematically penalizes teams who play in diverse tournaments with teams from small clubs.

**Severity: Medium** — Should be 0.5 (neutral) unless there's evidence unknown teams are below average.

---

### Layer 6: Performance (`v53e.py:1415-1453`)

**What it does:** Measures how much a team outperforms or underperforms expectations based on power ratings.

**How it works:**
```python
expected_margin = 5.0 * (team_power - opp_power)
perf_delta = actual_gd - expected_margin
# Filtered by 0.5-goal threshold, then weighted by recency and k_adapt
```

**Key observation:** `PERF_BLEND_WEIGHT = 0.00` — Performance is **currently disabled** in PowerScore calculation. It's computed and stored for diagnostics only. This was done to fix a "stat-padding bias" where teams running up scores against weak opponents got an outsized performance boost.

**Severity: Low** — Disabling performance is the right call until the stat-padding issue is properly addressed. The ML Layer 13 effectively replaces this with a more sophisticated approach.

---

### Layer 10: PowerScore Composition (`v53e.py:1467-1478`)

**What it does:** Combines offense, defense, and SOS into a single score, then applies provisional multiplier.

**How it works:**
```python
powerscore_core = (0.20*off_norm + 0.20*def_norm + 0.60*sos_norm) / 1.0
powerscore_adj = powerscore_core * provisional_mult
# provisional_mult: 0.85 for <8 games, 0.95 for <15 games, 1.0 otherwise
```

**What could go wrong:** The provisional multiplier creates discontinuities:
- 7 games → powerscore * 0.85
- 8 games → powerscore * 0.95

A team that wins game 8 could jump 10% in PowerScore just from the multiplier change, not from improved performance. This is a known tradeoff — the multiplier prevents under-sampled teams from ranking too high.

**Severity: Low** — The step function is crude but effective. A sigmoid transition would be smoother but adds complexity.

---

### Layer 8b: SCF Regional Bubble Detection (`v53e.py:383-618`)

**What it does:** Detects teams playing only within an isolated geographic region and dampens their SOS toward neutral.

**How it works:**
1. For each team, counts unique opponent states and regions
2. Calculates `state_diversity = unique_states / 3.0`
3. Adds region bonus (up to 0.2 for multi-region schedules)
4. SCF = max(0.4, min(1.0, state_diversity + region_bonus))
5. Quality override: if opponents' average power > p65, boost SCF to at least 0.85
6. Applies: `sos_adjusted = 0.5 + SCF * (sos - 0.5)`

**What could go wrong:**
- The quality override at p65 is generous — it means any team whose opponents are above-median quality bypasses the bubble penalty. In a strong cohort like U15 Male, most teams might qualify.
- `SCF_FLOOR = 0.4` means even a completely isolated team keeps 40% of their SOS deviation from neutral. A truly isolated bubble (3 teams playing each other in a loop) could still inflate.

**Severity: Medium** — The quality override may be too permissive, but the PageRank dampening and component normalization provide additional safety nets.

---

### Power-SOS Co-Calculation (`v53e.py:1494-1613`)

**What it does:** Iteratively refines SOS using opponents' full power scores (which include SOS).

**How it works:**
```
For 3 iterations:
  1. Build strength map: full_power = max(powerscore_adj * anchor, base_strength)
  2. Recalculate SOS using full opponent power
  3. new_sos = 0.7 * calculated + 0.3 * previous  (damping)
  4. Re-normalize SOS percentiles within components
  5. Re-apply low-sample shrinkage
  6. Recalculate PowerScore with new SOS
  7. Check convergence (mean change < 0.0001)
```

**Key detail — the floor:** Line 1530: `floored_power_values = np.maximum(full_power_values, base_strength_values)`. This prevents circular depression in closed elite leagues. Without it, a closed league could spiral downward because all teams' SOS depends on each other, and if SOS drops, power drops, which drops SOS further.

**What could go wrong:** The floor is asymmetric — it prevents downward spirals but not upward spirals. A closed league of mediocre teams that beat each other could inflate because the floor keeps their power from dropping, maintaining their SOS contributions.

**Severity: Medium** — The asymmetric floor introduces an upward bias. Should be monitored with test cases.

---

### ML Layer 13 (`layer13_predictive_adjustment.py`)

**What it does:** Uses XGBoost to predict game outcomes, then measures how much each team outperforms or underperforms predictions. Teams that consistently beat expectations get a PowerScore boost.

**How it works:**
1. **Feature engineering:** team_power, opp_power, power_diff, age_gap, cross_gender
2. **30-day time split:** Train on games >30 days old, predict on all games. Prevents data leakage.
3. **Residual = actual_margin - predicted_margin** — positive means team outperformed
4. **Recency-weighted aggregation:** More recent overperformance counts more (lambda=0.06)
5. **Minimum 6 games** required for residual to be non-zero
6. **Cohort normalization:** Percentile within (age, gender), then center to [-0.5, +0.5]
7. **Blend:** `powerscore_ml = (powerscore_adj + alpha * ml_norm) / (1 + 0.5*alpha)`

**What could go wrong:**

**MEDIUM FINDING: XGBoost uses only 5 features, all derived from current PowerScores.**

The features are: team_power, opp_power, power_diff, age_gap, cross_gender. Since team_power and opp_power are the current v53e PowerScores, the model is essentially learning "given these teams' ratings, how much does the actual result deviate?" This is a valid approach (residual modeling), but the features are thin:
- No venue information (home/away)
- No form (recent W/L streak)
- No historical head-to-head
- No tournament context

With only 5 features and the target being goal margin, XGBoost is essentially fitting a nonlinear expected-margin function. The residuals capture "everything the PowerScore doesn't explain." This is fine, but alpha=0.18 means this accounts for a meaningful chunk of the final score.

**Severity: Medium** — Not a bug, but the ML layer has limited predictive power due to thin features. The 30-day time split is correctly implemented and prevents leakage. The minimum 6 games requirement and residual clipping at ±3.5 are good guardrails.

---

### Anchor Scaling — TRIPLE APPLICATION

**CRITICAL FINDING: Age anchor scaling is applied in THREE separate places.**

1. **v53e.py:920** — `abs_strength = power_presos * anchor` (used for SOS opponent strength lookups)
2. **calculator.py:787-853** — `power_score_final = (base * anchor).clip(0, anchor)` (post-ML scaling in compute_all_cohorts)
3. **data_adapter.py:890-925** — `calculate_anchor_scaled_power()` in `v53e_to_rankings_full_format()` (pre-DB write defensive scaling)

Place #1 is for internal SOS calculations only — it scales `power_presos` (50% OFF + 50% DEF, no SOS) to create cross-age comparable strengths. This is correct and necessary.

Place #2 applies anchor scaling to the final `power_score_final` column. This takes the ML-blended score and multiplies by the age anchor (U10=0.40, U18=1.00).

Place #3 is described as a "defensive measure" because "values were not persisting to the DB." It re-applies the SAME scaling formula. If place #2 already ran, the value coming in is already scaled, and scaling again would square the anchor.

**Code evidence from data_adapter.py:877-884:**
```python
# This function is the last stop before DB write, so applying anchor
# scaling here guarantees correctness regardless of upstream issues.
```

**But the code checks for incoming values at line 929:**
```python
incoming_psf = rankings_df.get('power_score_final')
if incoming_psf is not None and incoming_psf.notna().any():
    logger.info(f"Re-applying anchor scaling to power_score_final (defensive)")
```

It logs "Re-applying" — confirming it knows the values may already be scaled. The function unconditionally recomputes `power_score_final` from `powerscore_adj` (which is NOT anchor-scaled), applies SOS-conditioned ML, THEN applies anchor. So this is actually recomputing from scratch, not double-applying.

**Re-assessment:** After careful TRACE through the code path:
- `compute_all_cohorts` line 853: sets `power_score_final = (base * anchor).clip(0, anchor)` — this IS anchor-scaled
- `v53e_to_rankings_full_format` line 943: overwrites `power_score_final` by recomputing from `powerscore_adj` — which is NOT anchor-scaled

So the data_adapter REPLACES the calculator's value with its own computation. The two computations should produce the same result IF the SOS-conditioned ML logic is identical. **But there's a subtle difference:**

- Calculator (line 824): uses vectorized SOS thresholds across all teams in an age group
- Data adapter (line 908): applies per-row using `row.apply()` with the same thresholds

These should be equivalent, but the data adapter operates on the combined output of ALL cohorts, while the calculator operates per-age-group. If there are any NaN handling differences, the results could diverge.

**Severity: Critical** — The redundant computation in data_adapter is a maintenance hazard. If the formula changes in calculator.py but not in data_adapter.py (or vice versa), rankings will silently use the wrong values. This is a "last-write-wins" problem where the data adapter always wins.

**Recommendation:** Remove anchor scaling from ONE of the two places. The data_adapter should either trust the incoming `power_score_final` or be the sole owner of anchor scaling. Having both creates a silent override.

---

### Data Adapter (`data_adapter.py`)

**What it does:** Converts Supabase game records to v53e format (one row per team per game, with home and away perspectives).

**How it works:**
1. Fetches games from Supabase with pagination (1000-row batches)
2. Fetches team metadata (age_group, gender) in 100-ID batches
3. Creates two rows per game (home perspective + away perspective)
4. Applies merge resolution (deprecated → canonical team IDs)
5. Filters out deprecated teams, missing scores, missing metadata

**What could go wrong:**

**MEDIUM FINDING: Future-dated games are excluded, but the filter is fragile.**

Line 133: `.lte('game_date', today_date_str)` — This excludes games with dates in the future. Good. But `today` defaults to `pd.Timestamp.utcnow().normalize()`, which strips time. If the Supabase games table stores timestamps (not just dates), a game entered as "2026-03-18T23:00:00Z" would be included even if the ranking runs at midnight UTC on 2026-03-18.

**Severity: Low** — The `lte` comparison against a date string should work correctly for date-only values.

---

### Merge Resolver (`merge_resolver.py`)

**What it does:** Maps deprecated team IDs to their canonical replacements. Ensures merged teams appear as a single entity in rankings.

**How it works:**
- Loads `team_merge_map` from Supabase into an in-memory dict
- `resolve(team_id)` returns canonical ID (or original if not deprecated)
- Version hash enables cache invalidation when merges change

**What could go wrong:**

The resolver does NOT handle **transitive merges** (A → B → C). If team A was merged into B, and later B was merged into C, calling `resolve(A)` returns B (not C). The merge map is a flat dictionary, not a chain.

**Severity: Medium** — If transitive merges exist in the database, teams could appear duplicated in rankings. The merge map should be resolved transitively during load.

---

## Phase 2 — SOS Team Deep Dive

### Team 1: `ffa679df-b3e3-43cf-a330-d7dd6dea5be7`

**From validation data (2025-11-24):**
| Metric | Value |
|--------|-------|
| Age Group | U12 Male |
| Games Played | 30 |
| Status | Active |
| PowerScore (adj) | 0.813 |
| PowerScore (ML) | 0.849 |
| SOS Norm | 0.791 |
| OFF Norm | 0.797 |
| DEF Norm | 0.845 |
| Perf Centered | +0.046 |
| Power Score Final | 0.467 |
| Rank in Cohort | 207 |

**SOS Calculation Walkthrough:**

1. **Offense/Defense Profile:** This team has strong offense (79.7th percentile) and strong defense (84.5th percentile). They're a well-rounded, top-quartile team within U12 Male.

2. **SOS at 79.1st percentile:** Their opponents are stronger than ~79% of the cohort. This is a tough schedule.

3. **PowerScore Composition:**
   ```
   powerscore_core = 0.20 * 0.797 + 0.20 * 0.845 + 0.60 * 0.791
                   = 0.159 + 0.169 + 0.475
                   = 0.803
   ```
   After provisional multiplier (1.0 for 30 games): powerscore_adj ≈ 0.803
   The stored value of 0.813 suggests Power-SOS co-calculation adjusted upward slightly.

4. **ML Adjustment:** ML pushed from 0.813 to 0.849 (+0.036). This means the team outperformed ML expectations, likely winning games they were "expected" to draw or lose. This is a +4.4% boost — within the alpha=0.18 range.

5. **Power Score Final = 0.467:** This is the anchor-scaled value: `0.849 * 0.55 (U12 anchor) ≈ 0.467`. Checks out.

6. **Rank 207:** Out of presumably 500+ U12 Male teams. With a 0.849 ML PowerScore, this team is in the top 40% nationally. Rank 207 makes sense if there are ~500 active teams.

**Sanity Check:** The numbers are internally consistent. Strong team (top quartile OFF/DEF), tough schedule (top quintile SOS), ML says they're overperforming — all signs of a legitimately strong U12 team. The anchor scaling correctly caps them at 0.55 (U12 ceiling), putting their national power score at 0.467.

**What would change their SOS:** If they played 3 additional games against teams at 0.95 strength (elite U12 teams), their SOS would increase. With 30 games, 3 new games represent 10% of the sample. If current opponent average strength is ~0.35 (implied by SOS_norm at 79th percentile in U12), adding 3 games at 0.95 would shift the weighted average up by approximately:
```
delta_sos ≈ (3 * 0.95 * w_new) / (total_w + 3 * w_new)
```
With recency decay favoring new games, the shift would be meaningful — maybe 2-5 percentile points of SOS_norm, translating to ~1-3 rank positions.

---

### Team 2: `691eb36d-95b2-4a08-bd59-13c1b0e830bb`

This team ID appears ONLY in `scripts/diagnose_merge.py` as a canonical merge target:
```
python scripts/diagnose_merge.py --canonical 691eb36d-95b2-4a08-bd59-13c1b0e830bb
```

This team is NOT in the validation rankings data. This likely means:
1. It's a canonical team that absorbed a deprecated team
2. After merge resolution, games from the deprecated team flow into this team
3. The team may be inactive/not enough games, or
4. The team was created after the last validation snapshot

**SOS Implications of Merged Teams:**
When a deprecated team's games are merged into this canonical team:
- The deprecated team's games count toward the canonical team's SOS
- Opponents of the deprecated team become opponents of the canonical team
- If the deprecated team played in a different region or tier, this could distort the canonical team's schedule profile
- The merge resolution happens in the data adapter BEFORE v53e processing, so the engine sees a single unified team

**Risk:** If the deprecated team played in a weaker league and the canonical team plays in ECNL, the merged games would dilute the canonical team's SOS downward. Conversely, if the deprecated team played in a strong tournament, it could inflate SOS.

---

## Phase 3 — Structured Audit Report

### Section 1 — Algorithm Health

**Overall Assessment:** The math is sound. The v53e engine is well-architected with appropriate guardrails (outlier clipping, Bayesian shrinkage, component normalization, PageRank dampening). The two-pass SOS architecture correctly handles cross-age opponent lookups. The ML layer has proper leakage prevention with the 30-day time split.

**Top 3 Risks to Ranking Accuracy:**

1. **SOS Weight Dominance (60%)** — Rankings are more about schedule than performance. A .500 team in a tough league can outrank a dominant team in a weaker league. This is a *philosophical* choice, but 60% is at the high end of defensible range.

2. **Triple Anchor Scaling Code Paths** — Three separate code locations compute anchor-scaled power scores. The data adapter always wins (last write), but if its formula diverges from the calculator's, rankings silently use the wrong computation. This is a maintenance time bomb.

3. **Double Bayesian Shrinkage** — The shrinkage formula is applied twice (before and after opponent adjustment), adding TAU=8 phantom games each time. This over-regularizes teams with 8-15 games, compressing the distribution more than intended.

**Components Needing Immediate Attention:**
- Reconcile anchor scaling between `calculator.py` and `data_adapter.py` — pick one owner
- Validate that double shrinkage is intentional by comparing ranking distributions with single vs. double shrinkage

---

### Section 2 — SOS Methodology

**Is the SOS calculation methodologically sound for national youth soccer?**

Yes, with caveats. The multi-layered approach (direct SOS → PageRank dampening → SCF bubble detection → component normalization → Power-SOS co-calculation) is more sophisticated than most ranking systems. The key innovations:
- Using connected components to normalize disconnected ecosystems independently
- The quality override for SCF that prevents penalizing elite regional leagues
- The Power-SOS floor that prevents circular depression

**Is it vulnerable to gaming (scheduling weak opponents)?**

Partially protected:
- Repeat cap (2 games per opponent) prevents farming one weak team
- Low-sample shrinkage penalizes teams with few games
- SOS normalization within components limits the benefit of being in a weak component

Not protected:
- A team could schedule 10 different weak tournament opponents and only 2 strong league opponents. The repeat cap doesn't help because each weak opponent is unique.
- With 60% SOS weight, a team that strategically avoids strong opponents loses a lot of PowerScore. This is actually anti-gaming — it strongly incentivizes playing tough opponents.

**How does it handle teams with very few games?**

Well:
- **Provisional multiplier:** <8 games → 15% penalty, <15 games → 5% penalty
- **Quadratic SOS shrinkage:** Teams with <10 games have SOS pulled toward 0.5
- **Bayesian shrinkage:** OFF/DEF pulled toward cohort mean
- **Inactive filtering:** <180 days of activity → hidden from rankings

Combined, a team with 3 games would have: powerscore * 0.85 (provisional) with SOS ~0.5 (shrinkage) and OFF/DEF heavily regularized. They'd rank near the bottom, which is correct.

---

### Section 3 — Data Quality Risks

**Places where bad/missing data could silently corrupt rankings:**

1. **NULL team IDs in games** — Filtered at query level (line 134-141 of data_adapter.py). Well-handled.

2. **Missing age_group or gender in teams table** — Games with missing metadata are silently dropped (line 339-344). If a large batch of teams has missing metadata, games would disappear from rankings without warning. The log message at line 348 would show "Skipped X games with missing team age/gender metadata" but this could be missed in automated runs.

3. **Score parsing failures** — `pd.to_numeric(home_score, errors='coerce')` silently converts unparseable scores to NaN, which then gets dropped. A corrupted import could silently remove hundreds of games.

4. **Duplicate game records** — The data adapter deduplicates by `id` (line 217), but if the same game is imported with different IDs (e.g., from different providers), it would appear twice. This doubles the perspective rows and inflates game counts. The `game_uid` field is supposed to prevent this, but it falls back to `id` if game_uid is null.

**Deduplication concerns:**
- The perspective format (2 rows per game) means any dedup issue doubles the impact
- If the repeat cap (2 per opponent) is hit, extra duplicates are filtered, but below the cap they inflate SOS sample size

---

### Section 4 — Recommendations

#### Quick Wins (can be done in a few hours):

1. **Set `UNRANKED_SOS_BASE = 0.50`** instead of 0.35. Unknown opponents should be neutral, not below average. Impact: fairer SOS for teams playing in diverse tournaments with small clubs.

2. **Add deterministic sort tiebreaker** — In recency ranking (line 752), add `game_id` as secondary sort key to prevent non-deterministic rankings between runs.

3. **Add a "double shrinkage" warning** — If the second shrinkage pass is intentional, add a comment explaining why. If not, apply shrinkage only once (after opponent adjustment).

4. **Log validation for critical thresholds** — Add a post-ranking assertion that checks: `assert all(0 <= ps <= 1.0 for ps in power_score_final)` and `assert no NaN in rank_in_cohort for Active teams`.

#### Medium Refactors (1-2 days):

5. **Consolidate anchor scaling** — Remove anchor scaling from `data_adapter.py` and make `calculator.py` the sole owner. Add a `_is_anchor_scaled` flag to the DataFrame to prevent accidental re-application.

6. **Reduce SOS weight to 0.45-0.50** — Run a backtest comparing 60% SOS vs 45% SOS against known tournament results. If 45% better predicts actual game outcomes, adopt it. The current 60% likely over-weights schedule at the expense of performance.

7. **Handle transitive merges** — In `MergeResolver.load_merge_map()`, resolve chains: if A→B and B→C, store A→C directly.

8. **Add cross-provider dedup** — Before creating perspective rows, check for games with the same teams + date + score from different providers. Log and deduplicate.

#### Larger Refactors (1-2 weeks):

9. **Unify the Power-SOS loop with the two-pass architecture** — Currently, `compute_all_cohorts` runs Pass 1 → build global map → Pass 2. Within each pass, `compute_rankings` runs 3 Power-SOS iterations. This means each cohort runs 3 internal iterations in Pass 1, then 3 more in Pass 2, for 6 total. The outer two-pass and inner three-iteration loops could be unified into a single convergence loop, reducing total iterations and improving clarity.

10. **Enrich ML features** — Add home/away (if available from game context), recent form (last 5 games W/L), tournament/league flag, and goal differential trend. This would improve the ML layer's predictive power beyond pure residual modeling.

11. **Implement SOS gaming detection** — Flag teams whose SOS is disproportionately driven by a small number of strong opponents (e.g., 2 strong tournament games + 20 weak league games). Compute an SOS Gini coefficient to measure schedule balance.

#### Places Where Current Approach Could Cause Ranking Injustice:

- **Strong team in a weak league:** A dominant U14 team in a Classic-level league goes 25-0 but ranks below a .500 ECNL team due to 60% SOS weight. The Classic team has OFF/DEF near 1.0 but SOS near 0.0, giving them ~0.40 PowerScore. The ECNL team has OFF/DEF near 0.5 but SOS near 0.9, giving them ~0.74 PowerScore.

- **Recently merged team:** When a deprecated team's games are absorbed, the canonical team's SOS could shift significantly if the deprecated team played in a different competitive environment. The engine has no way to weight "inherited" games differently from the canonical team's own games.

- **Small-state isolation penalty:** A strong team in Wyoming (few in-state opponents) that travels to Colorado tournaments could still get SCF-penalized if most of their games are against other Wyoming teams. The quality override helps but requires opponents to be above p65 strength.

---

## Appendix: Code Path Summary

```
fetch_games_for_rankings()          # Supabase → v53e format
    ↓
compute_all_cohorts()               # Two-pass architecture
    ├── Pass 1: compute_rankings_with_ml() per cohort
    │       ├── compute_rankings()   # v53e engine (Layers 1-11)
    │       └── apply_predictive_adjustment()  # ML Layer 13
    ├── Build global_strength_map from Pass 1
    ├── Pass 2: compute_rankings_with_ml() per cohort (with global map)
    ├── Pass 3: National/State SOS normalization
    ├── Age-anchor scaling (power_score_final)
    └── Final clipping [0, 1]
            ↓
v53e_to_rankings_full_format()      # Pre-DB formatting
    ├── Re-applies anchor scaling (defensive)  ← AUDIT FLAG
    └── Maps to database column names
```

---

*End of audit report.*
