# Recycled GotSport records: splitting two Excel Soccer Academy squads

**Status**: drafted 2026-09-21, not applied
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

## Current state

| Row | `team_id_master` | GotSport | ≤ 2026-04 | ≥ 2026-09 |
|---|---|---|---|---|
| `Excel U17 DPL` (u17) | `cc2800e4-bea2-4901-9930-66a02d3d7b23` | 496638 | 16 games — 2009 squad | 12 games — **the U17 squad** |
| `Excel Soccer Academy 2010 NL P1` (u17) | `ddb476c7-4736-454d-983a-db6f04d20376` | 496639 | 20 games — **the U17 squad** | 11 games — U16 squad |
| `Excel Soccer Academy 2010 NL` (u17) | `e48170eb-f964-42c9-8fba-ac6d4e6b92c0` | 121236 | 3 games — **the U17 squad** | — |

Each live row is half one squad and half another. The U17 squad's three seasons are spread across
all three rows.

`Excel U17 DPL` was named `Excel Soccer Academy 2009 G NL P1` at u19 until 2026-09-21 21:57, when
`reconcile_teams_with_gotsport.py` rewrote its name and age group from GotSport's current payload.
That job is the reason any name or age fix here is temporary unless the row is excluded from it.

## Steps

### 1. Wait for the reconcile batch to finish

7,893 teams were rewritten on 2026-09-21 without being scraped, 387 of them in the final hour.
Nothing below should run while that is in flight.

### 2. Build the two new rows

- A u19 row for the **2009 squad**, no provider alias (GotSport no longer serves it).
- A u16 row for the **U16 squad**, which takes over alias 496639 in `team_alias_map`.

Neither is a merge candidate against an existing Excel row: `Excel Soccer Academy U16 Black`
(760162) and `Excel Soccer Academy 2011 Black` (380969) are different squads, and 380969 is a
boys record GotSport now serves as `Excel Soccer Academy U14 Black`.

### 3. Move the four blocks

Run `scripts/reassign_games_between_teams.py` once per block, dry run first:

| From | To | Window | Games |
|---|---|---|---|
| `ddb476c7…` (496639) | `cc2800e4…` (U17) | `--before 2026-08-01` | 20 |
| `e48170eb…` (121236) | `cc2800e4…` (U17) | `--before 2026-08-01` | 3 |
| `cc2800e4…` (496638) | new u19 row | `--before 2026-08-01` | 16 |
| `ddb476c7…` (496639) | new u16 row | `--since 2026-08-01` | 11 |

`cc2800e4…` then holds the U17 squad continuously from 2024-11 to now, on the alias GotSport
still serves it under.

### 4. Rescrape 496638 at priority 1

The 3-0 and the 7-0 are already imported but carry null scores — that record was last scraped
2026-09-07. `enqueue_scrape_request` on `cc2800e4…`, priority 1.

### 5. Retire the emptied row

`ddb476c7…` ends with no games and no alias. Point it at `cc2800e4…` through `team_merge_map` so
the subscriber's existing link still resolves.

### 6. Keep reconcile off these rows

Otherwise the next pass re-applies GotSport's bracket-slot names (`U16G DPL`, `U17G DPL`) and
whatever age group the club registered under.

## Risks

- **Re-import of a moved block.** A moved game's `game_uid` is built from master ids, and a later
  import of the same physical game resolves the alias to a different row, so it inserts rather
  than matching. `process_missing_games` only scrapes 90 days back, so the three pre-April blocks
  are out of reach — but a full-history rescrape of 496639 (`scrape-games.yml`, or `drain_queue`
  with a `--since` override) would re-create the U17 squad's old games under the U16 row. Check
  after any bulk rescrape of this club.
- **Rankings.** Moving 20 games onto `cc2800e4…` and 16 off it changes both teams' game counts
  across `MIN_GAMES_PROVISIONAL` (12). Measure before applying; the U17 row ends at 39 games, the
  new u19 row at 16, the new u16 row at 11 — the last one is below the threshold and will not
  publish a rank until it has played more.
- **This is not the only club.** See below.

## Follow-up: detect recycled records

A GotSport record whose event-division age fails to advance, or falls, between seasons has changed
hands. That is one pass over the matches API per record and produces a review queue instead of a
customer email. Size it read-only before building anything.

## Verification

1. `cc2800e4…` holds 39 games, first 2024-11-03, last the 7-0, with no gap between 2026-04 and
   2026-09.
2. The 2026-09-12 and 2026-09-19 rows carry 3-0 and 7-0.
3. No game has the same team on both sides.
4. `ddb476c7…` holds zero games and resolves through `team_merge_map`.
5. Each apply log reverts cleanly on a scratch check before the next block runs.
