# Fixed winner confirmation

This private study compares current Compare with one fixed weighted version on the
same future fixtures. It changes no public predictions. It is separate from the
calibration, opponent-adjusted form and score studies; their manifests, samples,
review rules and collector revisions stay intact.

The initial weights come from exposed retrospective research, not a qualified
historical form experiment. They are recorded in a private immutable manifest
with hashes of the research receipt and training data. No fitting occurs during
capture. Do not register already-played replay outputs as prospective forecasts.

## Collection and review

Register before the next complete UTC Monday. The target window is that Monday
through the fourth Sunday. Review cannot open before January 11, 2027, and also
honors every existing date-wide experiment restriction. Finishing the sample
early never advances the review date. Late or insufficient collection gives no
adoption decision.

The `Compare Winner Study` action runs independently after successful scheduled
`Compare Live Monitoring` runs. Its `COMPARE_WINNER_STUDY_SIGNATURE` repository
variable selects the immutable private manifest. It resolves the registered code
revision and verifies committed dependency hashes for capture and review. Manual runs preview by default;
`execute` explicitly enables capture or private report preservation. The weekly
Monday run saves coverage reports while results are sealed.

For each fixture, the collector replays the frozen current Compare inputs, clock
and effective calibration, including explicit defaults. Both the unmodified
predictor and the research version with all multipliers at one must reproduce
every saved baseline output exactly. The fixed multipliers then produce the
challenger's probabilities, winner, score, margin and four-goal risk. No target
results are read during capture.

Replay runs in memory, including previews. Failed rows do not block later queue
pages; each invocation scans at most ten times its requested capture limit, up to
5,000 fixtures. Errors and a reached scan limit remain visible in its summary.

The database supplies capture timestamps, refuses captures once the UTC match day
begins, rechecks the exact original source fixture and rejects already-scored or
excluded games. Records cannot be changed or replaced. Coverage reports include
missing current Compare and challenger forecasts. A failed child does not block
the independent score collector. A posting site identifies a source; it is never
a model feature or an explanation of an outcome.

After release, comparison uses exact original source results, removes duplicate
or ambiguous fixtures and verifies event groups, labeling inferred groups. The
source audit includes later imports and aliases outside the captured sample.
Released reports retain capture gaps separately from result exclusions.
Qualification requires at least 1,000 settled pairs and 20 groups, a positive lower
95% paired group-bootstrap accuracy difference, and no worse log loss or Brier
score. Draw calibration, margin error, four-goal risk and age/history/ranked/cohort
slices accompany the report. Adverse slices and risk require release review.
Qualification never automatically promotes a candidate.

## Commands

From the registered checkout, install the Python dependencies and run
`npm ci --prefix frontend`. Credentials come from the existing private environment; never commit
them or saved match contexts.

```text
python scripts/register_compare_winner_study.py PRIVATE_MANIFEST [--execute]
python scripts/capture_compare_winner_study.py SIGNATURE --limit 20 [--execute]
python scripts/review_compare_winner_study.py SIGNATURE [--execute]
```

Apply only the additive winner-study migration after review. Enable its variable
after registration, verify a pregame pilot and repeat capture, then inspect the
first scheduled run. To stop collection, clear only the winner-study variable.
Preserve all forecasts and manifests during rollback. The live predictor modules
and calibration signatures remain unchanged.
