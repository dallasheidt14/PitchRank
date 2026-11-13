# Learning from current Compare predictions

This private pipeline saves current Compare and three SOS alternatives before a
game. It reviews correct predictions, misses and draws after scores arrive. It
cannot change the public formula or promote a candidate.

The original daily collector stays pinned for its existing studies. Monitoring
uses separate tables linked to those original fixture identities. It calls the
current prediction service with fresh frozen inputs; these are scheduled model
observations, not a record of every prediction a customer viewed.

## Capture and private storage

Apply only `20261114000000_compare_live_monitoring.sql` through the normal
migration release process. Do not run a blanket database push. The migration
creates observational tables and restricted server functions. It changes no
existing forecasts, registrations, rankings, or games.

`compare_monitoring_models` registers formula/calibration identity, code revision,
research source hash and multipliers 0, 0.5, 1, 1.5. Development is four weeks
starting on the next complete UTC Monday. A different source revision is a new
monitoring registration. Keep the workflow revision fixed during its study.

`compare_monitoring_forecasts` stores full frozen teams, cleaned histories,
calibration, baseline prediction, all four SOS outputs and replay receipts.
Server time must precede the match's UTC date. Source changes and scored games
are refused under a lock. Retries preserve the first capture. Browser roles
cannot read or write these records.

The research runner copies the real predictor into its own temporary directory,
replaces only its explicit SOS term, loads frozen calibration and freezes its
clock. The unchanged mode must reproduce every baseline output, including
confidence, margin, score and four-goal risk. Production predictor modules are
never edited. Missing SOS remains explicitly unknown in reports even though the
existing formula has its own neutral fallback.

## Pilot and operation

Use a clean committed checkout and existing server credentials. Preview writes
nothing, creates no temporary files and runs no research predictions.

```sh
cd frontend
NODE_OPTIONS=--conditions=react-server npx tsx scripts/capture-compare-monitoring.ts --limit 20
# Save the reviewed pilot privately.
NODE_OPTIONS=--conditions=react-server npx tsx scripts/capture-compare-monitoring.ts --limit 20 --execute
```

Repeat the pilot and verify earlier records are skipped with zero replacements;
the cap applies to new fixtures, so a retry may capture the next 20. Verify unchanged
original forecasts. Check source dates, complete frozen calibration, A/A parity,
all risk outputs and provider/age coverage in the database.

Set `COMPARE_MONITOR_REVISION` to the reviewed full commit SHA and
`COMPARE_MONITOR_ENABLED=true` only after verifying the pilot. The workflow saves
up to 500 new observations daily at 06:20 UTC and reviews results Monday at
17:30 UTC (10:30 AM Phoenix). Existing captures do not consume the new-fixture cap.
The monitoring sample follows the baseline's available fixtures and is not a
national random sample. Missing monitoring captures appear beside that baseline
denominator. A new live formula requires a separately pinned monitoring revision.

```sh
python scripts/review_compare_monitoring.py
python scripts/review_compare_monitoring.py --execute --output-dir /private/new-review
```

Detailed JSON and Markdown reports go to the existing private
`prediction-input-archives` bucket. Actions receives operational counts only;
no full match data or case reports are uploaded as public workflow artifacts.
The review reuses exact-source settlement and merge/exclusion handling. An
append-only result audit records observed scores, corrections and held results.
It never writes the games or original forecast ledger.

## Protected results and reporting

The server masks frozen context and fixture data for future dates and any date
inside an unfinished registered calibration study, regardless of the monitoring
model's signature. The November 14–15 diagnostic remains closed until November 16.
SOS confirmation dates are also masked until their complete window closes.
This conservative date-wide rule protects overlapping studies; it can leave the
weekly review coverage-only until existing study windows close. Do not bypass
that seal to obtain earlier accuracy results.

Reports separate model registrations and show last-seven-day and cumulative
probability accuracy, outcomes including draws, margin errors and four-goal risk.
Provider, age, gender, history and confidence slices include sample sizes.
SOS gaps are compared within age/gender/rating-gap strata; form/SOS conflicts are
labelled hypotheses, not causes. Small strata and nonrandom provider coverage
limit conclusions. Review examples include both correct and incorrect predictions.

## Selection and confirmation

After development closes and its labels are available, the benchmark requires
1,000 unique scored fixtures and 20 groups. Select once by development log loss,
then Brier score, then closeness to the unchanged configuration. Verified event
groups are preferred; inferred groups stay labelled. Events crossing development
boundaries are excluded. Source duplicates count once. Missing risk outputs are
an error, never silently removed from a candidate's denominator.

If a different multiplier wins, review its report and explicitly register it:

```sh
python scripts/review_compare_monitoring.py --execute --output-dir /private/new-selection --register-selection
```

This saves an immutable selection and its exact development dataset digest.
Confirmation begins on the next complete UTC Monday after server registration
and lasts four weeks. Repeated registration cannot move the dates or selection.
Later changes to development evidence require review rather than silently
reselecting. Weekly jobs never register a selection automatically.

After confirmation closes, compare only the registered selection with the
unchanged arm on the same fixtures. Require 1,000 paired completed matches,
20 groups, lower Brier score and an upper 95% paired group-bootstrap log-loss
difference below zero. Complete risk outputs and adverse subgroup review are
required. Insufficient evidence makes no adoption decision. Even a passing
report says `release_review_required`; deployment requires a separate decision.

## Rollback

Unset `COMPARE_MONITOR_ENABLED` to stop monitoring. Preserve all models,
forecasts, result audits and selections. The live formula and existing studies
require no rollback because this feature does not modify them.
