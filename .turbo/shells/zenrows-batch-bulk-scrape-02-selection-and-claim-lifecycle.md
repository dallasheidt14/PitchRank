---
spec: .turbo/specs/zenrows-batch-bulk-scrape.md
depends_on: [zenrows-batch-bulk-scrape-01-batch-client-and-run-control]
---

# Plan: Selection and claim lifecycle

## Context

This shell decides which teams a run works on and guarantees every claimed team ends in
exactly one final state. It touches only the database — no ZenRows — so it can be built and
tested independently of the fetching layer.

The claim lifecycle is where this project is most likely to cause lasting damage, because a
row left mid-flight is invisible to every future run and nothing reclaims it automatically.
Three review rounds concentrated here, and two facts shape the whole design. First,
eligibility is **not** single-defined in the database: the top-up function applies the rules
in SQL, but claimed queue rows never pass through it, so the calling code is the only place
they are checked at all — and a rejected team left in the tracking map gets marked done with
zero games, burning a revival enqueue. Second, the queue table permits only one pending row
per team, and the scheduled enqueue jobs add fresh pending rows for teams a long run is
holding — so releasing a held row can be refused by the database, and the existing release
helper updates a hundred rows per statement and swallows that refusal as a warning, stranding
the other ninety-nine.

## Produces

- Team selection: claim from the queue, then top up from the teams table to the run's target,
  preserving the existing total-scrape-target semantics.
- **The identity map every later stage depends on** — per surviving team, its canonical master
  id, its provider team id, and its queue request id where one exists. Both ids are needed
  downstream and neither substitutes for the other: fetching and the game rows key off the
  provider id, while the scrape log and queue finalization key off the master id. The existing
  base scraper shows the same split (`src/scrapers/base.py:28-40`).
- An eligibility filter applied to claimed rows as well as top-ups, with rejected rows given a
  terminal state and removed from tracking.
- A single in-memory set of outstanding claims, and the invariant that a row reaches its
  terminal state before leaving that set — which is what makes the guard safe to run after a
  deliberate non-zero exit.
- An explicit precedence order over every path that closes out a team, so no row can be
  reachable in two final states or in none.
- Release mechanics that survive the one-pending-row constraint: one row per statement, and a
  refused release retired to a terminal state rather than lost.
- Dry-run behaviour that previews the selection read-only, without claiming and without
  reaching the fetching layer, and reports the planned task count and a credit estimate for
  the configured proxy tier.

## Consumes

- The script skeleton and its CLI surface — from Shell 01.
- The queue claim and top-up database functions — from existing codebase.
- The eligibility rules and their rationale — from existing codebase.
- The queue finalize and release helpers as reference behaviour — from existing codebase.

## Covers Spec Requirements

- R1
- R2
- R3
- R4 (partial: this shell's own files must not touch the three protected files)
- R5
- R6
- R7
- R8
- R14 (partial: releasing teams never submitted when the budget expires)
- R37

## Implementation Steps (High-Level)

1. **Build selection**
   - Claim queue rows for the provider, then top up from the teams table to the run target,
     most-recently-scraped first past the staleness gate.
2. **Apply eligibility to both sources**
   - Enrich claimed rows with the columns the rules read, then filter. Give a rejected claim a
     terminal state and drop it from tracking, so it cannot later be marked done with no games.
3. **Introduce the outstanding-claim set**
   - One set, with the write-then-remove ordering. This is the mechanism that lets the outer
     guard release only what is genuinely unresolved.
4. **Encode the precedence order**
   - Implement the ordered branches so exactly one decides each row. Later shells attach their
     exit conditions to these branches rather than inventing new ones.
5. **Implement release mechanics**
   - Release one row per statement. When the database refuses because the team already carries
     a newer pending row, retire that redundant claim to a terminal state instead of dropping
     it. Do not reuse the batched helper's shape here.
6. **Wire the dry run**
   - Preview the selection with a read-only query and exit before anything is claimed or any
     job is created. Report the planned task count and the credit estimate for the configured
     tier, which the requirement asks for alongside the preview itself.
7. **Test every terminal path**
   - One named test per branch of the precedence order, each asserting no row ends in two
     states and none is left outstanding. Include a refused-release test proving one conflict
     does not strand its neighbours.

## Open Questions

None.

## Expansion Deferred

The following are filled in when `/expand-shell` runs:

- Pattern survey against the codebase state at implementation time
- Concrete `file_path` references with named functions or symbols for each Implementation Step
- Verification section with specific test commands and smoke checks
- Context Files section with the files to read in full before editing
