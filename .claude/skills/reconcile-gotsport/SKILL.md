---
name: reconcile-gotsport
description: "Reconciles a state and age-group slice of PitchRank teams against GotSport: runs the read-only GotSport reconcile, triages each team whose GotSport age or gender disagrees with ours into gender fix, reused GotSport ID (a record handed to another squad at the Aug 1 rollover), relabel or hold, and on the owner's approval corrects genders, splits a reused record's games by date, renames teams and corrects age groups, every write guarded, logged and reversible. Use when asked to run /reconcile-gotsport, reconcile a state's teams with GotSport, find teams whose GotSport ID now belongs to another squad, split a team whose old and new games belong to two squads, find an old squad's new GotSport id, or fix teams GotSport files under the other gender."
---

# Reconcile GotSport

At each Aug 1 rollover our labels move every team up one group, while GotSport shows what each
record is now. A disagreement is one of four things, and only the evidence tells them apart:

| Class | What happened | Fix |
|---|---|---|
| **gender_fix** | GotSport's gender differs from ours, our own name or the names of the teams it played agree with GotSport, and neither backs ours. Whole import batches arrive with the wrong gender, so the column is never a witness | Set the gender first; the next triage judges the age on the right board |
| **reused_id** | The club handed the GotSport record to another squad, younger (`16B Wagner` is now `U10B Etgar`) or older (`CCV Stars 2016 North Orange` is now `Pre-ECNL G2014/15`). GotSport's name names another squad, last season's opponents sit at our age, this season's at GotSport's | Move the games before the season start to the old squad's new record, then rename and relabel the reused one |
| **relabel** | Same squad, and it did not age up (the Aug–Jul bands keep part of a birth year in one group two seasons running). GotSport's name keeps the squad word (`15B OMolina` is now `U11B OMolina`). When this season's opponents are too few or split evenly, the names decide: a band in GotSport's name, or a U-age in ours on a team new this season (`Southeast U10 Boys Black`, GotSport `Southeast 16/17 Boys Black`) | Relabel; rename if GotSport's name states the age and ours does not |
| **hold** | No games since Aug 1 (the team is most likely dormant and our value stands), a two-year band in our own name backs our age or neither age, too few games this season, opponents back our age, no squad word to compare, a gender mismatch no witness settles, or a same-named team already in GotSport's cohort | Leave it, and record the reason |

GotSport's age is judged the same way whether it is younger or older than ours, and a squad word
both names share separates relabel from reused_id: a squad that stayed in its group shows the same
one-group drop at Aug 1 as a reused record.

```
Task Progress:
- [ ] Step 1: Run the reconcile (read-only)
- [ ] Step 2: Triage the flagged teams
- [ ] Step 3: Read real rows
- [ ] Step 4: Find each reused record's old squad
- [ ] Step 5: Ask the owner
- [ ] Step 6: Apply: genders, split, rename, relabel
- [ ] Step 7: Verify and record
```

Run every command from the main checkout: logs land in `data/exports/`, which is gitignored, and
the revert path for every write is in those logs. Credentials come from root `.env`.

## Step 1: Run the reconcile (read-only)

```bash
python scripts/reconcile_teams_with_gotsport.py --age-group u10,u11 --state AZ --limit 0
```

Leave off `--execute`: this step only reads. The script calls GotSport once per team at 3 seconds
each, so a slice of a few hundred teams takes tens of minutes. Run it in the background and wait
for it to exit. Its stdout is block-buffered, so an empty output file means it is still running,
not that it failed. If it stops on consecutive failed lookups, GotSport's WAF is blocking: wait it
out and re-run with a larger `--delay`. `--state` matches the stored state, so teams with no state
are outside a state run.

The log it names (`reconcile_teams_with_gotsport_<time>.csv`) is Step 2's input. A run resumed
after a WAF stop leaves several logs; pass them all to Step 2, oldest first.

## Step 2: Triage the flagged teams

```bash
python .claude/skills/reconcile-gotsport/scripts/triage_reconcile.py --log data/exports/<reconcile log>.csv
```

Read-only. It examines every team whose live age or gender differs from GotSport's, skipping an age
the owner kept as stored, and writes to the exports folder:

- the triage CSV (`reconcile_triage_<time>.csv`), one row per team with its class and reason and the
  evidence behind them. `stated_birth_years` shows when a year in our name forced `same_squad` to
  False. `adjacent_gotsport` lists, for reused rows, the GotSport records within 3 ids of this one;
  `?` marks a failed lookup, not an empty record.
- a relabel plan and a reused-ID plan, in the format `scripts/fix_band_cohorts.py` applies. Relabel
  rows are `would_update`. Reused rows are `pending_split`, which the applier ignores until Step 6
  flips them. `fixture_verdict` carries that applier's meaning: `backs_move` when this season's games
  against band-named opponents at the new age outnumber those at the old age three to one.
- a gender plan of the `gender_fix` rows, in the format the bundled `apply_team_fields.py` applies.

When the triage finds reused rows, re-run it with `--probe-gotsport` to fill `adjacent_gotsport`.
It adds 6 GotSport calls per reused row.

## Step 3: Read real rows

The triage reads ages from opponents' names where they carry a two-year band and from opponents'
stored columns otherwise. The columns were set by the same imports that mislabelled the team, so
a row whose `fixture_verdict` is `thin` rests on circular evidence. For every reused and relabel
row, read the schedule's opponent names on both sides of Aug 1 before proposing it.

Check these by hand, because the triage cannot see them:

- **A bare birth year fits two groups.** `2015` is U12 or U11. It does not settle a move either way.
- **Teams that play up.** The owner, 2026-09-18: "it doesn't matter that they play up we need to
  get their actual age group correct." Older opponents this season do not make a relabel, and a
  two-year band in our own name decides the age.
- **MLS NEXT, AD, HD and EA teams** are out of scope. Hold them.
- **A squad word can match by accident**: a colour shared by two of the club's squads, a coach's
  name, or a club program word such as RSL Arizona South's girls "Royals". A birth year in our name
  catches some of these; where the club fields several squads in the cohort, compare against all of
  them. At a club seen rotating coaches or reshuffling records (RSL Arizona South, CCV Stars), a
  shared word does not make a relabel: treat the row as reused unless the owner says otherwise, and
  move its row from the relabel plan to the reused-ID plan as `pending_split`, so Step 6 does not
  relabel it before its games are split.
- **A dormant hold can hide a squad that re-registered.** When a team held as "no games since
  Aug 1" has a same-club, same-cohort row holding only this season's games, the squad likely moved
  to a new GotSport record (Next Level's "Southeast 2016 Black" and "SE U11 Boys Black"). Propose
  the pair as a merge through the `merging-duplicate-teams` skill.
- **A hold whose reason is "no squad word to compare"** is often a club with one team per age, and
  the triage cannot catch a reused record there: Bala FC's `Bala FC - 2016` carried no squad word.
  Decide it from the club's other teams in both cohorts and from GotSport's current name, then
  move it to relabel or reused by hand. Add a reused one's row to the reused-ID plan.
- **The owner knows clubs the data does not.** "Utah Royals are girls teams", although that
  team's opponents are boys.

## Step 4: Find each reused record's old squad

The old games move to the record GotSport now uses for the old squad. Read GotSport's current name
and age for any record the reconcile looked up from its logs (`gotsport_team_name`, `gotsport_age_group`) before
looking it up live: a live lookup can hang for minutes while GotSport is throttling a running
reconcile. Look in this order:

1. `adjacent_gotsport` in the triage. Clubs register squads in batches, so the old squad is often
   a neighbouring id: Bala FC's reused record was 614082 and its old squad 614084.
2. PitchRank teams of the same club in our stored cohort whose names carry the old squad word.
3. `unknown_<id>` placeholders with this season's games against the old cohort's opponents.

Confirm the record with GotSport's current name and age. A club that shifts every record down a
year makes a chain: the old squad's new record still holds its own previous squad's season, so move
that season up first and work down the chain, oldest squad first. Where the old squad's record has
no PitchRank row yet, hold the reused team: the row is created when that record's games are
imported, and the split waits for it. Where nothing turns it up, ask the owner for the id.

When nobody can say where the old squad went (the owner on RSL Arizona South, 2026-10-09: "I dont
think theres a rhyme or a reason"), offer the archive route instead: the record's games before
the season start go to a new archive team named for the old squad and season, with no provider
link, in the record's stored age group. Both squads' records stay honest, the archive leaves the
boards as its games pass the ranking window, and a chain needs no order because each record is
handled alone. When the old squad's record turns up later, merge the archive into it with the
`merging-duplicate-teams` skill.

## Step 5: Ask the owner

Output the triage counts, then use `AskUserQuestion`: one question each for the gender fixes, the
reused rows and the relabel rows. Split the gender fixes in two: rows whose own name states the
gender, and rows resting on opponents alone, listing each one's opponents so the owner can check
them by hand. Name real teams with both names, both ages and, for reused rows, the old squad's
record. Phrase it as outcomes ("move 21 games to U11B Moyer, set this team to U10"), not mechanisms.

Add each declined relabel to `kept_as_stored.teams` in
`.claude/skills/correcting-team-age-groups/scripts/owner_decisions.json` as
`{"team_id": ..., "name": ...}`, the shape its entries already have. The triage and the age review
both skip those teams. Record the date and the owner's answer in Step 7's record.

## Step 6: Apply: genders, split, rename, relabel

Dry-run each command first and read its output. Then run it with `--execute`. Every one of them
logs before its first write and prints its undo command.

**a. Genders.** Apply the gender plan, filtered to the approved rows:

```bash
python .claude/skills/reconcile-gotsport/scripts/apply_team_fields.py --plan data/exports/<gender plan>.csv
```

Then re-run Step 2: a team that changes gender changes board, and its age is judged there.

**b. Split each reused record's games** (reused rows only). For records going to archive teams,
one command does steps b to d:

```bash
python .claude/skills/reconcile-gotsport/scripts/archive_split.py plan --triage data/exports/<triage>.csv
python .claude/skills/reconcile-gotsport/scripts/archive_split.py apply --plan data/exports/<plan>.csv --names "<pilot>" "<pilot>"
```

`plan` writes one row per reused record; edit it to the approved records, and set
`archive_age_group` to the old squad's cohort on any record already relabelled. `apply` creates
each archive team, moves the games, renames and relabels the record, and writes a run log naming
each step's log. Pilot a few with `--names`, verify them, then run the rest. Each step is
idempotent, so re-running finishes a stopped run.

For a record whose old squad's new record is known, move the games directly:

```bash
python scripts/reassign_games_between_teams.py --from <reused team id> --to <old squad team id> --before <season start, YYYY-08-01>
```

Expect every game to be planned as `moved`. A `skipped_would_self_play` means the two squads met,
and the old-squad row already holds that game. Leave it in place. The move covers games filed
under the reused team's own id; games on a team merged into it stay there, so check the merge
history when its count falls short of the triage's. If a run stops part-way, finish it with
`--resume <log> --execute`, never by re-running the block: a game whose side was cleared can only
be found again through the log.

**c. Rename**, before the relabel: a reused record still carries the old squad's name, and its
birth year would make the relabel's name check hold it. Use GotSport's current name, where it
states a U-age or a band and ours states a bare year or nothing. The owner prefers a band or U-age
name to a bare birth year. Rename each reused record and each placeholder that received old games.
Write a CSV of `team_id_master,team_name,field,old_value,new_value` with `field` set to
`team_name`, and run:

```bash
python .claude/skills/reconcile-gotsport/scripts/apply_team_fields.py --plan <names.csv>
```

A placeholder that received games also lacks club and state. Leave those to the
`normalizing-club-names` and `assigning-team-states` skills, and list them in Step 7.

**d. Relabel:**

```bash
python scripts/fix_band_cohorts.py --apply data/exports/<age plan>.csv --skip-name-contradictions
```

Run it once per plan file. In the reused-ID plan, change `action` from `pending_split` to
`would_update` only on rows whose split and rename you verified in the database, and set
`team_name` to the new name; the applier skips the rest. Leave out rows the owner declined with
`--exclude <id,id>`. `--skip-name-contradictions` holds any team whose own name states another age.
Read those in the apply log and do not force them. For more than 50 rows, pilot with
`--limit 50 --execute`, verify, then run the rest.

## Step 7: Verify and record

Verify against the database, not against the scripts' summaries:

- each gender fix holds its new gender
- each split leaves no game with an empty side and no team playing itself, and the old squad holds
  the games before the season start
- each renamed team carries its new name
- each relabelled team holds its new age, with gender and state unchanged

Write `data/exports/<state>_reconcile_gotsport_<date>.md` with: the slice, the class counts, each
applied change with its log and undo command, each hold with its reason, and the follow-ups
(placeholders needing club or state, reused teams waiting on an old-squad row). The boards
regroup at Monday's ranking run.
