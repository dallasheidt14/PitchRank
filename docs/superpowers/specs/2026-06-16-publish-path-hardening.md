# Publish-Path Hardening — Scoping Doc

**Date:** 2026-06-16
**Status:** Draft for review. No implementation until approved.
**Hard invariant:** `SCF_PUBLISH_ONLY` stays `False` for every step below. Re-enabling it is **not** part of any scoped change — it is a separate final decision gate (see *Re-enable Criteria*).

---

## Context

The #885 incident (publish-only SCF undampening `mu`) scrambled the published standings; u14F teams that never played still moved a median of 387 ranks. It was rolled back in #911 and the pre-#885 baseline was restored (non-playing churn 387 → 21, top-100 churn 28 → 4, Rush Union #17 → #98).

The rollback restored the *old* system, not a *good* one. The baseline still carries the structural weakness that made #885 so destructive: the published ordering is over-leveraged on the Layer-13 ML overperformance term and on a stack of evidence gates that re-price off the **current run's own output**. That makes the standings (a) partly decoupled from team strength and (b) hypersensitive to any engine input change.

**Goal:** reduce that leverage in the smallest independently-shippable steps, each validated by the stability harness, without a redesign. Each step ships behind its own config flag (default = current behavior) so it is reversible and so the behavior flip is itself gated on harness evidence — the opposite of how #885 shipped.

**Pipeline recap (for reference):**
`mu` → engine `compute_rankings_v2` (SOS scale, evidence scale, `provisional_mult`) → `powerscore_adj` → Layer-13 (`powerscore_ml = powerscore_adj + alpha*ml_norm`, XGBoost re-fit each run) → calculator SOS-conditioned ML scaling + same-age evidence gates / raw-shrink / publish-penalty / publication-cap → `power_score_true` → `power_score_final` → `rank_in_cohort_final` (the published rank).

---

## Step 1 — Freeze the evidence-gate reference (narrow, ships first)

**Problem being addressed**
`_compute_same_age_evidence_metrics()` builds its opponent rank/power lookups (`base_rank_lookup`, `base_power_lookup`) from the **current run's** `powerscore_adj`. Every downstream consumer of those metrics (evidence gates, raw-shrink, publish-penalty, publication-cap) therefore moves whenever the current run's pricing moves. An engine change perturbs `powerscore_adj`, which silently shifts the gates and caps in the same run — a self-referential amplifier with no stable anchor.

**Exact code surface / files touched (ONLY this)**
- `src/rankings/calculator.py`:
  - `_compute_same_age_evidence_metrics()` (~line 667): replace the two lookups derived from `teams_work["powerscore_adj"]` with reads from a passed-in frozen reference map.
  - Its single caller (in `compute_all_cohorts`): build the frozen reference once and pass it in.
- No other file. No threshold, gate-logic, ML, SOS, cap, or SCF change.

**One design decision to settle in review (does not widen scope):** what the frozen reference *is*, and on what scale.
- **Recommended:** the prior published snapshot (`ranking_history`, keyed by `team_id`), which is stable against the current run's repricing. **Scale is load-bearing.** The live metrics read *unanchored* `powerscore_adj` (calculator.py ~703) and test it against fixed thresholds (calculator.py ~321: `severe_min_avg_opp_power`, `thin_schedule_max_avg_opp_power`, `play_up_min_avg_opp_power`), but `ranking_history` stores *anchor-scaled* `power_score_final` (ranking_history.py ~137). So Step 1 must take prior **rank** from `rank_in_cohort_final`, and convert prior **power** back to an unanchored score before use (un-apply the anchor, e.g. `power_score_final / anchor_val`, or read `power_score_true` if the snapshot carries it). Without this, `same_age_avg_opp_power_adj` / `play_up_avg_opp_power_adj` are fed the wrong scale and the fixed thresholds silently retune the gates, which would break the "no threshold/gate change" guarantee. Fall back to the current run's `powerscore_adj` **only** for teams absent from the snapshot.
- **Alternative:** the current run's pre-ML base (`powerscore_adj`) captured once. Already on the correct unanchored scale (no conversion needed), simpler, no lag, but it still moves with engine changes, so it only partially decouples.

**Expected behavior change**
Evidence metrics (top-100/top-500 opponent counts, avg opponent power, etc.) become a function of a stable reference, not of the in-flight ordering. A future engine change no longer moves the gates/caps within the run that introduces it. On a steady-state week the published output is materially unchanged.

**Validation plan**
- Run `scripts/ranking_stability_check.py` on a re-run with the flag on vs off; non-playing churn and top-100 churn must not regress.
- Backtest log-loss/accuracy unchanged within noise (this step is not a scoring change).
- Spot-check: re-run with a deliberately perturbed engine input (e.g., toggle a minor SOS constant) with flag off vs on; confirm gate-driven cap/penalty assignments are far more stable under the frozen reference.

**Rollback path**
Single config flag (e.g. `EVIDENCE_GATE_FROZEN_REF`, default `False`). Flip off → exact current behavior. No data migration; cache fingerprint includes the flag so a re-run cleanly recomputes.

**Success criteria**
- With the flag on, a perturbed-input re-run shows gate/cap churn reduced (target: gate-assignment flips cut by majority vs the live-reference path).
- Steady-state published top-N unchanged within normal weekly drift.
- Stability harness: no FAIL introduced.

**Risks / failure modes**
- Prior-snapshot reference lags one run; a team's real strength change is reflected in gates one cycle late (acceptable; converges). Cold-start teams need the documented fallback or they get no evidence credit.
- If the alternative (current-run base) is chosen, decoupling is partial — must be stated honestly, not oversold.

**Independently shippable:** yes. Delivers value (kills the self-referential amplifier) even if Steps 2–4 never land.

---

## Step 2 — Make `ranking_stability_check.py` a required gate

**Problem being addressed**
Nothing currently blocks a scrambled run from publishing. #885 reached production because validation was engine/`mu`-scope only and the end-to-end publish-path check was optional and skipped.

**Exact code surface / files touched**
- `.github/workflows/calculate-rankings.yml`: add a post-compute, pre-publish step that runs `scripts/ranking_stability_check.py` against the staged result and fails the job (blocks publish) on a FAIL verdict.
- `src/rankings/calculator.py` (or the run entrypoint): a staging seam so the stability check can read the new run **before** it becomes the live `rankings_full` (e.g., write to a staging table / dry-run artifact, publish only on pass). If a full staging seam is judged too large, the fallback is post-publish detection + alert + one-command rollback (smaller, but detection not prevention — call this out for the decision).
- `scripts/ranking_stability_check.py`: minor — accept a target/staging source argument; no logic change.
- CI (`ci.yml`): no full ranking run on PRs; engine-touching PRs instead require the harness to have been run on a branch re-run and its output attached (see *Required Gates*).

**Expected behavior change**
A run whose published standings reshuffle beyond thresholds cannot auto-publish. Engine changes carry a mandatory stability artifact.

**Validation plan**
- Replay the #885 run through the gate: it must FAIL and block.
- Replay the 06-16 rollback run: it must PASS.
- Dry-run the workflow on a no-op re-run: PASS, publishes normally.

**Rollback path**
Gate is additive. Disable by reverting the workflow step / env toggle (`STABILITY_GATE_ENFORCE=0` → warn-only). No engine behavior change.

**Success criteria**
- #885-shaped run is blocked pre-publish in a replay.
- Normal weekly run publishes unimpeded.
- Gate runtime acceptable within the existing job budget.

**Risks / failure modes**
- Staging seam is the scope risk; if it balloons, fall back to detection+alert (explicitly weaker) rather than widening this step.
- Threshold calibration: too strict blocks legitimate high-movement weeks (season starts). Thresholds live in the harness and are tunable; start permissive, tighten with data.

---

## Step 3 — Reduce positive ML authority (conditional on 1–2)

**Problem being addressed**
`power_score_final ∝ powerscore_adj + alpha*ml_norm` with `alpha=0.08` and `ml_norm ∈ [−0.5,+0.5]`, so the ML term swings ≈±0.04 — comparable to the entire `powerscore_adj` spread of a dense top cohort, letting modest overperformance reorder many teams. Only attempt if Steps 1–2 don't sufficiently de-leverage.

**Exact code surface / files touched**
- `src/rankings/layer13_predictive_adjustment.py`: `alpha` (line 61) and/or a clamp on positive `ml_norm`.
- Possibly `src/rankings/calculator.py` SOS-conditioned ML scaling block (~2954–3104) if the positive-authority cap is applied there instead.
- No change to residual computation or feature set (that is Step 4).

**Expected behavior change**
Overperformance moves teams less; published order tracks `powerscore_adj` (strength + schedule) more closely. Upset-prone mediocre-record teams sit lower.

**Validation plan**
- Backtest: log-loss/accuracy must not meaningfully degrade (this is the real tension — ML authority helps prediction; we are trading a little prediction for defensibility, per the recorded accuracy definition).
- Stability harness: stage-shift (`mu` → published) should drop.
- Cohort spot-checks across ages/genders for defensibility.

**Rollback path**
`alpha` / clamp are config; revert to current values. Cache fingerprint includes them.

**Success criteria**
- mu→published stage shift reduced vs baseline.
- Backtest degradation within an agreed tolerance.
- No new FAIL in the harness.

**Risks / failure modes**
- Over-trimming ML re-introduces the very prediction weakness Layer-13 was added to fix. Must be a measured trade, not a blanket cut.

---

## Step 4 — Train Layer-13 on raw `mu` (last)

**Problem being addressed**
Layer-13 features `team_power`/`opp_power` are `powerscore_adj` (`power_map` / `base_power_col`, `layer13_predictive_adjustment.py` ~345–346). So the ML model trains on the publish-side score and re-fits every run on a moving target. Training on raw `mu` decouples the model from publish-stage churn.

**Exact code surface / files touched**
- `src/rankings/layer13_predictive_adjustment.py` (~345–346): the feature-source selection (`base_power_col` / `power_map`) lives here — change it to source model features from raw `mu` (or a fixed transform of it).
- Same file's `_build_features`: rescaling/handling if the input domain changes (`mu` is ~1500-centered, not `[0,1]` like `powerscore_adj`).
- Model is re-fit per run regardless, so no stored-model migration.

**Expected behavior change**
The residual model's inputs stop moving with publish-side adjustments; `ml_norm` becomes a cleaner overperformance signal relative to raw strength. Does **not** by itself fix the evidence-gate self-reference (that's Step 1) — sequenced last for that reason.

**Validation plan**
- Backtest: confirm prediction quality holds or improves with `mu`-based features.
- Stability harness on a re-run.
- Compare `ml_norm` distributions before/after for sanity.

**Rollback path**
Config flag selecting the feature source (`mu` vs `powerscore_adj`); flip back. Cache fingerprint includes it.

**Success criteria**
- Prediction metrics hold within tolerance.
- `ml_norm` no longer co-moves with publish-stage perturbations.
- No new harness FAIL.

**Risks / failure modes**
- `mu` and `powerscore_adj` live on different scales; feature rescaling needed or the model degrades. Lower confidence than Steps 1–3; treat as exploratory.

---

## Cross-cutting: Required Gates

What `scripts/ranking_stability_check.py` must prove, and when.

**Before merge (any engine/publish-path PR, Steps 1–4):**
- A branch re-run with the change ON vs OFF, harness output attached to the PR.
- Non-playing-team churn: **no regression** vs the OFF run (median stays in baseline range, currently ~20s for an 8-day comparison; ~0 for an adjacent same-engine run).
- Top-100 churn: no new FAIL.
- For scoring steps (3, 4): backtest log-loss/accuracy delta attached and within the agreed tolerance.

**Before publish (every production run, after Step 2 lands):**
- Harness runs on the staged result vs the prior snapshot and returns **0 FAIL**.
- A FAIL blocks publication (or, in the fallback design, fires an alert and arms one-command rollback).
- The mu→published stage-shift metric is logged every run for trend tracking even when it passes.

---

## Cross-cutting: Re-enable Criteria (SCF_PUBLISH_ONLY go/no-go)

`SCF_PUBLISH_ONLY` stays `False` until **all** of the following hold. This is a deliberate, separate decision — never bundled into Steps 1–4.

**Go (all required):**
1. Steps 1 and 2 merged and in production (evidence-gate reference frozen; stability gate enforcing pre-publish).
2. A full end-to-end `compute_all_cohorts` re-run with `SCF_PUBLISH_ONLY=True` on a branch, diffed against the live baseline, through the **publish path with Layer-13 in the loop** (the validation #885 skipped).
3. Harness on that re-run: non-playing churn and top-100 churn within thresholds (no scramble), stage-shift not materially worse than baseline.
4. Bubble guardrail re-verified at **publish** scope (not just engine/`mu`): isolated weak-schedule teams stay out of the top ranks.
5. Backtest still shows the prediction gain that motivated #885, AND defensibility spot-checks pass per the recorded accuracy definition.

**No-go (any one):**
- Any harness FAIL on the candidate re-run.
- Defensibility regression in cohort spot-checks (e.g., undefeated isolated teams or mediocre-record teams surfacing in the top tier).
- Step 2's pre-publish gate not yet enforcing.

**Decision owner:** Dallas. The re-enable is a single, explicit go/no-go review with the above evidence on the table — not a default flip.

---

## Sequencing summary

1. **Step 1** ships alone, first (narrow, reversible, kills the self-referential amplifier).
2. **Step 2** next (gate must exist before any further scoring change is trusted).
3. **Step 3** only if 1–2 leave residual over-leverage; measured trade vs prediction.
4. **Step 4** last; exploratory, lower confidence.
5. **SCF_PUBLISH_ONLY re-enable** considered only after 1–2, as a separate gated decision.
