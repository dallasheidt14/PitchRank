---
status: draft
---

# Plan: Add the merges stage to the weekly team cleanup

## Context

The weekly team cleanup (`scripts/team_cleanup/`) runs clubs, states and ages unattended: an hourly
tick proposes on Wednesday, publishes review cards to `/mission-control/cleanup`, applies an
automatic lane inside the apply window, and applies the owner's choices once the review is marked
done. Merges were always designed as stage 5, but today `propose_week.py` stubs them as "not run:
the duplicate scans are frozen". The owner lifted that freeze on 2026-10-18 and on 2026-10-22 asked
for merges to join the weekly process.

Owner decisions (2026-10-22):

- **Evidence cards, no AI reviewers.** The two duplicate scans run unattended during the weekly
  propose. Each pair becomes a card on the same website page, showing both teams side by side,
  their shared opponents and their game overlap. The owner picks Merge them, Keep separate or Not
  sure, and can flip which row survives.
- **Only provably safe pairs merge automatically.** That is Doorway C's `1_provably_safe` tier: one
  row holds no games, and its provider alias already points at the other row. Merging such a pair
  changes no team's record. Every other pair becomes a card.
- **At most 100 merge cards a week**, cleanest first. The rest wait for later weeks.

Scope cuts, decided while planning:

- Fused rows are not split by this stage. A pair the scanners hold for self-play or for a fused
  survivor is counted in the manifest's `left_out` and never carded.
- No second lap.
- Doorway B is not added.
- Doorway A stays off.
- The health report gains no duplicate metrics.

## Pattern Survey

Survey of `C:\pitchrank-cleanup-loop` at origin/main 8efa8116e, 2026-10-22. Line numbers were
confirmed by grep. PR 1 has since changed the applier, the exclude script and the kit's pair
helpers, and PR 2 the two stage CHECKs, their migration tests and the website, which now admit
merges; read those entries against their PR's steps.

### Analogous Features

**Propose**
- `propose_week.py:77` defines `PROPOSED_STAGES = (CLUBS, STATES, AGES)`, and `NOT_RUN` (`:79`)
  holds the frozen merges note.
- Each stage runs `preflight()` → `propose()` → `scoped_proposals()` → `close_guard()`:
  - `preflight()` runs `SELF_CHECKS[stage]` (`:91`, all `--code-only`).
  - `propose()` runs `stage_commands()`, which is an if-chain per stage.
  - `scoped_proposals()` writes `proposals.json` (one row per single-team change) and the input
    named by `APPLIER_INPUTS` (`:104`).
  - `close_guard()` writes `stale.json` through `write_guard.stale`.

**Automatic lane**
- `sure.sure_because` (`sure.py:103`) is an if-chain over clubs, states and ages, and returns
  None otherwise.
- `reverted_changes` (`:72`) keeps a reverted `(team, field, new_value)` from ever being sure again.

**Pages** (`pages.py`)
- `build()` (`:391`) runs `sort_out` (`:239`), then `sure_because`, then takes
  `auto = settled[:caps.auto]` and owner cards up to `caps.cards`, then calls `card()` (`:324`,
  single-team: `change.{field, old, new}` and `team.{…}`).
- State evidence comes from `state_facts()` and is attached as `card["evidence"]`.
- Game evidence comes from `build_evidence(fetch_games(...))`.
- Both lanes go to `team_cleanup_cards` through `decisions.card_rows` (`decisions.py:93`).
- The build writes `page.manifest.json` and `page.json`.
- `load_caps()` (`:144`) reads one global `page_caps` pair from `config/team_cleanup.json`,
  currently `{cards: 2000, auto: 50}`.

**Website**
- `frontend/app/api/mission-control/cleanup/route.ts` feeds `stageReviews()`
  (`frontend/lib/mission-control/cleanup.ts`), which iterates `CLEANUP_STAGES`
  (`['clubs','states','ages']`).
- `decisions/route.ts` accepts apply, dont_apply or unsure on the owner lane of the newest build.
- `done/route.ts` sets `owner_done_at`.
- `undo/route.ts` inserts into `team_cleanup_requests`.
- The UI is `CleanupCardView.tsx` (single-team card) and `CleanupReview.tsx` (stage tabs,
  whole-group apply, the auto-lane list, per-lane Undo, `PreviousRunUndo`, Mark review done).

**Collect** (`collect.py`)
- Reads the manifest's cards and auto.
- `db_choices` (`:136`) reads the owner's choices once `owner_done_at` is set.
- `decision_rows` copies each proposal.
- `write_vetted` (`:213`) is per stage, with `VETTED` at `:97`.

**Apply** (`apply_stage.py`)
- Takes the lease and file lock, then:
  1. `open_stage` checks hashes.
  2. Other-writer checks run.
  3. `plan_decisions`/`record_decisions` (`:628`/`:651`) record the owner's choices.
  4. `apply_batches` runs a pilot then the rest (`PILOT_ROWS = 50`, `:168`) as cut files. Each
     batch is verified from the database and ledgered into `team_cleanup_changes` through
     `ledger_rows` (`:1028`).
  5. `write_record` writes RECORD.md.
- Revert is `revert_stage` (`:1508`): it replays each batch log through `revert_command` (`:576`),
  then `stamp_reverted` (`:1481`).

**Tick and lifecycle**
- `advance.py` `due()` orders work: pages → auto lanes → owner lanes. Nothing orders one stage
  after another.
- `end_run.py`, `status.py` and `run_store.STAGES` (`:98`) already include `merges`.
  `review_keys()` already picks `MERGE_REVIEW_KEYS`.

**The old merge kit, in the repo**
- `.claude/skills/merging-duplicate-teams/scripts/build_review_page.py` has `side()` (`:60`) and
  `manifest()` (`:113`). The manifest maps a card id to merge/keep ids, names and
  `merge_as_vetted`/`keep_as_vetted` via `vetted.stamp`.
- `collect_review_decisions.py` has `DECISIONS` (`:53`, merge/separate/unsure) and `SWAPPED`
  (`:54`), plus `refuse_conflicts` (`:103`), `refuse_kept_apart_joins` (`:113`) and
  `keep_separate_rows` (`:135`).
- The kit shows no shared opponents and no game overlap.

### Reusable Utilities

**Decision records** (`scripts/team_cleanup/decisions.py`)
- `MERGES`, `KEEP_SEPARATE`, `pair_subject` (`:52`) and `keep_separate_row` (`:80`).
- `keep_separate_index`/`kept_apart_reason`, which are merge-resolved.
- `card_rows` (`:93`) is shape-agnostic. It needs only `card["id"]` and `card["n"]`.

**Recorded team values** (`scripts/team_cleanup/vetted.py`)
- `IDENTITY_FIELDS` (age_group, gender, state_code, club_name), `stamp()` and
  `changed_since_vetted()`.

**Database reads** (`scripts/find_cross_provider_duplicates.py`)
- Paging and batching: `page`, `batched`, `load_merge_map`, `merged_into`.
- `load_keep_separate`, which fails closed.
- `build_evidence` (`:288`) returns games, excluded, dates, opponents, self_play and aliases. Shared
  opponents are `opponents[a] & opponents[b]` and shared dates are `dates[a] & dates[b]`.
- `screen` computes `opponent_jaccard`.
- `tier_for` (`:421`) defines `1_provably_safe`.

**The two scanners**
- Doorway D, `scripts/find_squad_key_duplicates.py`:
  - `--state` is required.
  - It writes `squad_key_duplicates_<xx>.json` (proposals), `_all.json`
    (`{proposed, held, rejected}`) and a CSV.
  - Each record carries status, reason, both names and original names, providers, games,
    `merge_id`/`keep_id` and `merge_as_vetted`/`keep_as_vetted`.
  - It honours Keep separate, and its `direction()` applies the owner's survivor order.
- Doorway C, `find_cross_provider_duplicates.py`:
  - `--state` is optional.
  - It writes fixed-name `cross_provider_duplicates.json` and `.csv`.
  - It records tier, `opponent_jaccard`, competing partners and
    `alias_already_points_at_gotsport`.
  - It honours Keep separate.

**The applier and its cleanups**
- `scripts/apply_vetted_team_merges.py`:
  - Flags: `--file`, `--execute`, `--limit`, `--out`. `MERGED_BY = "pitchrank-operator"` is
    hardcoded (`:62`) and passed as `p_merged_by` to the `execute_team_merge` RPC (`:290-293`).
  - It resolves chains, drops conflicts, skips kept-apart pairs and re-reads each pair before
    merging.
- Revert:
  - `revert_fuzzy_auto_merges.py` filters by actor and `--since` only.
  - The per-merge alternative is the RPC `revert_team_merge(p_merge_id, p_reverted_by,
    p_revert_reason)` (`supabase/migrations/20251208000003_create_team_merge_audit.sql:190`).
- `scripts/exclude_merge_duplicate_games.py` (`--scope`, `--execute`, `--limit`, `--out`) sweeps
  every merge cluster ever. It has no per-batch scope and no `--revert`.
- `scripts/check_merge_skill_assumptions.py --code-only` follows the self-check contract.

### Convention Anchors

Every place listed here admits only clubs, states and ages today. Each must be registered for merges.

**Python**
- `propose_week`: `PROPOSED_STAGES`, `NOT_RUN`, `FIELDS`, `SELF_CHECKS`, `APPLIER_INPUTS`,
  `stage_commands`, `scoped_proposals`.
- `sure.sure_because`.
- `pages`: `TITLES`, `WHOLE_TIERS` (`whole()` raises KeyError for an unknown stage), `group_of`,
  `sort_out`, `change_id`, `card`.
- `collect.VETTED`.
- `apply_stage`: `APPLIERS`, `APPLIER_LOGS`/`LOG_READERS`, `LOG_CHANGES`, `applier_command`
  (its fallthrough is states), `cut_name`/`write_cut`, `vetted_changes`, `revert_command`,
  `revert_refusal`, `lane_teams`, `write_record`.
- argparse `choices=PROPOSED_STAGES` in pages, collect and apply_stage.
- Single-team row shape: `write_guard.stale`, `decisions.team_decision_row`, `plan_decisions`,
  `verify`/`ledger_rows`, `replay_sure.stage_cards`.

**Database**
- `team_cleanup_cards.stage` CHECK (`20261017120000_add_team_cleanup_cards.sql:16`) and
  `team_cleanup_requests.stage` CHECK (`20261019120000_add_team_cleanup_requests.sql:10`) lack
  `merges`.
- `team_cleanup_decisions` and `team_cleanup_changes` already allow it.
- `team_cleanup_changes.field` and `new_value` are NOT NULL.

**Frontend**
- `CLEANUP_STAGES` and `STAGE_LABELS`, the `CleanupCard` type, `CleanupCardView`, and the
  auto-lane list and `PreviousRunUndo` in `CleanupReview.tsx`.

**Safety conventions**
- Dry run unless `--execute`; exit 75 for waits; lease and file lock.
- Writer checks before every batch.
- Verify from the database, then ledger.
- Pilot, then the rest, as cut files.

**Tests**
- One file per module, `tests/unit/test_team_cleanup_<module>.py`. Each fake records at
  `execute()` and refuses what PostgREST refuses. Scripts are stood in for by `_Runner`.
- Stage pins that must change together:
  - the migration IN-list tests (`test_team_cleanup_cards_migration.py:92`,
    `test_team_cleanup_requests_migration.py:50`), which read only the newest `CREATE TABLE`
  - the `NOT_RUN` note pins in `test_team_cleanup_propose_week.py`, `test_team_cleanup_advance.py`
    and `test_team_cleanup_end_run.py`
  - the shipped-caps test (`test_team_cleanup_pages.py:1333`)

### Proposed Alignment

- Follow the stage pipeline as it stands.
- Reuse the kit's pair shape: two sides, the `_as_vetted` stamps, the swap, and the conflict and
  kept-apart refusals. Add shared opponents and date overlap from `build_evidence`.
- Limit the automatic lane to `1_provably_safe`.
- Close two gaps first, because each breaks the per-lane batch contract: undo by batch, and a
  doubled-fixture repair scoped to one batch.

## Implementation Steps

**Setup.** Build in `C:\pitchrank-cleanup-loop`, never `C:\PitchRank`, which is far behind and holds
unrelated dirty files.

- Before each PR, run `git fetch --all --prune` and branch from `origin/main`. Confirm with
  `git status --short` that the only untracked file is `.turbo/plans/team-cleanup-orchestrator.md`,
  and never stage that file.
- Ship three PRs in order, each branched from `main` after the previous one merges. PR 2 itself must
  not merge before its migration is applied and ledgered: the review page's GET and the decisions
  route select `swap`, so a deploy ahead of the column takes the whole review page down.
- The run open when this plan was written, `2026-10-22-all`, is pinned to its own code
  (`autopilot.json`) and keeps "merges: not run". The first run with merges is the next Wednesday
  propose after PR 3 merges and `C:\pitchrank-weekly` is re-pinned.

### PR 1: make the merge tools work one batch at a time

1. **Extract the kit's pair helpers into `scripts/team_cleanup/pairs.py`**
   - Move these from `.claude/skills/merging-duplicate-teams/scripts/collect_review_decisions.py`:
     - the `SWAPPED` mapping (`:54`), as `swapped(record) -> dict`
     - `refuse_conflicts` (`:103`)
     - `refuse_kept_apart_joins` (`:113`)
     - `keep_separate_rows` (`:135`), as `page_keep_separate_rows`
   - Move `side()` (`:60`) from `build_review_page.py`.
   - Both kit scripts import them from the new module, so their behaviour is unchanged and
     `tests/unit/test_build_review_page.py` plus the collector's tests stay green unedited.
   - Keep the import packaged (`from scripts.team_cleanup.pairs import ...`).
2. **`scripts/apply_vetted_team_merges.py`: a run's own actor, and per-batch revert**
   - `--actor` (default `MERGED_BY`) is passed as `p_merged_by`; a revert is recorded as that
     actor plus `:revert`.
   - Each log entry is written before its merge is sent. It records `merged_by`, the incoming
     `team_merge_map` rows and alias rows the merge will repoint (`incoming_ids`, `alias_ids`), and
     the merge's own `team_merge_map` row (`map_id`). That row is read back after the call, because
     postgrest-py can turn the RPC's reply into an exception; `map_read` says whether the
     read-back ran.
   - `--out` refuses an existing file, since a log may be the only record a revert can replay.
   - `--revert <log>`, a dry run unless `--execute`, replays the log newest first:
     `revert_team_merge` on `map_id`, then the incoming rows and aliases are pointed back while
     they still point at the survivor. A merge whose row is gone counts as already reverted. An
     entry whose run never read back its merge row stops the revert, to be settled by hand per the
     skill's Step 6.
3. **`scripts/exclude_merge_duplicate_games.py`: scope to one batch, and undo**
   - `--merge-log <applier log>` limits the clusters to those of every logged entry's `keep_id`,
     resolved through `team_merge_map`. The grouping key and the raw-master-id discriminator stay
     exactly as they are.
   - Every run, flagged or not, leaves in place a copy whose exclusion `trg_propagate_game_exclusion`
     would carry to another copy outside the run, so every game a run hides is in its log. `--limit`
     applies before that check, and every `--execute` run writes a log recording `sent`, empty when
     nothing is excluded.
   - `--revert <its own log>` sets `is_excluded = false` on the first `sent` logged rows and any
     later logged row sharing their cascade key, each only while still excluded, then stamps the
     log `reverted_at` so it cannot be replayed.
4. **Tests**
   - `tests/unit/test_apply_vetted_team_merges.py`: the actor reaches the RPC, `--revert` replays
     in reverse, and a dry-run revert writes nothing.
   - `tests/unit/test_exclude_merge_duplicate_games.py`: `--merge-log` leaves other clusters alone,
     and `--revert` restores only logged ids.
   - Assert expected values as literals.

### PR 2: database and website pair cards

5. **Migration `supabase/migrations/<ts>_team_cleanup_cards_merges.sql`**
   - Widen the `stage` CHECK on `team_cleanup_cards` and `team_cleanup_requests` to add `'merges'`,
     using `DROP CONSTRAINT IF EXISTS` then `ADD CONSTRAINT`. Both CHECKs were declared inline, so
     Postgres named them `<table>_stage_check`.
   - Add `team_cleanup_cards.swap BOOLEAN NOT NULL DEFAULT false`.
   - Grants and RLS are unchanged; confirm both creating migrations' policies still cover the new
     column.
   - The owner applies it by hand and ledgers it with `supabase migration repair --status applied`
     from `C:\pitchrank-cleanup-loop`, after copying `C:\PitchRank\supabase\.temp` in.
   - Run the `migration-reviewer` agent on the PR.
6. **Make the migration tests read the effective final constraint**
   - The stage pins `test_a_card_s_stage_and_decision_are_the_ones_the_loop_uses` and
     `test_a_request_names_a_stage_and_lane_the_loop_runs` read only the newest `CREATE TABLE`.
     Resolve each table's stage CHECK across `CREATE` and every later `ALTER ... CONSTRAINT` in
     `supabase/migrations/*.sql`, per CLAUDE.md.
   - Assert `_stage_values(table) == (*PROPOSED_STAGES, MERGES) == ("clubs", "states", "ages",
     "merges")`: the tables admit merges a PR before the loop proposes it. PR 3 replaces
     `(*PROPOSED_STAGES, MERGES)` with `PROPOSED_STAGES`.
7. **`frontend/lib/mission-control/cleanup.ts`**
   - Add `'merges'` to `CLEANUP_STAGES` and label it "Duplicate teams" in `STAGE_LABELS`.
   - A card row's stage decides its shape: every merges card is a pair card, every other card a
     team card. Cards carry no `kind`.
   - A pair card is the card base (`id`, `n`, `group`, `whole`, `alike`, `interest`, `sure`, `why`)
     plus `merge` and `keep` sides and `evidence: {doorway: 'C' | 'D', shared_opponents,
     shared_opponent_names (up to five), shared_dates, opponent_overlap (0 to 1, null when either
     row has no opponents)}`. `why` says why the scan paired them (step 16); the owner's swap lives
     in the `swap` column, never in the card.
   - A side is the team block of a single-team card (name, original, club, state, age, gender,
     provider, games, excluded, first, last) plus `team_id`.
8. **`components/mission-control/cleanup/PairCardView.tsx`** (new)
   - Layout (owner-approved): the kept row first, labelled "Kept", the other "Merged into the kept
     team"; side by side, stacked at phone width. "Keep the other one" trades the two.
   - Evidence lines: how the pair was found; shared opponents, with their names; opponent overlap
     as a percentage; days both played. The `why` line sits above them.
   - Buttons: **Merge them** / **Keep separate** / **Not sure**, mapped to apply / dont_apply /
     unsure. Plus a "Keep the other one" swap toggle and a note.
   - Reuse `CleanupCardView`'s button, note and saving patterns.
9. **`CleanupReview.tsx`**
   - Render `PairCardView` for pair cards.
   - Give pairs a one-line form ("A → kept as B") in the auto-lane list.
   - Never offer "Apply every undecided card here" on merges, and count the tally in the pair
     buttons' words.
   - `PreviousRunUndo` lists only the stages the last finished run published cards for; a run from
     before merges therefore shows no merges Undo. The undo route needs no stage-specific branch.
10. **`frontend/app/api/mission-control/cleanup/decisions/route.ts`**
    - Accept an optional boolean `swap` on merges cards only, and refuse it on other stages.
      Persist it and echo it in the POST's reply; the review route's GET (`cleanup/route.ts`)
      returns it with each card.
    - The pair card is inert until PR 3, because no merges cards exist yet.
11. **Frontend tests**: Vitest for the pair card (swap flips the marked survivor, labels map to the
    stored decisions) and for the decisions route (`swap` refused on a states card).

### PR 3: the orchestrator's merges stage

12. **Caps**
    - Add `"merges": {"cards": 100, "auto": 50}` to `page_caps` in `config/team_cleanup.json`.
    - `pages.load_caps(path, stage)` returns a stage's override when present, else the global pair.
    - Update the shipped-caps test (`test_team_cleanup_pages.py:1333`) with literal values for both.
13. **`scripts/team_cleanup/propose_week.py`**
    - Registration:
      - Add `MERGES` to `PROPOSED_STAGES` and delete `NOT_RUN[MERGES]`.
      - `SELF_CHECKS[MERGES]` runs `scripts/check_merge_skill_assumptions.py --code-only`.
      - `FIELDS[MERGES] = "merged_into"`.
      - `APPLIER_INPUTS[MERGES]` is `merges/pairs.json`.
    - `stage_commands(MERGES)`, output under `merges/scans/`:
      - `find_cross_provider_duplicates.py` once, nationally. With a state scope, run it once per
        state.
      - `find_squad_key_duplicates.py --state <xx>` for each state in scope. For ALL, that is every
        state code holding a live team, read with paging.
      - Both run without `--execute`, which neither registers.
      - Measure the all-states runtime during implementation. If it passes about 15 minutes, run
        the squad-key scan in-process rather than one subprocess per state.
    - `scoped_proposals(MERGES)`:
      - Take only proposed records: Doorway C's proposal tiers and Doorway D's `status == proposed`.
      - Normalise each into one pair row: `merge_id`, `keep_id`, `merge_name`, `keep_name`,
        doorway, tier or status, `merge_as_vetted`, `keep_as_vetted`,
        `alias_already_points_at_gotsport`, games on each side.
      - Dedupe on the unordered pair, keeping the Doorway C record.
      - Drop any pair whose team appears in this run's clubs, states or ages `proposals.json`, so
        it waits a week rather than racing another stage's write.
      - Write `pairs.json` in the applier's input format.
      - Carry the held and rejected counts by reason (from Doorway D's `_all.json` and Doorway C's
        CSV) for the manifest's `left_out`.
14. **`scripts/team_cleanup/write_guard.py`**: add a pair branch to `stale()`. A pair is stale when
    either team was deprecated, or when `vetted.changed_since_vetted` reports either side changed.
    The single-team branch is untouched.
15. **`scripts/team_cleanup/sure.py`**
    - In `sure_because(MERGES)`, a pair is sure only when doorway is C and tier is
      `1_provably_safe`.
    - In `reverted_changes`, key merges as `(merge_id, "merged_into", keep_id)`, so a reverted pair
      is never sure again.
16. **`scripts/team_cleanup/pages.py`**
    - Set `TITLES[MERGES] = "Duplicate teams"`, and make `whole()` return False for a stage with no
      `WHOLE_TIERS` entry.
    - Key `sort_out`/`change_id` on the pair id `card_id(run, f"{merge}_{keep}")`, as the kit does.
    - Order owner cards by doorway C identical-name, then doorway D, then by fewer games on the
      retiring side. Cap them with the merges caps.
    - `build()` reads teams and games for both `merge_id` and `keep_id` of every pair, plus the
      shared opponents' names; today it reads only each proposal's `team_id_master`.
    - New `pair_card()`, in exactly the shape step 7 gives the page:
      - the card base. `group` is the owner-card ordering bucket, "C identical name" then
        "D squad key" (the page shows it after "Tier"); `group_of()` cannot supply it, since it reads
        a `tier` key Doorway D rows lack. `alike` is null; `interest` is true when either side is of
        interest. `why` is a sentence `pair_card()` composes from the pair row, since neither scanner
        gives a proposed pair a reason (Doorway D writes an empty `reason`, Doorway C none): for C
        the shared name and the two providers, for D the squad key the two spellings share.
      - `merge` and `keep` from `pairs.side()`, rebuilt on a new team-block helper that `card()`
        also uses for `team`, plus `team_id`, so a side carries the normalised `state` a single-team
        card does; the kit's page gains `state` and keeps working.
      - evidence from the `build_evidence` result: `doorway` from the pair row; `shared_opponents`,
        the size of `ev.opponents[merge] & ev.opponents[keep]`; `shared_opponent_names`, the first
        five of those by name; `shared_dates`, the size of `ev.dates[merge] & ev.dates[keep]`;
        `opponent_overlap`, shared over union rounded to 3 as `screen()` computes `opponent_jaccard`,
        or null when either set is empty. Compute it here: the pair row carries no jaccard, Doorway D
        never measures one, and the scanner's 0.0 for an empty side would read as measured.
      - no `kind` and no `swap`: the stage marks a pair card, and swap is a column defaulting false
    - Add a test that builds a pair card and asserts, as literal key sets, the card's, each side's
      and the evidence's keys from `PairCard`, `PairSide` and `PairEvidence` in `cleanup.ts`, so the
      Python writer and the page cannot drift apart unseen.
    - The manifest records `merge_as_vetted`/`keep_as_vetted` through `vetted.stamp`, as the kit's
      `manifest()` does.
17. **`scripts/team_cleanup/collect.py`**
    - Set `VETTED[MERGES] = "vetted.json"`, and read `swap` alongside each decision in `db_choices`.
    - For apply cards, build the merge list with `pairs.swapped` where swapped, then call
      `pairs.refuse_conflicts` and `pairs.refuse_kept_apart_joins`.
    - Keep separate needs no vetted row. The apply step records it.
    - The auto lane collects the sure pairs unchanged.
18. **`scripts/team_cleanup/apply_stage.py`**
    - Applier and pilot:
      - `APPLIERS[MERGES] = "apply_vetted_team_merges.py"`.
      - `applier_command(MERGES)` passes `--file <cut> --execute --actor team-cleanup:<run> --out
        <batch log>`. Add an explicit merges branch rather than relying on the states fallthrough.
      - Make the pilot size per stage: 25 for merges, 50 otherwise.
    - After each merges batch, run `exclude_merge_duplicate_games.py --merge-log <batch log>
      --execute --out <exclude log>`, so the survivor's doubled fixtures are excluded before
      Monday's ranking run.
    - Decisions and ledger:
      - `plan_decisions`/`record_decisions` take pair rows. A Keep separate goes in through
        `decisions.keep_separate_row`; Merge and Not sure through a new `pair_decision_row` in
        `decisions.py`.
      - Verification from the database: `merge_id` is deprecated, `team_merge_map` maps it to
        `keep_id`, and `keep_id` is live.
      - `ledger_rows`: `team_id_master = merge_id`, `field = "merged_into"`, `old_value = null`,
        `new_value = keep_id`.
    - Before each merges batch, read this run's `team_cleanup_changes` for the other stages and drop
      any pair touching those teams, recorded as "changed this week". This backs up the applier's
      own `changed_since_vetted` refusal.
    - Revert:
      - `revert_command(MERGES)` replays each batch in reverse: the exclude log's `--revert` first,
        then the applier's `--revert`.
      - `stamp_reverted` for merges stamps a change when `merge_id` is live again.
      - `lane_teams` returns both ids.
      - `write_record` lists pairs by name.
    - `APPLIER_SCRIPTS` already lists both scripts.
19. **`scripts/team_cleanup/advance.py`**: in `due()`, order the merges lanes after the other
    stages' lanes of the same kind, so another stage's changes land before a merge reads them.
    Nothing else is stage-specific; `end_run` and `status` already iterate `STAGES`.
20. **Tests**, one per module and following each file's existing fakes:
    - **Propose:** both scans run, neither with `--execute`; dedupe keeps C; a team in another
      stage's proposals drops its pair.
    - **Sure:** only `1_provably_safe` is sure, and a reverted pair is never sure.
    - **Pages:** pair card contents, the 100-card cap, `whole()` for merges.
    - **Collect:** swap, conflict refusal, kept-apart refusal.
    - **Apply:** the pilot is 25; the exclude step runs once per batch with that batch's log; the
      ledger shape; Keep separate is recorded; revert runs the two replays in order.
    - **Pins:** update the `NOT_RUN` pins, and in both migration tests' stage pins replace
      `(*PROPOSED_STAGES, MERGES)` with `PROPOSED_STAGES`. Revert each half of every compound guard
      on its own and confirm the new test is among those that fail.
21. **Docs**
    - The running-team-cleanup skill gets a merges section: what reaches a card, what merges on its
      own, how Undo reverses a merge, and the 100-card cap.
    - `.claude/skills/merging-duplicate-teams/SKILL.md` notes that the weekly cleanup runs Doorways
      C and D, and that its auto lane is the provably safe tier only. Update `RECORDED` in
      `scripts/check_merge_skill_assumptions.py` if a checked claim changes.
    - Close any backlog entry this finishes in the same PR.

## Verification

- `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py` and
  `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` for each PR. PR 2
  also needs the frontend gate (`npx eslint .`, `npx prettier --check .`, `npm run typecheck`,
  `npm run test`).
- **PR 1:** dry-run `exclude_merge_duplicate_games.py --merge-log <old applier log>`; it should
  name only that log's clusters. Dry-run `apply_vetted_team_merges.py --revert` on the same log: an
  old log records no merge row, so every entry should be refused as predating `--revert` and the
  run should exit 1. Nothing is written. The revert path itself is exercised in the first live
  week's Undo.
- **PR 2:** before merging, after the owner applies the migration, confirm from the database that
  both CHECKs accept `merges`, that `swap` exists, and that the anon key still gets 42501 on
  `team_cleanup_cards`. Then, on a preview deployment, confirm the existing stage tabs render
  unchanged and the last finished run's Undo lists only the stages it published, with no Duplicate
  teams entry.
- **PR 3:** propose one small state into a scratch store with
  `propose_week.py --states <xx> --store <scratch> --date <unused> --dry-run`, build its merges
  page into the same store, and check:
  - every card carries both sides and evidence
  - at most 100 owner cards
  - auto holds only `1_provably_safe`
  - no pair touches a team in that run's other proposals

  Then dry-run `apply_stage.py --stage merges` and `--lane auto`. Each should list a pilot of 25
  and one exclude call per batch.
- **First live week:**
  - After the auto lane's pilot, confirm from the database that each pilot `merge_id` is
    deprecated and mapped to its `keep_id`, and that the survivor holds no doubled fixture.
  - Press Undo on one merge-lane batch and confirm the retired rows are live again and their
    excluded games restored.

## Context Files

- `scripts/team_cleanup/propose_week.py`: stage registration and the propose flow.
- `scripts/team_cleanup/pages.py`: the card build, caps and manifest.
- `scripts/team_cleanup/apply_stage.py`: lanes, batches, ledger, revert.
- `scripts/team_cleanup/collect.py` and `scripts/team_cleanup/sure.py`: the choices and the auto
  split.
- `scripts/team_cleanup/decisions.py` and `scripts/team_cleanup/vetted.py`: Keep-separate records
  and recorded team values.
- `scripts/team_cleanup/pairs.py`: the pair side, the swap, and the conflict and kept-apart
  refusals, which the kit's `build_review_page.py` and `collect_review_decisions.py` now import.
- `scripts/find_cross_provider_duplicates.py` and `scripts/find_squad_key_duplicates.py`: scanner
  output and evidence.
- `scripts/apply_vetted_team_merges.py` and `scripts/exclude_merge_duplicate_games.py`: the
  applier and the doubled-fixture repair.
- `frontend/lib/mission-control/cleanup.ts`,
  `frontend/components/mission-control/cleanup/CleanupReview.tsx` and `CleanupCardView.tsx`: the
  website page.
- `.claude/skills/merging-duplicate-teams/SKILL.md`: safety rules, survivor order, the provably
  safe class.
- `.turbo/plans/team-cleanup-orchestrator.md` (untracked, in `C:\pitchrank-cleanup-loop`): the
  stage 5 design notes.
