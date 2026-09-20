# Compare prediction benchmark

Run this before proposing a probability-calibration change. It reads frozen
prospective forecasts and settled results; it never retrains ratings, fetches
current team inputs, changes production predictions, or deploys a calibrator.

```powershell
python scripts/benchmark_compare_calibration.py --input frozen-forecasts.json --model-version heuristic_v3_shadow_ready --train-end 2026-04-12 --test-start 2026-04-17 --test-end 2026-04-19 --output-dir .turbo/validation/compare-experiment-001
```

Without `--input`, it reads settled `prospective_match_predictions` rows using
the normal Supabase environment. JSON input must be an array of those records.
Use a new output directory each time. Keep source data and generated reports
local; the public repository should contain tests and tooling, not raw exports.

## Evidence rules

- One predictor version per experiment; row, payload, and canonical snapshot
  versions must agree. A custom version label cannot hide a predictor upgrade.
- Match both fixture sides to the frozen forecast's team identities, allowing
  aliases recorded in that snapshot. Exclude later corrections to different teams.
- A forecast must have completed before the game's calendar day in UTC. With no
  kickoff time stored, same-day forecasts cannot prove that they preceded play.
- Require settled integer scores, valid three-way probabilities, a finite expected
  margin, and game/fixture/event identities. Report exclusions explicitly.
- Count each actual game once, retaining its earliest eligible frozen forecast.
- Exclude an entire event from both partitions if it spans development and holdout.
- Require at least 200 games and three events in each partition before selecting
  a candidate. These are screening floors, not proof of broad representativeness.
- Select temperature by development log loss only. Inspect the later holdout once;
  further tuning based on that report requires another untouched test set.

## What the experiment changes

Temperature rescales the three recorded outcome probabilities symmetrically:
below 1 sharpens them; above 1 softens them; 1 is the unchanged baseline. The
outcome-selection policy, score, expected margin, and four-goal risk stay frozen.
This neither reconstructs uncalibrated probabilities nor reruns the current Compare
model, so it cannot establish whether removing its prior blend would help.

`benchmark.json` records the input digest, dates, source/current versions,
coverage, exclusions, development candidates, and holdout results. The selected
candidate is evaluated against the baseline on identical games. The uncertainty
interval resamples entire events, preserving within-tournament dependence.

The report includes winner accuracy, log loss, multiclass Brier score, margin
error, and available four-goal risk metrics. Reliability tables include each
outcome and four-goal risk, including probabilities below 50%. Missing risk values
remain unavailable. Compare the observed blowout rate with predicted risk on
the same rows, not the complete population when coverage differs.

Holdout slices cover cohort, gender, same/cross-age matches, limited history,
PowerScore gaps, and events. Age/cohort and gender slices use team A's frozen
predictor inputs; refreshed roster labels cannot relabel a forecast. Unknown
metadata stays an explicit group. A cross-age pairing alone does not identify
the tournament's playing-up assignment.

## Release decision

An old model version, missing four-goal forecasts, insufficient coverage, or no
supported probability-score improvement prevents a positive candidate status.
Even `candidate_for_shadow_validation` means only a candidate for further testing.
Inspect cohort coverage and regressions, verify relevance to current inputs, and
collect fresh pre-game forecasts before proposing a production change. None of
these commands restarts the paused prospective scraping workflow.
