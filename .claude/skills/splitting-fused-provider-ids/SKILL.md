---
name: splitting-fused-provider-ids
description: "Fixes a PitchRank team row whose games belong to more than one real squad because several provider ids point at it: an ECNL and an ECNL-RL id on one row, or a TGS/GotSport id that the club handed to a younger squad at the Aug 1 rollover so its new games sit on last season's team. Reads each id's opponents by season to say which squad it is, then gives each squad its own row, repoints the aliases and moves the games, every write dry-run first, logged and reversible. Use when asked why a game is filed under the wrong team, why a team has games against the wrong cohort or the RL team instead of the ECNL team, to split a fused team, to move one id's games to another team, or when a team's history mixes ECNL with ECNL-RL or two birth-year cohorts."
---

# Splitting fused provider ids

A team row holds every game of every provider id aliased to it. When a row carries two squads' ids (ECNL and ECNL-RL, or an id reused at the rollover), its games, record and ranking mix two teams. The fix is per id: decide which squad each id is in each season, then move aliases and games to a row for that squad. The merging-duplicate-teams skill's "Splitting a fused row" covers the same operation for a squad that arrived through a merge or sits on a SincSports row; revert a merge there rather than moving its games here.

```
Task Progress:
- [ ] Step 1: Name the ids on the row
- [ ] Step 2: Read each id's squad by season
- [ ] Step 3: Draw the map
- [ ] Step 4: Check the targets
- [ ] Step 5: Apply
- [ ] Step 6: Verify and record
```

Credentials come from root `.env`, with `.env.local` layered over it. Run every script from the main checkout; logs land in `data/exports/`. Games are immutable: the scripts change which team a game side points at and nothing else.

## Step 1: Name the ids on the row

List every alias on the wrong row and on the sibling rows of the same club, gender and cohort band:

```sql
select a.provider_team_id, p.code, a.team_id_master, a.review_status from team_alias_map a
join providers p on p.id = a.provider_id
where a.team_id_master in (<row ids>);
```

Count each id's games by season from `games`, grouping on the side's team and provider id (`home_provider_id` / `away_provider_id`) with `games.provider_id`. Include rows merged into the wrong row (`team_merge_map`), since games keep the pre-merge team id.

## Step 2: Read each id's squad by season

Run `list_id_games.py` per id with `--before` and `--since` set to the Aug 1 season start (arguments in Step 5). It prints opponent names and the event for each game. Opponent names that state a cohort (`G2011/12`, `ECNL RL 2012`) are the witnesses; opponents' stored `age_group` is circular, since the same imports set it. Two patterns decide the case:

- **ECNL and RL on one row.** One id's opponents are ECNL teams and the other's are `RL` or `ECNL-RL` teams, in the same cohort. They are two squads, since ECNL and ECNL-RL are different competitions.
- **Reused id.** Read the cohort as a birth-year band (`2011/12`), never as a U-age. A squad that keeps its id moves up one U-age each season; an id handed to a younger squad plays the same or a lower U-age after Aug 1, and its opponents' bands step one band younger. Its games before Aug 1 belong to the old squad and its later games to the new one. A club that shifts every id down a year makes a chain: id X's old squad now plays on id Y, so X's pre-Aug 1 games go to the row Y's squad lives on.

An id whose opponents stay in one band is not reused; leave its games alone. A GotSport id belongs to a squad when its fixtures and scores match that squad's results on the provider's own team page.

## Step 3: Draw the map

Write one line per id and period: `<provider>:<id> <before/after Aug 1> -> <squad row>`. The alias follows the squad that uses the id now, so a reused id's alias goes to the new squad's row and its pre-Aug 1 games to the old squad's row. Existing live rows for the squad (same club, band, gender, ECNL vs RL) are targets; create a row only when none exists, named like its siblings (`<Club> ECNL G2011/12`, `<Club> ECNL RL G2011/12`) with the stored age group for that band.

Present the map and the game counts to the user before Step 5 when any id is ambiguous or a squad's old games would join a row that already holds a season of its own, since that fuses two squads. Where nobody can say where the old squad went, leave those games in place and say so.

## Step 4: Check the targets

- **Duplicate fixtures.** The same fixture recorded by two providers doubles a result. Compare the dates of the games being moved with the target's existing games; remove an overlapping game from the ids file and list it in the report.
- **`teams.provider_team_id` is unique per provider**, deprecated rows included. When the new row's first alias id is taken, pass `--own-provider-team-id` with a unique value (`<id>-<season>`) for a row that only holds history and current games by alias. When the taken id is the fused row's own `provider_team_id`, repoint that column to an id that stays and give the real id to the new row, so scrape jobs that read `teams.provider_team_id` follow the live squad.
- **Unscored fixtures** on the moving id are excluded (`is_excluded`), as the merging-duplicate-teams skill says, since the score import would otherwise add a second row. `move_game_sides.py` skips them and reports each.
- **A game the user's reference page omits** stays out of the ids file; list it in the report.

## Step 5: Apply

Dry-run each command, read it, then add `--execute`. Order: rows and aliases first, games after, so an import in between reads an alias that already points at the new row. Take a created row's id from the `--execute` output; a dry run prints none.

```bash
# new row + alias repoint (the first --alias also supplies the row's provider_team_id)
python .claude/skills/splitting-fused-provider-ids/scripts/split_provider_ids.py \
  --name "<Club> ECNL G2011/12" --club "<Club Name>" --age-group u15 --gender Female --state-code CA \
  --league ECNL --alias tgs:<id>:<current team uuid> [--alias gotsport:<id>:<current team uuid>] [--own-provider-team-id <unique>]

# alias repoint to a row that already exists
python .claude/skills/splitting-fused-provider-ids/scripts/split_provider_ids.py \
  --to-existing <team uuid> --alias tgs:<id>:<current team uuid>

# games held by one id on one team, within a window; build every ids file before the first move
python .claude/skills/splitting-fused-provider-ids/scripts/list_id_games.py \
  --team <team uuid> --provider tgs --provider-team-id <id> [--since YYYY-08-01 | --before YYYY-08-01] --out data/exports/ids_<name>.txt

# move them
python .claude/skills/splitting-fused-provider-ids/scripts/move_game_sides.py \
  --from <team uuid> --to <team uuid> --games-file data/exports/ids_<name>.txt --provider-team-id <id>
```

`split_provider_ids.py` takes `--alias provider_code:provider_team_id:current_master_uuid` and skips an alias that no longer points at the stated team or has no alias row. `move_game_sides.py` moves the side that holds `--from`, which also covers games filed under a merged-away team that `scripts/reassign_games_between_teams.py` refuses. It writes its log before the first write, skips a game that would play itself, an unscored game and a side with another provider id, and stops on an error. Use `reassign_games_between_teams.py` only when every game in the window belongs to the squad being moved; otherwise pass `--exclude`.

A move is a clear then a fill, so a stopped run can leave a game with an empty side that a re-run cannot see. Finish it with `move_game_sides.py --resume <log> --execute`, which addresses each logged game by id.

Undo: `split_provider_ids.py --revert <log> --execute` repoints aliases back; `move_game_sides.py --revert <log> --execute` moves games back. A created row stays and keeps being scraped while live, so deprecate it or leave games on it.

## Step 6: Verify and record

Query the database, not the script output:

- each target row's game count before and after Aug 1, and its aliases, each pointing at the intended row and approved
- for every game id in the move logs, the moved side equals `to` and the other side is not `to`; a team query cannot see an empty side, and database-wide empty-side counts include rows broken before this work
- no team plays itself on the rows touched

Report the new rows with their ids, the log paths, what was left in place and why, and the follow-ups for other skills: club and state on new rows (`normalizing-club-names`, `assigning-team-states`), age labels on rows that hold both cohorts' games (`correcting-team-age-groups`), and rows that fell below 12 games, which lose their published rank. The weekly ranking run regroups the boards.
