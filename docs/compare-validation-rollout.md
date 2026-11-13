# Compare evidence and prospective validation

The Compare card shows all three outcome probabilities, a projected scoreline,
supporting factors, up to two opposing factors and concise limited-history cautions.
Detailed game counts, sample sizes and dates remain available in the API evidence
summary and frozen validation inputs; the card omits that diagnostic panel. Evidence
uses cleaned games in the 365-day window and up to eight recent games for form.
These presentation changes do not adjust production probabilities, ranking scores,
or scoreline calculations.

## Release order

1. Capture and settlement: immutable ledger, database fixture intake, bounded worker,
   opt-in daily workflow and PostgreSQL integration tests.
2. Evidence UI: shared evidence summary, balanced explanations and baseline parity tests.
3. Validation: immutable experiment registration, sealed holdout and offline calibration
   report. Apply this migration before the first pilot capture.

Merge the reviewed PRs and deploy both migrations through the normal database release
process before running the pilot. Keep the repository variable `COMPARE_CAPTURE_ENABLED`
unset or `false` until the pilot checks below pass. Applying code alone does not enable
capture, promote a calibrator or change the rankings pipeline.

## Pilot and activation

The commands below assume the normal Supabase URL and service-role environment is
configured. Never put credentials in command arguments or save them in report artifacts.

1. Apply `20261111000000_guard_prospective_forecasts.sql` and
   `20261111010000_register_compare_experiments.sql` in that order. They protect the
   existing ledger and create `compare_calibration_experiments`; they do not backfill
   forecasts or modify `games`.
2. From the repository root, preview intake:

   ```sh
   python scripts/prepare_prospective_match_predictions.py --database --limit 20
   ```

   Inspect selected, skipped and provider/cohort coverage. Eligible fixtures are
   unscored, nonexcluded, resolved to distinct teams with current ratings, and dated
   1–7 UTC days ahead. An empty preview is a coverage gap, not proof that predictions
   work. The default preview writes neither database rows nor summary files.
3. Dispatch **Daily Prospective Forecast Capture** manually with `limit=20` and
   `execute=true`. The first step inserts eligible ledger rows; the second freezes
   current Compare forecasts. A dispatch with `execute=false` previews intake and
   predicts only previously prepared pending rows, since it cannot insert new rows.
4. Inspect the run's intake and capture summary artifacts. Require zero unexpected
   errors, no deadline exhaustion, and completed forecasts for the selected eligible
   fixtures. Investigate skipped or changed fixtures before activation. Record the
   exact captured ledger IDs from the capture summary's `frozenIds` and verify them read-only:

   ```sql
   SELECT id, source_game_id, game_date, heuristic_predicted_at,
          heuristic_model_version, heuristic_prediction_status,
          heuristic_prediction->>'modelSignature' AS signature,
          heuristic_prediction->>'codeRevision' AS code_revision,
          heuristic_prediction#>'{shadowContext,preOutcomeCalibration}' AS raw_probabilities,
          jsonb_array_length(heuristic_prediction#>'{shadowContext,frozenEvidence,games}') AS frozen_games
   FROM public.prospective_match_predictions
   WHERE id = ANY (:pilot_ids);

   SELECT * FROM public.compare_calibration_experiments
   WHERE model_signature = :pilot_signature;
   ```

   Bind `:pilot_ids` from `frozenIds`; use the first query's signature for the manifest
   query. Require nonempty signature and revision,
   matching versions, frozen inputs/calibration, three raw probabilities, and
   `heuristic_predicted_at` before the fixture's UTC date. Repeating the same capture
   must leave those completed payloads and timestamps unchanged. A second intake may
   discover different fixtures; compare the recorded pilot IDs rather than row totals.
5. Set `COMPARE_CAPTURE_ENABLED=true` after verification. Daily capture at 04:15 UTC
   rotates providers and cohort/history strata in both intake and forecast capture,
   orders dates and stable hashes within each stratum, caps each stage at 500,
   uses at most four workers and stops taking work after 45 minutes. In-flight work
   finishes; the job's outer timeout is 60 minutes. Monitor skipped/error counts and
   provider/cohort coverage in the 90-day summary artifacts.

Completed forecasts are immutable, including their fixture identity. Pending/error
rows can be retried. Source changes, partial scores, missing identities and same-day
cutoffs prevent capture. Review held rows rather than resetting completed forecasts.

## Settlement

The weekly workflow retries pending and previously missing results, up to 5,000 rows.
Retries start with the least recently updated rows so missing results cannot permanently
occupy the batch. Database fixtures settle against their original `games.id`; canonical team aliases
allow a verified merge or reversed orientation. Changed dates, unrelated teams,
changed source links, excluded results and unresolved duplicate fixtures are held for review. No similar
match is substituted. The ledger preserves the original identities even if team
cleanup deletes a deprecated team row.

For a bounded manual preview, then an explicitly requested write:

```sh
python scripts/settle_prospective_match_predictions.py --status unsettled --limit 20
python scripts/settle_prospective_match_predictions.py --status unsettled --limit 20 --execute
```

Settlement can change result fields without changing the saved prediction. Check held
status counts and exact source IDs before reporting coverage. A missing or excluded
result is unavailable evidence, not a loss, draw, or zero-goal game.

## Registered experiment and report

The first completed capture of each algorithm/calibration signature atomically registers
its manifest. The next complete UTC Monday begins four weeks of development, followed
by four weeks of holdout. Windows, thresholds, temperature grid, bootstrap seed and
probability source are immutable. Changing predictor source or calibration creates a
different signature and experiment; these signatures are never pooled. A cosmetic
edit to a hashed predictor module also starts a different signature, so schedule such
changes deliberately while collecting.

Run the report from the repository root into a new directory:

```sh
python scripts/benchmark_compare_calibration.py --experiment-signature SIGNATURE --output-dir reports/compare-RUN
```

This reads the manifest and settled ledger rows without writing to the database.
Before the holdout closes, it emits coverage and `collecting` status only. The weekly
legacy evaluation also excludes registered forecasts. After the final holdout UTC date,
the report requires at least 1,000 games and 20 groups in **each** window; otherwise it
reports insufficient data. Do not extend the same manifest after inspecting outcomes.

Candidates apply scalar temperatures `[0.5, 0.75, 1, 1.25, 1.5, 2]` to the frozen
probabilities before the final outcome-calibration blend. Development log loss chooses
one temperature. The baseline is the original final probability vector. Winner choices,
goal margins and four-goal risk predictions remain fixed for this experiment.

The report includes log loss, multiclass Brier score, calibration, draw metrics, margin
and score errors, four-goal risk coverage and provider/cohort/history/gap slices. A
candidate needs lower Brier score and an upper 95% paired group-bootstrap log-loss delta
below zero (1,000 resamples, seed `20260920`). Advancement also requires the current
model version and complete four-goal probability coverage in the holdout. Passing these
gates earns further shadow validation. Any production calibration change requires its
own review.

Verified event IDs form groups. Without one, provider/competition/ISO-week groups are
explicitly marked inferred. Groups crossing the development/holdout boundary are
excluded. Repeated teams can still create dependence; the capped provider sample does
not support a nationwide accuracy claim.

Archive the completed directory, including the manifest, input hash, frozen ledger
inputs and CSV/JSON/Markdown outputs. To reproduce offline, pass `--manifest` with
`manifest.json` and `--input` with `frozen_inputs.json` into a new output directory.
Manifest files require frozen input files; live reads always use the database's manifest.
Legacy version/date arguments remain available for historical research, but cannot
override a registered experiment's policy or establish prospective performance.

## Rollback

Unset `COMPARE_CAPTURE_ENABLED` to stop scheduled capture. Pause manual execution too.
Keep completed forecasts and experiment manifests intact; rollback never deletes or
relabels evidence. Revert the UI independently if needed. Do not remove the ledger
guards to retry a capture, and do not promote an offline calibration report automatically.
