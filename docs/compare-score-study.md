# Prospective score comparison

Live Compare's formula and calibration stay unchanged. This private trial compares
its displayed scores with two fixed alternatives on the same upcoming games:

- **25% blend:** keep 75% of the baseline score distribution and mix in 25% of
  the previously fitted attack/defense model's distribution.
- **Blowout-protected candidate:** use the learned score shape while preserving
  the baseline's total probability of a four-goal-or-larger winning margin.

Both preserve every saved win/draw probability and the selected winner exactly.
Missing team/cohort fits retain the complete baseline and count as fallbacks.
Posting sites identify source records; they never enter the model as predictors.

## Flow and dates

1. Register an immutable manifest before the next complete UTC Monday. The
   intended window is **November 23–December 20, 2026**, conditional on setup and
   review finishing beforehand. Otherwise register a later complete four-week
   window; never backdate captures or silently shift a registered window.
2. After successful scheduled current-Compare capture, save all three forecasts
   as one immutable child record. Its parent is the authenticated current
   monitoring forecast, rather than the original study's older predictor.
   Capture must finish before the target's UTC match day begins.
3. Capture runs report errors and fallbacks. Weekly checks report baseline
   coverage and missing current captures or score pairs. Final scores and frozen contexts remain
   unavailable through the study's review function while sealed.
4. Formal review opens no earlier than **January 11, 2027**, and only after every
   overlapping calibration/form/SOS protection permits it. The calibration
   development period remains November 16–December 13 and its final test remains
   December 14–January 10.
5. Review at least **1,000 completed pairs across 20 labeled groups**. A small
   sample produces no adoption decision. No report deploys a candidate.

The original nightly job is scheduled at 04:15 UTC (9:15 PM Arizona on the
preceding date). Current-Compare capture is at 06:20 UTC (11:20 PM Arizona on the
preceding date); successful scheduled runs trigger score capture. Weekly score
coverage/review is Monday 18:00 UTC (11 AM Arizona). GitHub can delay schedules.

## Reproducibility and protections

The registered manifest binds the current monitor and model signatures, committed
execution dependencies, exact private model backup and JSON member hashes, fit
receipt, chronological training cutoff, fixed candidate rules and metric policy.
The collector verifies the backup and training-game digest without extracting or
executing archive members. It resolves teams through each parent's frozen aliases.
New coefficients, code, calibration or candidate rules require a separate study.

The child binds the immutable parent payload hash, rates, eligibility, predictions
and server capture timestamp. Source date, teams, posting-site identity, exclusion
and absent scores are rechecked under lock. Completed children cannot be replaced.
Private report uploads use immutable content hashes and verified readback.

Review matches the baseline's exact source game ID. A changed source date or
identity yields a missing-result limitation rather than another game's score.
Duplicate sources count once; ambiguous same-pair/day records are excluded unless
verified fixture links distinguish rematches. Event groups are verified where
possible, otherwise competition/week groups remain explicitly labeled inferred.

The primary candidate is the 25% blend; the protected candidate remains secondary.
The primary metric is mean absolute error of the **displayed integer goals per
team**. Also report exact scores, displayed-margin error, score log loss,
four-goal Brier score, emitted-winner accuracy, cohort/training-history slices and
coverage. Paired group bootstrap uses 10,000 repetitions and seed 20261123, with
95% intervals and Holm adjustment across the two goal-error comparisons. Report
adverse slices and risk results for a separate release review.

Score log loss uses the declared 0–40 Poisson grid reconstructed from frozen
expected goals and conditioned on the saved win/draw probabilities. It is a
reproducible comparison distribution, not a saved joint score grid from live
Compare. Winner accuracy remains identical on every paired fixture.

## Operator commands

Apply the reviewed `20261116000000_compare_score_study.sql` migration first.
Prepare a private manifest using the committed `source_identity`, candidate
definitions, fixed policy and previously verified model receipt/artifact locator.
Registration verifies that artifact and current baseline without reading outcomes.

```powershell
python scripts/register_compare_score_study.py <private-manifest.json>
python scripts/register_compare_score_study.py <private-manifest.json> --execute
python scripts/capture_compare_score_study.py <registered-signature> --limit 20
python scripts/capture_compare_score_study.py <registered-signature> --limit 20 --execute
python scripts/review_compare_score_study.py <registered-signature>
```

After verifying the pilot, set `COMPARE_SCORE_STUDY_SIGNATURE` to the registered
signature to enable automatic collection. Review preview never reads outcomes or
writes files. `review_compare_score_study.py ... --execute` publishes coverage
while sealed, or the released accuracy report, to the existing private bucket.
Never upload detailed inputs or reports as public Actions artifacts.
