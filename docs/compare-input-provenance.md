# Compare input provenance

Historical research must establish the exact values available before a match,
not just find rows with old game dates. A model fitted later can overwrite a
game's ML value without changing that game's date.

## Recovery findings on November 11, 2026

The read-only recovery inventory preserved 51 ranking workflow records from
August 1 onward. The August 17 run `32033951303`, using revision
`4bf134e53e57698f0b51b0cfb21cb20ba2600044`, reports saving 124,622 predictor
snapshots. Database counts and creation times agree with that log. The log does
not contain snapshot payload hashes or the per-game ML values. Count agreement
cannot authenticate today's historical row values.

The five pinned Compare calibration files match both the August 17 checked-out
source and the source referenced by successful run `30761692787`. That earlier
run completed August 2 at 22:21:04 UTC, establishing the earliest recovered
availability bound for those exact bytes. Their exact training dates and
unrelated snapshot/game values remain unverified.

The broader August 1–November 8 inventory contains 81 completed legacy forecast
records and 560 shadow records. These are potential evidence, not certified
pre-game forecasts. Shadow logging retained relevant game IDs, not their values.
Even their combined count before overlap/exclusions cannot meet the declared
1,000-match requirement in each period. November's immutability protections do
not retroactively certify legacy records.

The available daily database backups cover November 4–11; point-in-time recovery
is disabled. No older external exports were identified by the owner. Those
backups cannot recover the August–October development inputs. The original
historical study remains insufficient; future collection is a separate study.

Raw logs, metadata queries, and their returned results are kept in the local,
gitignored recovery directory. No historical candidate has qualified. Recover
value-bearing historical artifacts or an independently verifiable history of
immutability before certifying those rows. Never backdate newly created evidence.

## Future ranking archives

The ranking workflow requests an input archive with `--provenance-dir`. Recording
captures the actual database responses and requests at `.execute()`, including
games, identity mappings, exclusions, snapshot/ranking outputs, and ML writes.
It records resolved engine configurations, training rows and cutoffs, fitted ML
models, joint-model state and uncertainty, runtime versions, source files, and
the five calibration files. Training and reconstruction timestamps stay truthful.

The recorder observes the existing calculation; it does not refit a model or
change its values. Recording errors are collected and reported after calculation,
so a disk error cannot make a database fetch return fewer games. Such an archive
cannot be published. Initialization failures are reported after rankings finish;
they may leave an incomplete directory without a manifest. Source changes during
a run also fail the archive. Existing directories and objects are never overwritten.

`--dry-run` previews the calculation without creating archive files. To record
an authorized ranking publication and then validate its archive locally:

```sh
python scripts/calculate_rankings.py --ml --force-rebuild --provenance-dir .turbo/private-new-run
python scripts/publish_ranking_input_archive.py .turbo/private-new-run
```

The second command validates locally and makes no network requests. Add
`--execute` only to publish into the configured project's private archive bucket.
That publisher verifies every referenced object, uploads without replacement,
downloads it for comparison, and finally registers the manifest hash in
`prediction_input_archives`. The database supplies its immutable `recorded_at`.
An incomplete upload cannot create a completed index record. Internal model
pickles must never be loaded from an untrusted archive.

Server registration supplies a conservative known-available-by time, not the
original first observation of every score. Exporting old rows today cannot make
them eligible for an earlier match. Future dataset assembly must bind each input
to its exact archived content and an independently authenticated availability
witness. It must distinguish frozen forecasts from reconstructions made later.
Archive completion itself does not certify study eligibility.

## Full forecast archives and a separate form study

The daily Compare workflow can also archive completed forecasts for the next
seven UTC match days. It preserves the ledger's full frozen team inputs,
calibration, cleaned result values, predictions, and source identity. Actual
outcome columns are excluded. This sidecar does not recalculate or replace a
forecast. It is disabled until the repository variable
`COMPARE_INPUT_ARCHIVE_ENABLED` is set to `true` after the archive migration is
verified.

```sh
python scripts/archive_compare_forecasts.py
python scripts/archive_compare_forecasts.py --execute --output-dir reports/private-forecasts-RUN
python scripts/publish_ranking_input_archive.py reports/private-forecasts-RUN --execute
```

The first command reads coverage without writing files or remote records. The
second writes a new local archive only. The third publishes privately. Preview
counts describe captured rows, not research-eligible fixtures; incomplete legacy
payloads must still be excluded during assembly.

Register future form research from a reviewed, clean commit before its first
target date:

```sh
python scripts/register_compare_form_study.py
python scripts/register_compare_form_study.py --execute --output-dir reports/private-form-study-RUN
```

The preview needs no credentials or network. Execution writes a private study
archive and registers its hash in the same append-only index. It records the
committed research source hashes, collecting predictor revision/signature,
fixed form variants, and selection/confirmation rules. Development starts on
the next complete UTC Monday and lasts four weeks; evaluation follows for four
weeks. Each period still requires 1,000 matches and 20 groups. Registration
crossing that Monday boundary is rejected; its archived objects and index record
remain preserved but do not constitute a valid study registration.

For an array of complete ledger records, the offline source check is:

```sh
node --import ./frontend/node_modules/tsx/dist/loader.mjs frontend/scripts/verify-compare-source.ts frozen-rows.json NEW-receipts.json
```

It checks the collector revision's actual input projection and seven predictor
modules against the pinned revision, then verifies the JS input hash, calibration
signature, team orientation, required replay-input containers, and reported pre-match
capture time. Output files cannot be overwritten. Successful receipts explicitly
retain `authority_verified: false`: a local JSON file and matching hashes cannot
authenticate a database timestamp. Dataset assembly must independently verify
the private server index, its exact referenced objects, and each member binding
before using these inputs. The current benchmark does not yet consume this new
study registration or certify its archives.

## Rollout and rollback

Apply `20261112000000_archive_prediction_inputs.sql` before activating the workflow
publisher. A hand-applied migration also needs its migration-ledger entry repaired.
The migration adds an append-only index and private storage bucket. Restrictive
browser-role policies protect the new bucket even when unrelated permissive
storage policies exist. It does not update games, ratings, forecasts, or existing
experiment manifests.

Verify the first actual workflow archive: download and hash-check its manifest
and objects, confirm required input sources and training cutoffs, and compare
archived output values with that run's saved snapshots. A green workflow alone
does not prove those records were written. Roll back collection by disabling the
archive workflow arguments/publisher, while preserving existing private objects
and the immutable index. Do not trigger a ranking calculation merely to test
collection; use an offline fixture or the next authorized production run.

The collecting Compare predictor's seven hashed modules and calibration files
remain unchanged. Any future form study needs its own predeclared registration;
it must not relabel the August–November study or alter the existing calibration
experiment.
