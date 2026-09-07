---
spec: .turbo/specs/zenrows-batch-bulk-scrape.md
depends_on: [zenrows-batch-bulk-scrape-01-batch-client-and-run-control, zenrows-batch-bulk-scrape-02-selection-and-claim-lifecycle]
---

# Plan: Club resolution and parsing

## Context

This shell turns fetched bodies into game rows. It is the highest-risk stage in the project,
because it contains **two mirror-image traps at the same boundary, and both fail silently** —
no exception, no warning, just wrong or missing output.

The first is the club-name cache. The existing parser checks that cache before making a
network call, which is the entire reason no refactor of the scraper is needed. But the fill
has to be complete and string-keyed: an id left out because the database already answered it,
or a key stored as a number, falls straight through to a direct request from the runner's IP
— reintroducing exactly the slow sequential traffic this project exists to remove, while
appearing to work.

The second runs the opposite way. The parser compares team ids by strict equality against an
integer in the payload and compares dates against a date object. Hand it the string id the
cache wants, or a raw timestamp, and it matches nothing and returns **zero games with no
error**. A test that only checks "did it throw" passes while the run silently collects
nothing.

So this stage's verification cannot be "it ran" — it has to assert real games came out.

There is a third instance of the same trap in adjacent calls, and it runs the opposite way
again: the match parser takes the team id as an **integer**
(`src/scrapers/gotsport.py:660`), while the converter that turns a parsed game into an output
row takes it as a **string** (`:841`) and emits it as one (`src/scrapers/base.py:52`). So game
rows end up carrying the provider id as text while the scrape log and queue finalization key
off the canonical master id. Both ids have to travel together through this stage.

Club names are not optional here: the opponent club feeds team matching at roughly a third of
the weight, and games cannot be edited after import, so a run imported with blank clubs turns
into manual team merges later.

## Produces

- Pass-1 orchestration: one task per selected team built from the selection handoff, submitted
  through the batch client under the run clock, polled to completion or to the budget, and its
  bodies downloaded. This is the seam that joins selection to parsing; the client knows how to
  submit a list, and this is where that list becomes the actual run.
- Per-team parsed game counts keyed by the canonical master id — the form queue finalization
  needs, since the game rows themselves carry the provider id.
- **The run-output handoff** the bookkeeping stage reads: per-task results keyed by their
  external id, every job's job id and run id, the cumulative spend figure, and the path and
  naming of the scraped game file. All of it must be captured before any non-zero exit,
  because the reporting and the artifact upload downstream run on failure paths too — which
  is exactly when this handoff is most needed and least likely to exist.
- Ordering and capping applied before club ids are collected, so no credits are spent
  resolving clubs for games that parsing will discard.
- A side-effect-free pre-filter mirroring the parser's own checks, tightening that further.
- Database-first club resolution: a direct lookup keyed by the provider's team id, then an
  alias fallback restricted to approved mappings only, both batched within the URI-length
  limit and paginated.
- A second batch job for whatever the database could not answer.
- A cache pre-fill combining all three sources — resolved by job, resolved by database, and
  an empty placeholder for the rest — keyed so the parser's lookup actually hits.
- The parser boundary: integer team id and date cutoff on the way in, string ids preserved
  everywhere else.
- Game output in the existing file shape, and the import handoff, including the failure path
  that keeps teams retryable.

## Consumes

- The batch client, chunking, the run clock and the reserved time allowance — from Shell 01.
- The selected team list with its identity map — master id, provider id, request id — from
  Shell 02.
- The outstanding-claim set and the precedence order's abort and import-failure branches —
  from Shell 02.
- The existing match parser and its game-dict converter, called as-is — from existing codebase.
- The existing game importer, invoked as a subprocess — from existing codebase.

## Covers Spec Requirements

- R4 (partial: this shell's own files must not touch the three protected files)
- R9 (partial: routing club lookups through job 2, with the no-direct-network assertion that proves it)
- R14 (partial: routing an incomplete-submission expiry into the abort branch)
- R15 (partial: running pass 2 within the reserve and aborting when it expires)
- R17
- R18
- R19
- R20
- R21
- R22
- R23
- R25
- R26
- R27 (partial: releasing claims, writing no log rows, and exiting non-zero)
- R38 (partial: surfacing job-2 failures without exposing the key)

## Implementation Steps (High-Level)

1. **Run pass 1 over the selected teams**
   - Build one task per selected team from the selection handoff, keyed by provider id, with
     the date parameters. Submit through the client, poll under the run clock, and download
     the bodies. Carry the identity map alongside so every downstream artifact can be keyed
     either way.
   - If the budget expires while submissions or the close call are still outstanding, stop the
     run and take the abort branch. Do not continue into parsing, and do not let it fall
     through to the generic guard — an incomplete submission is a distinct case from a run
     that fetched everything and simply ran late.
2. **Order, cap, then pre-filter**
   - Sort newest-first and cap before collecting club ids, then apply the pre-filter matching
     the parser's own discard rules. Treat this as conservative, not exact — the parser drops
     more than the cap does.
3. **Collect the ids that still need a club**
   - The scraped team itself, plus every opponent whose payload carried no inline club.
4. **Resolve from the database first**
   - Direct lookup by provider team id, then the alias fallback — restricted to approved
     mappings, since the column also admits pending, rejected and provisional rows and an
     unapproved association would feed a wrong club into matching. Batch and paginate.
5. **Submit the remainder as a second job**
   - Chunked like any other submission. On wholesale failure, or if the reserved allowance
     expires, take the abort branch rather than importing with blanks.
6. **Pre-fill the cache from all three sources**
   - Job results, database results, and placeholders for the rest — including ids the job
     answered with no club field. String keys throughout.
7. **Convert types at each boundary — they disagree**
   - Integer team id and a date cutoff going into the parser; string id going into the
     converter that builds the output row; string keys in the cache. Three adjacent calls,
     three different expectations, and getting any of them wrong produces no error.
8. **Parse, write, and import**
   - Produce the existing file shape and hand it to the importer. On a non-zero import,
     release claims and exit non-zero rather than marking teams done.
9. **Test for silence, not just for errors**
   - Assert a non-zero game count through the batch path for a fixture team — this is what
     catches the type trap. Assert no direct network call happens during parsing — this is
     what catches an incomplete cache. Cover the database-resolved id, a job result with no
     club field, and a number-keyed entry treated as a miss. Compare output against the
     existing path using a fixture with more than the cap's worth of matches spanning the
     cutoff.

## Open Questions

None.

## Expansion Deferred

The following are filled in when `/expand-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path` references with named functions or symbols for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
