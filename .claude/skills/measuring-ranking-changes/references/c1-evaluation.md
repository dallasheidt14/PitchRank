# C1: connectivity information for ceiling decisions only

C1 is an offline experiment. It restores the existing connectivity calculation only while the
publication ceiling is decided. Every earlier score must equal the October candidate exactly.
The ordinary API default is false. The original C1 worktree refuses live fetching and
persistence. The combined release permits these operations through the production entry
point; the measurement harness independently blocks all live reads and writes.

The experimental branch also contains the two recorded October-candidate edits: SCF's code default
is false, and the convergence gender mask uses the detected cohort gender. These are dependencies
of the comparison, not additional C1 changes. This branch is not authorized for deployment.

## Capture and verify

Run the reconstructed October candidate twice with the same immutable capture tooling, training
freeze, runtime and environment. Then run C1 with both flags:

```text
python shadow_harness.py board --code-root C1_ROOT --freeze TRAIN_FREEZE --out NEW_RUN --capture-stages --ceiling-connectivity
python c1_validation.py --base BASE_RUN --cand C1_RUN --freeze TRAIN_FREEZE --out NEW_BOUNDARY_REPORT.json
```

Use `--capture-stages` without `--ceiling-connectivity` for both baseline repetitions. Capture
receipts cover every engine pass, selected-game multiplicity, warm starts, ML outputs, upstream
helper calls and pre-cap frames. C1 saves its diagnostics separately. The validator refuses missing
or altered captures and exact upstream differences. `--allow-legacy-base` is only for reproducing
an older archived baseline without stage captures; the C1 scorer never uses that exception.

Compare all final team columns as well for baseline-versus-baseline reproduction. The C1 boundary
validator intentionally permits post-cap scores and ranks to differ, so it alone cannot establish
that two baseline runs had identical final rankings.

## Lock before looking at evaluation outcomes

Implementation is not an experimental lock. September influenced the design and can only supply
descriptive evidence. October is eligible only if its outcomes have not informed C1's design when
the design is locked. Otherwise select the next untouched full month before accessing its outcomes.

The C1 scorer requires a JSON lock with these fields. Create the actual record only when the design
and comparisons are final and the untouched-outcomes statement is justified:

```json
{
  "locked": false,
  "outcomes_unseen_at_lock": false,
  "locked_at": null,
  "profile": "c1",
  "start": null,
  "end": null,
  "rules": {
    "gain": 0.25, "alpha": 0.05, "board_harm": -1.0, "cut_scf": 0.6,
    "cut_min_games": 300, "cut_estimate": -1.0, "cut_lower": -2.0
  },
  "engine_file_sha256": {"base": {}, "candidate": {}, "reference": {}},
  "scorer_sha256": {},
  "training_manifest_sha256": null
}
```

Use a timezone-aware UTC lock time; copy each role's `engine_file_sha256` from its run provenance.
The reference is the SCF-enabled incumbent on the same freeze. Record SHA-256 hashes of
`score_later_games.py`, `score_c1.py`, `c1_validation.py` and the training `freeze-manifest.json`.
The template deliberately fails the lock gate.

## Evaluate in the declared order

First score the October candidate against the incumbent using the original locked comparison and
candidate family. Add `--record-evaluation` to the existing legacy command to bind the report to
its training freeze, evaluation period, held-out games and completed runs. This option does not
change any legacy metric or decision rule. Apply the original out-of-state subgroup condition to
the combo candidate using its existing candidate name and `--scf-cand` value.

Then, and only if that comparison validly passed, use:

```text
python score_later_games.py --profile c1 --base OCTOBER_CANDIDATE_RUN --cand c1=C1_RUN --isolation-reference INCUMBENT_RUN --prerequisite-report FIRST_STAGE.json --design-lock C1_LOCK.json --train-freeze TRAIN_FREEZE --heldout-freeze EVALUATION_FREEZE --start START_DATE --end END_DATE --out NEW_C1_REPORT.json
```

Invalid evidence produces `void` and a nonzero exit. A failed or inconclusive first stage produces
`not_evaluated` without reading held-out games for C1. An evaluated comparison checks harm before
pass, otherwise reports inconclusive. All 18 boards must have defined estimates for a pass.

The isolation group comes from the separate incumbent's SCF values, not from C1 or its comparison
baseline. It includes a game once when either team has SCF below 0.6 and both states are known and
different. A sample below 300 or an interval extending below -2 points blocks a pass; the estimate
must also be at least -1. Credible harm takes precedence even for a small sample.

Report U10 boys, U10 girls and pooled U10 games separately. An overall gain does not establish a
U10 improvement. No scorecard automatically authorizes adoption.

## Combined release

Use `--profile ceiling-release` for the complete release versus the unchanged October
combination. C1 alone remains diagnostic. The original first-stage test stays unchanged.
The new profile reuses all C1 statistics, thresholds and prerequisites, then vetoes a pass
if a board or isolation subgroup has a 95% upper bound below -1 against the incumbent.
Missing cumulative statistics are inconclusive. This safety comparison is not another
improvement hypothesis. The lock must identify profile `ceiling-release` and include
`comparisons` exactly as `score_c1.RELEASE_COMPARISONS` defines it, along with all
the hashes above. The C1 lock cannot be reused. September remains descriptive.
