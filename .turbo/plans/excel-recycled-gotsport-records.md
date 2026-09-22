# Recycled GotSport records: splitting two Excel Soccer Academy squads

**Status**: game surgery applied 2026-09-21. One merge and one scrape outstanding.
**Trigger**: a trial subscriber reported that an Arizona U17 girls team shows another squad's
games and is missing its own recent results.

## What went wrong

A GotSport team record is supposed to be a squad that ages one group per season. Excel Soccer
Academy handed two of its records to different squads at the August 2026 rollover, and we file
games by the record.

Verified from `system.gotsport.com/api/v1/teams/<id>/matches`, reading the division label each
record played under per season:

| GotSport record | 2024-25 | 2025-26 | 2026-27 |
|---|---|---|---|
| 496639 | U15 | U16 | **U16** |
| 496638 | U16 | U17 | **U17** |

Both sat flat across a rollover, which a real squad cannot do. Every other club in the same DPL
bracket advanced by one: RSL 11125 (U14→U15→U16), Arsenal 121571 (U15→U16), RSL 11117 (U16→U17),
Arsenal 79701 (U16→U17). A third Excel record, 380969, went U15B→U14B — backwards.

So the squad that held 496639 through April 2026 now holds 496638, and 496639 was handed to the
club's U16 squad. The subscriber's two named results (a 3-0 on 2026-09-12 and a 7-0 on 2026-09-19)
are on 496638, which confirms it.

## The shape of the fix

Each record keeps the alias it has. What moves is the games, because the alias describes who the
record serves **now** and the games describe who played them.

| Row | Alias | Becomes |
|---|---|---|
| `cc2800e4-bea2-4901-9930-66a02d3d7b23` | 496638 | the subscriber's U17 squad, 2024-11 to date |
| `ddb476c7-4736-454d-983a-db6f04d20376` | 496639 | the club's U16 squad |
| `ba65a568-3516-4158-8c03-aa31471a22c0` | none (`archive_excel_2009_496638`) | the 2009 squad's history |
| `e48170eb-f964-42c9-8fba-ac6d4e6b92c0` | 121236 | emptied; merges into the U17 row |

**Do not merge `ddb476c7…` into the U17 row.** An earlier draft of this plan said to, so that the
subscriber's existing link kept resolving. It would have been wrong: that row owns alias 496639,
so the merge would route the U16 squad's future games into his team permanently. The stale link
resolving to the U16 team is the smaller cost.

Reconcile needs no exclusion either. GotSport labels 496638 U17 and 496639 U16, which — now that
each row holds the squad that occupies that bracket — is correct for both, so
`reconcile_teams_with_gotsport.py` reinforces these values instead of fighting them.

## Applied 2026-09-21

`scripts/reassign_games_between_teams.py`, one run per block, each verified in the database:

| From | To | Window | Games |
|---|---|---|---|
| `e48170eb…` | `cc2800e4…` | `--before 2026-08-01` | 3 |
| `cc2800e4…` | `ba65a568…` | `--before 2026-08-01`, less the 3 above | 16 |
| `ddb476c7…` | `cc2800e4…` | `--before 2026-08-01` | 20 |

Result: 35 games on the U17 row spanning 2024-11-03 to 2027-04-11, 11 on the U16 row, 16 on the
archive row, none half-attached. `ddb476c7…` relabelled to `Excel U16 DPL` / `u16`.

Two mechanics the blocks taught, both now in the script:

- A game's team cannot be changed by an UPDATE. `enforce_game_immutability` admits a team change
  only as a clear or a fill, never a swap, so the script moves each side through
  `unlink_game_team` then `link_game_team`. The side is NULL in between, and **a game left in
  that state cannot be recovered by rerunning the block** — it names neither team on the moved
  side, so the team-and-window query no longer selects it. `--resume <log>` addresses each game
  by id and is the only route back. An earlier draft of this file said a rerun finished the job;
  it does not, and the code comment saying so was wrong in the same way.
- **Move games out of a destination before moving any in.** The first block put three games onto
  the U17 row inside the same date window the second block was about to sweep, and a date window
  cannot tell them apart. `--exclude` covers the case; ordering avoids it.

## Outstanding

1. **The scrape.** Queued at priority 1 (`1e904031-f026-40d6-b44a-a77e6ebcc020`) so the 3-0 and
   7-0 pick up their scores — both rows are imported but carry nulls, because 496638 was last
   scraped 2026-09-07.
2. **The merge the subscriber asked for.** `e48170eb…` now holds zero games and is a dead record
   of the same squad. It matches `merging-duplicate-teams` on club, state and age group.
3. **Rankings.** The U17 row goes from 16 ranked games to 35 and the archive row starts at 16;
   the U16 row has 11, below `MIN_GAMES_PROVISIONAL` (12), so it will not publish a rank until it
   plays again. Monday's run regroups all three.

## Follow-up: detect recycled records

A GotSport record whose event-division age fails to advance, or falls, between seasons has changed
hands. That is one pass over the matches API per record and produces a review queue instead of a
customer email. Size it read-only before building anything.

Two pre-existing conditions surfaced while verifying and are not from this work: 3,493 games carry
a NULL on one side and 1,076 have the same team on both sides.
