# Handoff: PitchRank Publish-Path Hardening (post-#885 incident)

## TL;DR
The #885 ranking-engine change scrambled published standings; it's been **diagnosed, rolled back, and verified recovered**. A **scoping doc for the long-term publish-path hardening** is drafted, reviewed, corrected, and ready for implementation review. **No hardening code has been written yet** — that's deliberately gated on user go. Next decision: commit/PR the doc, then implement Step 1.

## What's already done (do not redo)
- **Incident diagnosed:** #885 (`SCF_PUBLISH_ONLY` + `TIER_MULT_CENTERED`, commit `7053a4027`) undampened internal `mu`, which fed Layer-13 (re-fit each run on `powerscore_adj`) and the self-referential same-age evidence gates. In a dense cohort a bounded ±0.04 ML move reordered hundreds of teams. Proof: u14F teams that never played still moved a median of **387 ranks**.
- **Rolled back & merged to `main`:**
  - **PR #910** (`8b55346a2`) — added `scripts/ranking_stability_check.py` (publish-path reshuffle detector; non-playing churn / mu→published stage shift / top-100 churn).
  - **PR #911** (`84df45e89`) — set `SCF_PUBLISH_ONLY=False` + `TIER_MULT_CENTERED=False` (flag flip, not a code revert; cache fingerprint forces recompute) + pinned 5 tests that asserted publish-only/centered behavior via the default.
- **Recovery verified** on the 2026-06-16 rerun vs the last sane run (06-08): non-playing churn median **387 → 21**, top-100 new entrants **28 → 4**, mu→published stage shift avg **247 → 133**, Rush Union (`d21d8035-…`, 19-9-2) **#17 → #98**, 30-0-0 back to #3. Both PRs' Codex review threads replied "Fixed in 63677828d" and resolved. Memory updated: `gotcha_engine_ml_feedback_amplification`, `gotcha_ci_no_pytest` (CI now runs pytest).

## Active artifact (center of the work)
`docs/superpowers/specs/2026-06-16-publish-path-hardening.md` — **untracked, uncommitted**. A no-code scoping doc with 4 hardening steps, each carrying problem / code surface / expected behavior / validation / rollback / success criteria / risks, plus cross-cutting **Required Gates** and **Re-enable Criteria** sections. Two reviewer corrections already applied (Step 1 scale-conversion; Step 4 file ref). The reviewer called it "ready for implementation review."

The four steps, in order:
1. **Freeze the evidence-gate reference** (narrow, ships first, `calculator.py` only). `_compute_same_age_evidence_metrics` (~667) + its caller. Open design choice: frozen prior-snapshot power (must un-anchor `power_score_final / anchor_val`; rank from `rank_in_cohort_final`) vs current-run `powerscore_adj` base (scale-correct, partial decouple).
2. **Make `ranking_stability_check.py` a required pre-publish gate** (`.github/workflows/calculate-rankings.yml` + a staging seam).
3. **Reduce positive ML authority** (`layer13_predictive_adjustment.py` `alpha`=0.08 / clamp `ml_norm`) — conditional on 1–2.
4. **Train Layer-13 on raw `mu`** (`layer13_predictive_adjustment.py` ~345–346 `base_power_col`/`power_map`) — last, exploratory.

## Hard invariants / constraints
- **`SCF_PUBLISH_ONLY` stays `False`.** Re-enabling it is a separate final go/no-go gate (see the doc's Re-enable Criteria), never bundled into Steps 1–4.
- **Step 1 must stay narrow** — only the evidence-gate reference freeze, `calculator.py` only, no threshold/gate/ML/SOS/cap edits. Independently shippable.
- Each step ships behind its own config flag (default = current behavior); flip the default only after the stability harness passes. This is the opposite of how #885 shipped.

## Branch / environment hygiene (important)
- `C:/PitchRank` is on **`fix/modular11-events-division-mapping`** with **unrelated dirty + staged work** (config/settings.py, a somsports spec, frontend files, deleted logos, .pyc). **Do NOT bundle** new work into it or unstage/commit that index.
- Per repo CLAUDE.md: for new work, branch/worktree **off `origin/main`** and port the change; never `git stash` with dirty `.pyc`. The earlier `C:/pitchrank-stability` worktree was already removed.
- CI runs `Python Lint` (`ruff check src/ scripts/` — not `tests/`) + `Python Tests` (`pytest tests/ … --ignore=test_enhanced_pipeline.py`, ~11 min). Run the full unit suite locally before pushing engine changes.
- The stability script also exists as an untracked copy in this checkout at `scripts/ranking_stability_check.py` (canonical is on `main` via #910). Run it from `C:/PitchRank` (has `.env`/`DATABASE_URL`): `python scripts/ranking_stability_check.py --age u14 --gender Female --prev-date <YYYY-MM-DD>` (requires `--age` and `--gender` together).

## Open decisions
1. **Commit the scoping doc?** — commit on a clean branch off `main` + open a PR for review, or leave local. (Asked, unanswered.)
2. **Step 1 frozen-reference choice** — prior snapshot (un-anchored) vs current-run base. Settle in implementation review.
3. SCF_PUBLISH_ONLY re-enable — out of scope until Steps 1–2 land and the full re-enable gate passes.

## Next concrete action
Decide whether to commit `docs/superpowers/specs/2026-06-16-publish-path-hardening.md` on a clean branch off `main` and open a PR (no code), or keep it local — then, on the user's go, implement **Step 1 only** (freeze the evidence-gate reference, `calculator.py`, behind a flag, off a clean branch from `main`), validate with `scripts/ranking_stability_check.py`, and stop. Do not touch `SCF_PUBLISH_ONLY`.
