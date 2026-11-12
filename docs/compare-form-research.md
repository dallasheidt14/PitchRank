# Compare form research

Research is offline. The collecting predictor is pinned to
`866f30c73a84524028b9fe8e55b3108ec8d544fc`; its seven hashed modules must match
before the TypeScript runner starts. Neither command changes database rows,
rankings, calibration, or the capture schedule.

## Historical eligibility

Development targets are August 17–October 11, 2026; evaluation targets are
October 12–November 8. Each period needs 1,000 distinct fixtures and 20 groups.
Source fixture IDs deduplicate mirrored examples. Verified event IDs should form
groups; otherwise supply an explicitly inferred provider/competition/UTC-week
group and retain that origin in the fixture metadata. Groups crossing periods
are excluded.

Run the live, read-only aggregate inventory from a configured environment:

```sh
python scripts/benchmark_compare_form.py --database-audit
python scripts/benchmark_compare_form.py --database-audit --execute --output-dir reports/form-inventory-RUN
```

The first command writes no files. `--execute` saves local artifacts only. Output
directories must be new. This inventory is not a historical fixture eligibility
report: disjoint weekly queries group target database rows by period, provider,
recorded game age group, and the smaller team's snapshot-reported game-count band.
It reports exclusions, missing scores/source identities, unmatched teams, and unavailable
snapshots. Snapshot labels, creation times, and calculation times must all precede
the target's UTC match day. These are inventory labels, not verified usable form
samples; overlapping failure counts and duplicate source rows are explicit.
Verified eligibility remains zero until lineage is established. The audit stops
before exporting millions of feature rows when their lineage is unresolved.

The November 11 inventory found 2,906,893 development-window snapshots and
2,441,212 evaluation-window snapshots. The snapshot schema does not contain a
training-run reference, training cutoff, or calibration signature. The separate
`model_training_runs` records describe offline match models and cannot establish
the lineage of ranking features. These counts are snapshot rows, not eligible
matches. No historical candidate has been selected from this inventory.

The bounded target audit counted 306,945 development-period database rows across
17 providers and 156,196 evaluation-period rows across 15 providers. Before source
deduplication, overlapping limitations include 25,975 excluded rows, 86,300 rows
without scores, 290 rows with unmatched teams, and 118,741 rows without both
timestamp-qualified snapshots. No row is certified eligible while lineage remains
unresolved. The saved JSON retains weekly provider/age/history breakdowns.

To proceed, supply an immutable external lineage manifest linking exact snapshot
hashes to their source artifacts and training cutoffs, or collect that provenance
for future snapshots. Do not infer it from today's model or the snapshot's label.
Historical result availability must also be established: a fixture's original
creation timestamp does not prove when its final score became known.

No older external archives are known. The recoverable Supabase backups begin on
November 4, so they cannot recover the original development period. That study
remains insufficient. A separately registered future study can collect the missing
evidence without changing the historical windows or the calibration experiment.

## Dataset from private forecast archives

After the archive migration, publication workflow, and separate study registration
are enabled, use the existing server credentials and management access token.
Download the study by its registered manifest hash, then preview or export:

```sh
python scripts/download_compare_archive.py STUDY_MANIFEST_SHA --execute --output-dir .turbo/study-RUN
python scripts/assemble_compare_form_dataset.py .turbo/study-RUN
python scripts/assemble_compare_form_dataset.py .turbo/study-RUN --execute --output-dir .turbo/form-dataset-RUN
python scripts/benchmark_compare_form.py --dataset .turbo/form-dataset-RUN
python scripts/benchmark_compare_form.py --dataset .turbo/form-dataset-RUN --execute --output-dir .turbo/form-evaluation-RUN
```

All output directories must be new. Use ignored `.turbo/` paths or a directory
outside the checkout: untracked artifacts inside the checkout fail the required
code-cleanliness check. These commands read remote data and write local files
only. They require a clean checkout of the exact registered research revision.
Preview writes nothing and does not run the predictor.

The assembler reads the complete private archive index in one enforced read-only
database snapshot. It downloads and checks each relevant archive against the live
index, remote content, and content hashes. The real collector's JavaScript source
verifier checks saved input hashes, the pinned algorithm and calibration signature,
capture clocks, original fixture identity, and frozen team aliases. A saved
`verified` flag or a local `server-record.json` is insufficient.

An exact forecast input and prediction published before its UTC match day proves
those values were available then. This route does not invent missing training
dates or certify retrospective reconstructions. It accepts only complete frozen
inputs. Expectations for prior games need their own pre-game publication; missing
ones remain neutral and reduce the usable form sample. Reports distinguish raw
archived rows, distinct source fixtures, exclusions, and provider/age/history
coverage.

Before the registered evaluation window closes, exports contain inputs and
coverage only. They do not query target settlements or result labels. The benchmark uses a fresh
database server clock to enforce the seal, so changing a local clock or manifest
flag cannot open it. Re-export after the window closes.

After closure, each score must match the baseline ledger's exact source game and
unchanged frozen fixture identity. Provider fixture duplicates and reversed
orientations stay together; conflicting duplicates are excluded. Event groups are
verified where possible, inferred groups remain labelled, and groups crossing the
development/evaluation boundary are excluded. Frozen aliases affect only their
match day; later team mappings do not rewrite earlier inputs.

Before performance testing, the benchmark authenticates the source inventory
again and reconstructs the complete cohort. Edited scores, omitted fixtures,
missing archives, and changed settlements require rejection or a fresh export.
The registered 1,000-match/20-group requirements apply to each period. Insufficient
data does not run candidate selection. Sufficient data replays the real TypeScript
predictor in bounded batches with A/A parity, original clocks and calibration,
and development-only ML-trend ablations. Inputs, outputs, hashes and the report
are saved locally. A successful report can qualify a candidate for a separately
registered confirmation experiment; it cannot deploy one.

## JSON bundle contract (`--input`)

The `--input` path accepts `schema_version: 1`, `predictor_revision`, `calibrations`
(the five original calibration filenames mapped to their frozen JSON contents),
and `cases`. Each case contains:

- `fixture`: original `source_game_id`, UTC `game_date`, canonical home/away IDs,
  actual home/away scores, `event_group`, grouping origin, provider, cohort,
  history band, and exclusion state.
- `teamA`, `teamB`: exact `TeamWithRanking` inputs in target home/away orientation.
- `reference_time`: timezone-aware predictor clock. Reconstruction defaults to
  the last millisecond before the target's UTC match day. Frozen forecast replay
  requires its original capture timestamp. The runner fixes timezone to UTC and
  freezes this clock so birth-year age inference survives later season rollovers.
- `games`: cleaned prior results in the original predictor input order, with
  `result_available_at` and `result_sha256`. Hash the ID, date, canonical home/away
  IDs, scores, and result availability using `digest()`. Non-null
  `ml_overperformance` also needs `ml_provenance`, bound to the ID and learned
  value, with pre-match availability and training timestamps. Exclude same-day
  and future information.
- `input_provenance`: one descriptor for each `team_a_snapshot`, `team_b_snapshot`,
  and `calibration_{margin,outcome,age_groups,probability,confidence}` role.
  Each descriptor has `sha256`, `code_revision`, timezone-aware `created_at` and
  `last_calculated`, and `snapshot_date`. Learned inputs additionally require
  `trained_at` and `training_cutoff`. Explicitly set `uses_learned_inputs: false`
  only for an input with no learned component. Hashes use the research module's
  canonical `digest()` and must match the inputs actually replayed.
- `expectations`: source fixture ID mapped to `expected_home_margin`, `source`
  (`frozen` or `reconstructed`), source fixture ID, date, canonical home/away IDs,
  model signature, and independently verified `provenance`. Its digest must
  match `expectation_payload()` and its identity must match that historical game.
  Preserve the original expectation inputs and identity mappings/exclusions in
  the bundle for independent provenance review. History-row-ID keyed maps are
  also accepted for existing bundles.

Frozen expectations must have been created before the historical game. A later
reconstruction instead preserves its truthful computation timestamp and carries
its complete input chain, pinned source hashes, collecting model signature, and
full baseline prediction. Every dependency must still pass the pre-match gate
for that historical game. Hashes detect changes; source evidence must independently
establish when those exact dependency values were available.

To reconstruct expectations from a bundle of verified pre-game inputs:

```sh
python scripts/benchmark_compare_form.py --input earlier-inputs.json --reconstruct-expectations
python scripts/benchmark_compare_form.py --input earlier-inputs.json --reconstruct-expectations --execute --output-dir reports/expectations-RUN
```

The preview audits inputs without running Node or writing files. Execution uses
the real pinned TypeScript baseline and saves `expectations.json`, keyed by source
fixture ID, alongside replay inputs and outputs. Target scores and candidate
overrides are excluded from reconstruction inputs. Missing or later-trained inputs
are reported as exclusions. This command performs no candidate selection and does
not change the historical study's coverage requirements.

Archive the original input files, identity mappings, exclusions, source revision,
and lineage evidence with the bundle. The generated manifest hashes the complete
input JSON. Historical reconstructions remain distinct from genuinely frozen
forecasts; neither missing metadata nor a hash alone proves provenance.

```sh
python scripts/benchmark_compare_form.py --input frozen.json
python scripts/benchmark_compare_form.py --input frozen.json --execute --output-dir reports/form-RUN
```

An insufficient-data report does not run model selection. Eligible runs replace
only the form scalar in a generated research copy; the collecting files are not
edited. Recent scoring rates, volatility, ratings and calibration retain their
baseline calculations. Residuals are clipped to four goals, shrunk for sparse
history, and tested with sequence weighting, 30/60-day half-lives, and opponent
caps. Missing expectations remain neutral and are reported in diagnostics.

The runner checks exact in-process A/A parity. A separately saved prediction may
differ by at most `1e-12` across JavaScript platforms; categorical decisions and
scorelines must agree. Use `--parity-only --execute` to replay unscored frozen
forecasts without treating them as historical evaluation cases.

## Interpretation and advancement

Choose a form candidate on development log loss, then Brier score, then the
predeclared simplicity order. ML-trend-off ablations are development diagnostics
only. Inspect evaluation metrics only for the selected candidate. Reports retain
residual coverage and frozen/reconstructed provenance, probability/draw metrics,
score/margin/risk errors, and provider/cohort/history slices.

Lower evaluation Brier score plus an upper 95% paired group-bootstrap log-loss
difference below zero qualifies for prospective confirmation, not deployment.
The attack/defense fitter is an offline building block with cohort-average
shrinkage and no home advantage; fitting/testing that challenger on real data
depends on the same provenance and coverage gates.

Before prospective challenger collection, a separate reviewed migration must add
immutable child forecasts keyed by baseline forecast ID and candidate signature,
plus an immutable candidate manifest and pre-match server timestamps. The baseline
ledger cannot store another model by inserting the source fixture again. No child
storage migration or challenger capture is activated by this research command.

The current calibration experiment stays registered for November 16–December 13
development and December 14–January 10, 2027 holdout. The existing benchmark remains
coverage-only until holdout closes. First scheduled capture and first live result
settlement must be verified when those events occur.
