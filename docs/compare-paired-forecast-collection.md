# Private paired forecasts and collection coverage

Private paired forecasts let a **separately qualified** form candidate predict
the same games as Compare. Collection balances coverage within the 500-fixture
daily limit. The public formula, collecting signature and existing studies stay fixed.

## Current boundaries

- The registered form study still develops on November 16–December 13, 2026 and
  evaluates on December 14, 2026–January 10, 2027. Its original checkout and
  manifests remain authoritative; new capture code does not rewrite them.
- No candidate is registered or enabled by this migration or workflow. Do not
  fabricate a qualifying report to start collection early.
- A candidate must have a closed, sufficient evaluation, a lower Brier score,
  and an upper 95% paired group-bootstrap log-loss difference below zero. Its
  report requires a separate review before registration.
- Confirmation lasts four weeks from the next complete UTC Monday **after the
  server registers the candidate**. The start/end dates never slide on retries.
- Adoption still requires at least 1,000 paired settled matches, 20 groups,
  lower Brier score, a negative upper 95% paired group-bootstrap log-loss
  difference, complete risk outputs, and subgroup review. Insufficient data
  makes no adoption decision. This capture feature does not implement a release.

## Storage and migration

Apply `supabase/migrations/20261113000000_compare_challenger_forecasts.sql`
through the normal migration process and verify the effective grants before
enabling any candidate. Never run a blanket migration push against this project.

`compare_challenger_manifests` binds the selected configuration, reviewed
qualification report/dataset/study hashes, code revision, complete research
source hashes, training provenance, and confirmation policy. Registration is
append-only. The candidate's calculation and input-building dependencies are
derived from their local imports, including expectation selection, verification,
calibration and runtime lockfiles. They must match the authenticated qualifying
study. Source bytes come from its archive, or its exact server-registered Git tree
when a code file was not copied into the archive. Missing code is a refusal;
current data or later-calculated values never fill missing historical inputs.
Capture infrastructure can have a newer revision.
`compare_challenger_forecasts` has a unique key on original forecast
ID plus candidate signature. It stores the baseline's exact frozen inputs,
authenticated historical expectations, candidate prediction, replay receipt,
and server capture time. Browser roles have no access; service-role writes go
through restricted functions. Update/delete are refused, and a concurrent or
repeated capture cannot replace the first one.

Capture rechecks the original source fixture under a database lock, rejects
scored/changed/excluded fixtures, and requires a timestamp before match day in
UTC. It cannot backdate a forecast. The original ledger remains untouched.
Final scores come exclusively from that ledger's exact-source result matching;
there is no independent candidate result-matching path.

## Register and capture after qualification

Use a clean, reviewed, committed checkout containing the full capture feature.
The registration command verifies its research files against Git. The qualifying
benchmark report must come from the authenticated frozen-dataset benchmark.
Its SHA256 binds the complete report, including diagnostics and subgroup results.

```sh
# Preview: prints the definition, writes nothing.
python scripts/register_compare_challenger.py /private/qualified/report.json --reviewed
# Separate release review must have happened before this explicit registration.
python scripts/register_compare_challenger.py /private/qualified/report.json --reviewed --execute
```

Keep the returned candidate signature. Set `COMPARE_CHALLENGER_SIGNATURE` to that
signature **only after** checking the server record and confirmation dates.
The `Capture Registered Compare Challenger` workflow then follows successful
scheduled main-branch daily baseline captures. An upstream manual preview cannot
start writing candidate forecasts; manual paired capture requires its own explicit
execute choice. The workflow resolves the candidate's immutable
revision and checks out that revision, so later unrelated main changes cannot
silently change the experiment. Empty configuration leaves the workflow idle.

For an operator-run preview using existing private archives:

```sh
python scripts/capture_compare_challenger.py SIGNATURE --archive /private/current-forecasts --archive /private/earlier-forecasts
```

Add `--execute` to save eligible paired forecasts. Alternatively,
`--download-archives /private/new-directory` downloads the registered forecast
archives needed for historical expectations when executing. Without `--execute`
that mode only inventories archive headers and explicitly reports that inputs
were not verified and no capture ran. Neither preview mode creates local files.
The download mode reads archives registered in the preceding 366 days. Only
independently authenticated prematch expectations can contribute residuals;
missing expectations remain neutral and reduce the usable sample.

The real TypeScript research runner must reproduce the saved baseline, establish
unchanged-mode parity, and supply complete outcome, margin, score and four-goal
risk outputs. Only the selected form contribution changes. Raw scoring profiles,
ratings, calibration, volatility, common opponents and ML trend stay fixed.
No development-only ML ablations run during confirmation capture.

Failures are counted and make the command fail. Capture limits, late fixtures,
missing authenticated inputs and existing captures are reported separately.
`compare_challenger_pair_coverage` reports baseline, paired, missing and paired
settled counts by date/provider/cohort. Missing candidates remain visible rather
than disappearing from the denominator. Do not compute confirmation accuracy
before its fixed window closes.

## Collection coverage

```sh
# Outcome-blind preview, no writes.
python scripts/audit_compare_collection.py --limit 500
# Save a new aggregate local report only; no remote writes.
python scripts/audit_compare_collection.py --limit 500 --execute --output /private/new-coverage.json
```

The audit enumerates the complete seven-day stored fixture pool with canonical
team identities and existing safety exclusions. It reports exclusion reasons,
provider/age/gender/history strata, saved forecast status and model signatures,
and the old and new selections on the same pool. It reads no outcome metrics.
The daily job saves that aggregate report alongside its intake/capture summaries.

The same Python sampler orders both intake and the complete pending capture queue,
so interrupted-run backlogs cannot undo provider coverage. Balanced selection
rotates providers, then age/gender/history strata within each
provider. Date and deterministic fixture hashes order games within each stratum.
This prevents many cohorts from one provider crowding out smaller providers.
The cap, source identity, exclusion and rating requirements remain unchanged.
`--selection chronological` retains the former selection policy for comparison
or rollback. New fixture payloads record their sampling policy and stratum.

Pool history bands use the smaller of the teams' **current rating games_played**
counts. Saved forecast bands use **frozen usable results** instead; these are
different denominators and are labelled separately. Cross-age or cross-gender
fixtures carry both labels in the pool report rather than being silently filed
under only the home team's cohort. Missing history is explicit `unknown`.

Balanced coverage deliberately oversamples small strata. It is not a national
random sample. Report the available pool and each subgroup beside overall
results; do not infer accuracy for an absent provider. Providers with zero stored
upcoming fixtures need source intake evidence before any collection change;
never substitute invented fixtures, later ratings, or relaxed identity checks.

## Rollback

Unset `COMPARE_CHALLENGER_SIGNATURE` to stop private candidate capture. To restore
chronological collection, change **both** `--selection balanced` arguments in
`weekly-prospective-refresh.yml` to `--selection chronological`. A one-off operator
command does not change the schedule. Preserve every
registered manifest, baseline forecast, candidate forecast and private input
archive. No rollback requires changing the public prediction formula.
