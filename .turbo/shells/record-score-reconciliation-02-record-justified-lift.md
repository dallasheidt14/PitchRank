---
spec: C:/PitchRank/.turbo/specs/record-score-reconciliation.md
depends_on: [record-score-reconciliation-01-down-side-separation]
---

# Plan: Record-justified lift (Stage 2)

## Context

Stage 1's down-pull removes indefensible top teams but, being one-sided, cannot rescue genuinely strong teams buried too low (a 90%-win team at #20; others at #70/#84). This shell adds the **up-side**: a bounded, conservative lift that raises a team toward its record-expected level only when it clears a layered eligibility gate — an absolute win-rate floor **and** a top record quantile within its cohort **and** a positive (record-expected − current) gap — so a losing team can never be lifted. The lift maximum is strictly smaller than the down-pull tolerance (the bigger credibility risk is still wrong teams too high). This completes the two-sided reconciliation; it reuses Stage 1's `record_expected` anchor and frozen-stats snapshot, and the two-sided change makes the prediction backtest load-bearing before ship.

## Produces

- A layered lift-eligibility gate (absolute win-rate floor AND top record quantile AND positive gap), computed from Stage 1's frozen pre-reconciliation snapshot.
- A bounded upward lift toward `record_expected`, asymmetric (maximum strictly smaller than the down-pull tolerance), applied single-pass alongside the down-pull.
- Extended config dials + cache fingerprint for the lift; up-side dials added to `scripts/run_scf_off_staging.py`.
- The two-sided backtest variant + a load-bearing published-score gate, run against the same tree as the candidate.
- Extended `data/staging/audit_ground_truth.py` + `audit_ground_truth.json` encoding a per-elite rise target, so the R10b elite-rise outcome is measurable (the current scorer only tests `cand ≤ --elite-ceiling`).
- Two-sided fixture-gated validation (buried elites rise materially per the extended scorer; losing-in-top-decile never regresses).

## Consumes

- The `record_expected` anchor, the frozen pre-reconciliation cohort-stats snapshot, and the single-pass reconciliation stage — from Shell 1 (record-score-reconciliation-01-down-side-separation).
- The down-side config/cache/harness/backtest scaffolding — from Shell 1 (record-score-reconciliation-01-down-side-separation).
- The Stage 1 down-side contract (R10a: drops cleared, no genuine-elite demotion, guardrails not regressed) — from Shell 1 (record-score-reconciliation-01-down-side-separation); the combined two-sided release must re-verify it still holds.

## Covers Spec Requirements

- R6
- R7
- R8 (partial: lift flag-off byte-identity)
- R9 (partial: lift zero-prod-write validation)
- R10b
- R11 (partial: two-sided published-score backtest, load-bearing)

## Implementation Steps (High-Level)

1. **Lift eligibility gate**
   - Implement the layered gate (absolute win-rate floor AND top record quantile AND positive record-expected − current gap) off the frozen snapshot; verify a sub-floor-record team is never eligible (the losing-in-top-decile guard).
2. **Bounded lift**
   - Raise `powerscore_core` toward `record_expected` for eligible teams, capped at a maximum strictly smaller than the down-pull tolerance; apply single-pass alongside the down-pull (no recomputation).
3. **Config + cache + harness**
   - Add the up-side default-off dials/floats; extend the `_cfg_dict` fingerprint (in `src/rankings/calculator.py`, not the engine file); add the up-side dials to the staging driver; mirror the config tests.
4. **Extend the ground-truth scorer + fixture (R10b measurability)**
   - Extend `data/staging/audit_ground_truth.py` and `audit_ground_truth.json` to score the directional + magnitude elite-rise rule: add a per-elite rise target (a minimum rank improvement, or a reachable top-N) so a buried elite that rises materially but not into the top-15 can PASS. The current scorer only tests `cand ≤ --elite-ceiling`, which cannot express R10b — this must land before R10b is measurable. The per-elite rise targets are **owner-set and pre-registered — committed to the fixture before the Stage 2 sweep begins** (like the `target_min` drop floors), so the success bar cannot drift to fit candidate results.
5. **Two-sided backtest + gate**
   - Extend the backtest variant to the full two-sided mechanism, run against the **same tree** as the candidate (the fork is **gitignored / main-checkout-only**, so copy it into the worktree and keep it in lockstep with the branch engine — do not validate one tree while implementing another); make the published-score-ordering gate load-bearing; confirm the `mu`-invariant check still holds.
6. **Validate + calibrate**
   - Build two-sided candidate boards on one snapshot; calibrate the lift constants (win-rate floor, quantile cutoff, lift max) to clear the **combined R10a AND R10b gate** — every buried elite rises materially to its pre-registered target (R10b) AND the Stage 1 down-side contract still holds (drops stay at/below their floors, no elite demoted, bubble + losing-decile not regressed — R10a); confirm flag-off byte-identity.

## Open Questions

- Calibration constants (lift): the absolute win-rate floor, the top-quantile cutoff, and the lift maximum (strictly < down-pull tolerance) — resolved by the staging sweep at implementation.
- Whether the published-layer lift can raise the deepest buried elites enough to clear the directional + magnitude bar, or whether the deferred `mu`-level lift becomes necessary — answered empirically during validation.

## Expansion Deferred

The following are filled in when `/expand-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path` references with named functions or symbols for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
