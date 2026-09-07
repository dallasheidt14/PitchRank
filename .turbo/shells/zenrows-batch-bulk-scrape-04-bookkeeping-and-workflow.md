---
spec: .turbo/specs/zenrows-batch-bulk-scrape.md
depends_on: [zenrows-batch-bulk-scrape-01-batch-client-and-run-control, zenrows-batch-bulk-scrape-02-selection-and-claim-lifecycle, zenrows-batch-bulk-scrape-03-club-resolution-and-parsing]
---

# Plan: Bookkeeping and workflow

## Context

This shell records what a run did and gives the operator a button to press. The bookkeeping
is not clerical: the scrape log drives which teams become eligible again and when, so writing
the wrong row for a team quietly changes what future runs do.

Three constraints shape it. Per-team outcomes must come from that team's own task result, not
the run-level rollup, which cannot say which team failed. The scrape log's status column
admits only three values, so "team not found" is a counter in the summary rather than a
fourth status — and a not-found deliberately advances the team's timestamp, since re-probing
a dead id every run buys nothing. And the second job's tasks are lookups against real team
rows, so treating their failures as team scrapes would reset those teams' clocks and push
them out of the eligibility window.

The block-pressure rule needs care for a reason worth stating plainly: the existing finalize
mapping fails only rows that actually errored, so releasing everything when blocks spike
would send back teams that were scraped *and already imported* for a pointless second pass.
Only the blocked teams get released, and the decision has to be made before any log rows are
written, or a released team carries a row that inflates its own attempt count against the
futility gate.

One clause from an earlier stage lands here rather than there. When the import fails, the run
releases its teams and exits non-zero — and that is exactly the moment the scraped file must
survive, because it holds games already paid for. Preserving it means uploading it as a
workflow artifact, and the workflow file is written here, so this shell owns that half.

This shell also carries the one question the spec deliberately left open.

## Produces

- Per-team outcome classification from each team's own task result, with the documented
  failure buckets distinguished.
- Outcome classification ordered before any logging, so the released subset can be excluded
  from the log entirely.
- Scrape-log writes for first-pass teams only, with the timestamp rule and its deliberate
  not-found exception.
- Explicit exclusion of second-pass lookups from all team bookkeeping.
- Queue finalization matching the existing mapping, plus the block-pressure rule that
  releases only the blocked subset and never releases a permanent not-found.
- Job identifiers logged and uploaded **unconditionally**, so a killed run is recoverable
  within the vendor's retention window. The printed log line survives a cancellation on its
  own; the uploaded artifact does not unless its step runs regardless of outcome — and
  recovering a cancelled run is the entire reason the identifiers are kept.
- Unconditional upload of the scraped game file as a workflow artifact, so a failed import
  never loses games the run already paid to fetch.
- A run summary reported on every exit that created a job, including aborts.
- The dispatch workflow with its inputs, validation, and timeout relationship.

## Consumes

- The batch client and its result and spend accessors — the mechanism — from Shell 01.
- The outstanding-claim set, precedence order, release mechanics, and the team identity map —
  from Shell 02.
- **This run's outputs — the values** — from Shell 03: per-task results keyed by external id,
  every job's job id and run id, the cumulative spend figure, per-team parsed game counts
  keyed by the canonical master id (the form queue finalization indexes by), and the path and
  naming of the scraped game file. The file path matters concretely: a wrong path or glob
  makes the artifact upload a silent no-op that only warns, which would defeat the whole point
  of preserving games already paid for.
- The existing finalize mapping and the activity-refresh counting rule as reference behaviour
  — from existing codebase.

## Covers Spec Requirements

- R4 (partial: this shell's own files must not touch the three protected files)
- R10 (partial: the workflow input and its default value)
- R14 (partial: the workflow timeout-minutes margin over the budget)
- R27 (partial: preserving the scraped game file as a workflow artifact)
- R28
- R29
- R30
- R31
- R32
- R33
- R34
- R35
- R36
- R38 (partial: the run summary and the uploaded artifacts)
- R39

## Implementation Steps (High-Level)

1. **Classify outcomes per team**
   - From each team's own task result. Distinguish a bad target from a policy block; note that
     no per-task code means "the target refused us", so block pressure is read at the run
     level while per-team state stays per-team.
2. **Order classification before logging**
   - Decide the released subset first, so those teams never get a log row at all.
3. **Write scrape-log rows for first-pass teams**
   - Reached-and-empty advances the timestamp; blocked or failed-in-transit does not. A
     not-found advances it deliberately, against the general rule, and is counted in the
     summary rather than given its own status.
4. **Exclude second-pass lookups from bookkeeping**
   - No log row, no timestamp change, no queue transition for a club lookup.
5. **Finalize the queue**
   - Match the existing mapping. Apply the block-pressure rule to the blocked subset only,
     never to permanent not-founds, and release through the mechanics Shell 02 built.
6. **Log job identifiers and report**
   - Print the identifiers and upload them on a step that runs regardless of outcome — a
     cancelled run is precisely the case the upload exists for, and precisely the case a
     conditional step skips. Report on every exit that created a job, marking aborted runs as
     such, and never claim the duplicate-scrape figure the schema cannot support. Nothing
     printed or uploaded may carry the API key.
7. **Upload the scraped game file unconditionally**
   - Upload it even when the run failed, since a failed import is precisely when those games
     need to survive. This is the half of the import-failure rule the earlier stage cannot
     deliver, because it lives in the workflow file.
8. **Write the dispatch workflow**
   - Its own inputs, not the sibling workflow's — two of those are meaningless here. Validate
     them, and set the timeout so the time budget leaves room for import and cleanup.
9. **Test the bookkeeping rules**
   - Cover the timestamp rules including the not-found exception, second-pass exclusion,
     block-pressure releasing only the blocked subset, and a summary printed on an aborted
     run.

## Open Questions

- **What should the proxy-tier input default to?** The cheaper tier measured a tenth of the
  cost of the current one, reproduced three times, but only across small probes — and the
  operator reports that bypassing the proxy entirely usually trips the target's protection, so
  the expensive tier is the known-good setting. The operator is resolving this empirically by
  running the existing bulk workflow on roughly 300 teams with the premium setting disabled: a
  clean run means default the input to the cheap tier, blocks mean default it to the expensive
  one and revert the cost expectations. Do not invent a default before that result exists.

## Expansion Deferred

The following are filled in when `/expand-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path` references with named functions or symbols for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
