---
name: reconcile-gotsport
description: "Reconciles a state and age-group slice of PitchRank teams against GotSport: runs the read-only GotSport reconcile, triages each team whose GotSport age or gender disagrees with ours into gender fix, reused GotSport ID (a record handed to another squad at the Aug 1 rollover), relabel or hold, and on the owner's approval corrects genders, splits a reused record's games by date, renames teams and corrects age groups, every write guarded, logged and reversible. Also runs the bulk lane that corrects age groups GotSport says are younger straight from the reconcile logs, and reviews the Tuesday age-group re-check. Use when asked to run /reconcile-gotsport, reconcile a state's teams with GotSport, reconcile stored cohorts against GotSport, correct cohorts in bulk from the reconcile logs, review this week's age-group re-check, find teams whose GotSport ID now belongs to another squad, split a team whose old and new games belong to two squads, find an old squad's new GotSport id, or fix teams GotSport files under the other gender."
---

# Reconcile GotSport

At each Aug 1 rollover our labels move every team up one group, while GotSport shows what each
record is now. A disagreement is one of four things, and only the evidence tells them apart:

| Class | What happened | Fix |
|---|---|---|
| **gender_fix** | GotSport's gender differs from ours, our own name or the names of the teams it played agree with GotSport, and neither backs ours. Whole import batches arrive with the wrong gender, so the column is never a witness | Set the gender first; the next triage judges the age on the right board |
| **reused_id** | The club handed the GotSport record to another squad, younger (`16B Wagner` is now `U10B Etgar`) or older (`CCV Stars 2016 North Orange` is now `Pre-ECNL G2014/15`). GotSport's name names another squad, last season's opponents sit at our age, this season's at GotSport's | Move the games before the season start to the old squad's new record, then rename and relabel the reused one |
| **relabel** | Same squad, and it did not age up (the Aug–Jul bands keep part of a birth year in one group two seasons running). GotSport's name keeps the squad word (`15B OMolina` is now `U11B OMolina`) and this season's opponents sit at GotSport's age. Or one of the owner's rules below takes GotSport's age | Relabel; rename if GotSport's name states the age and ours does not |
| **hold** | No games since Aug 1 (the team is most likely dormant and our value stands), a two-year band in our own name backs our age or neither age, this season's opponents back our age (or sit at neither age and no rule below applies), opponents that cannot decide beside names that state our age alone, a refusal listed below, a gender mismatch no witness settles, or a same-named team already in GotSport's cohort | Leave it, and record the reason |

For a team that has played since Aug 1, the owner's rules take GotSport's age, younger or older,
when:

- GotSport says older and this season's opponents do not back ours (2026-10-11, refined
  2026-10-12: "Older wins unless games say ours");
- this season's opponents cannot decide, with fewer than three games with a readable opponent age
  or an even split between neighbouring groups, unless the names state our age and not GotSport's
  (2026-10-11: "Gotsport literally tells us what age group the team is"); or
- the names state GotSport's age and not ours, and this season's opponents do not back ours
  (2026-10-12, of `Players U10 Girls Academy`: "it literally says u10").

The names are a two-year band in GotSport's current name, and a U-age in ours on a team with no
games last season, whose name was written this season (`Southeast U10 Boys Black`, GotSport
`Southeast 16/17 Boys Black`). None of the rules applies, and the team is held or goes to
reused_id, when a two-year band in our own name says otherwise (2026-10-11: "Our band name wins"),
GotSport's name is another squad, a name carries no squad word to compare and the names do not
state GotSport's age (2026-10-12: "Hold them too"), our current and original names carry different
bands, or GotSport's age is outside u7-u19. A squad word both names share separates relabel from
reused_id: a squad that stayed in its group shows the same one-group drop at Aug 1 as a reused
record.

Two lanes correct ages from GotSport, kept side by side (decided 2026-10-11, the owner taking the
recommendation): this
per-team triage (Steps 1 to 7), and the bulk lane for cohorts GotSport says are younger, with its
Tuesday re-check (**The bulk lane** and **Reviewing the weekly re-check** below).

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
the revert path for every write is in those logs. Credentials come from root `.env`; a
`.env.local` beside it overrides the keys it sets, and `.env` still supplies the rest. The
exception is a hand run of `scripts/reassign_games_between_teams.py` (Step 6b, its `--resume`
and its `--revert`), which reads `.env.local` alone when that file exists.

**Prove this skill is still true.** Run the self-check before trusting the rest:

```bash
python scripts/check_reconcile_skill_assumptions.py --code-only
```

`scripts/check_reconcile_skill_assumptions.py` turns this skill's claims about the code into
assertions (what Step 1 reads and leaves alone, its pacing and its stop, how GotSport's answer
is decided, what the triage reads and writes, and the guards, logs and undo commands of the
Step 6 tools and the bulk lane) without reading the database or calling GotSport. **A failure
means this skill is now wrong, not that the codebase is broken** — fix the prose, then continue.
Its NOT VERIFIED lines are claims no code settles, such as how long a lookup takes; they never
fail the run. The weekly team-cleanup loop runs neither this check nor the reconcile, and records
the reconcile stage as `not run: reconcile is run by hand`.

## Propose-only mode

Take Steps 1 and 2 and stop there. The reconcile without `--execute` and the triage both
**write nothing to the database**. The reconcile leaves its log
(`reconcile_teams_with_gotsport_<time>.csv`) and the triage its CSV and three plans in the
exports folder. Both still call GotSport: the reconcile once per team that has a GotSport id,
the triage only with `--probe-gotsport`. Resume at Step 3 to read real rows, or hand the triage
on as it stands.

Nothing is written at this stage, so there is nothing to undo.

## Step 1: Run the reconcile (read-only)

```bash
python scripts/reconcile_teams_with_gotsport.py --age-group u10,u11 --state AZ --limit 0
```

Leave off `--execute`: this step only reads. For each team with a GotSport id the script
pauses `--delay` (3 seconds unless set), then sends one request with a 15-second timeout and no
retry. Over a long walk, budget about `delay + 0.35 s` per lookup, the rate the scraper-patterns
skill measured across every state. Time before the first lookup comes on top: one 15-team run on
2026-10-09 took 169 s from start to finish. The script's own `Estimated runtime` line counts only
the pauses. Run it in the background and wait for it to exit. Its stdout is block-buffered, so an
empty output file means it is still running, not that it failed. `--state` matches the stored
state, so teams with no state are outside a state run.

After ten failed lookups in a row (`--abort-after`; a 404 is an answer and clears the count) it
stops, writes its log for the teams it reached, and exits with code 75 rather than 0. That
usually means GotSport's WAF is blocking, but a local network outage looks the same: tell them
apart and respond as the scraper-patterns skill describes.

The log it names (`reconcile_teams_with_gotsport_<time>.csv`) is Step 2's input. A run resumed
after a WAF stop leaves several logs; pass them all to Step 2, oldest first.

With `--execute` the same script also takes GotSport's name for a team, but not where GotSport files
the team in another age group, or where our name's birth year fits our group and GotSport's name
would trade it for another age or no number (owner, 2026-10-12). The log shows each withheld rename
as `team_name` in `blocked_fields`. A GotSport name that marks a retired or archived registration
(`zz old`, `do not use`, `inactive`, `archive` and the like) is never taken: it is blanked before
logging.

## Step 2: Triage the flagged teams

```bash
python .claude/skills/reconcile-gotsport/scripts/triage_reconcile.py --log data/exports/<reconcile log>.csv
```

Read-only. It examines every team whose live age or gender differs from GotSport's. It leaves out
the age of every team the owner decided to leave, in any section of
`.claude/skills/correcting-team-age-groups/scripts/owner_decisions.json` and on any row such a
team was merged into since, and prints how many it left out; a gender difference on such a team is still triaged. A missing or malformed decisions file
stops the run. It writes to the exports folder:

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
  get their actual age group correct." Older opponents this season do not make a relabel where
  GotSport says younger. Where GotSport says older they do not back ours, so the owner's
  "Older wins unless games say ours" takes GotSport's age. A two-year band in our own name decides
  the age either way.
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
  The hold comes only where the names do not state GotSport's age; where they do, the triage
  relabels the row, so look at those relabels the same way. Decide a held one from the club's other
  teams in both cohorts and from GotSport's current name, then move it to relabel or reused by hand.
  Add a reused one's row to the reused-ID plan.
- **The owner knows clubs the data does not.** "Utah Royals are girls teams", although that
  team's opponents are boys.

## Step 4: Find each reused record's old squad

The old games move to the record GotSport now uses for the old squad. Read GotSport's current name
and age for any record the reconcile looked up from its logs (`gotsport_team_name`, `gotsport_age_group`) before
looking it up live: a live lookup can hang for minutes while GotSport is throttling a running
reconcile. A blank `gotsport_team_name` there can mean GotSport's name marked a retired or archived
registration, which the reconcile blanks before logging; look that record up live. Look in this
order:

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
`{"team_id": ..., "name": ...}`, the shape its entries already have. The triage then leaves out
their age, and the age review skips them. Record the date and the owner's answer in Step 7's record.

## Step 6: Apply: genders, split, rename, relabel

Dry-run each command first and read its output. Then run it with `--execute`. Each tool but
`archive_split.py` writes its log before its first write, and they differ in the undo they print:

- `apply_team_fields.py` and `scripts/fix_band_cohorts.py` print their undo
  (`--revert <log> --execute`) after a run with `--execute`.
- `scripts/reassign_games_between_teams.py` prints its undo only on the dry run. After a run with
  `--execute` it prints only the `Log:` path; undo with `--revert <that log> --execute`.
- `archive_split.py apply --execute` creates each record's archive team before it runs that
  record's tools. Only after the last record does it write its run log
  (`archive_split_run_<time>.csv`), which names each step's log, and print a template of the
  undo: each tool's `--revert <log>`, last step first, without `--execute`, so as printed each
  one only previews. A stopped run leaves neither, only the logs of the tools that ran. Nothing
  undoes the archive team: once its games are reverted it stays as a team with no games, and a
  re-run reuses it.

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

## The bulk lane

Correct a cohort when GotSport says younger **and** something season-proof agrees. Across 12,083
corrections, 99.3% of games against band-named opponents matched the new cohort.

This path only sees teams GotSport says are **younger** than stored. A band-named team GotSport
files one group old never reaches it; the audit in the `correcting-team-age-groups` skill is how
those get fixed.

### Bulk 1: Preflight

Run from the checkout that holds `data/exports`, or pass both scripts
(`scripts/reconcile_teams_with_gotsport.py` and `scripts/fix_band_cohorts.py`) `--exports-dir`
pointing there. Both are tracked under `scripts/`, so every checkout has them — but their
candidates and logs live under `data/exports/`, which is gitignored, so a worktree run without the flag finds no
candidates and leaves its logs where removing the worktree destroys them.

Both scripts read root `.env` with `.env.local` layered over it, as the top of this skill says.
A key missing from both stops either script before any read. `scripts/fix_band_cohorts.py` says
`Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY`, and the reconcile says
`Missing Supabase credentials. Need SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY/SUPABASE_KEY.`
With `--execute` the reconcile also refuses to run unless `SUPABASE_SERVICE_ROLE_KEY` or
`SUPABASE_SERVICE_KEY` is set.

Candidates come from `reconcile_teams_with_gotsport_*.csv` in that folder — the most recent
execute-mode row per team. Only rows from an `--execute` run count, so Step 1's read-only run adds
none. A team never reconciled cannot appear, and on a machine without those logs the tool reports
zero candidates rather than failing. Widen the population by running
`scripts/reconcile_teams_with_gotsport.py` with `--execute` first; that run also writes the names,
clubs and states it reports, so ask before it.

### Bulk 2: Plan, and read real rows

`python scripts/fix_band_cohorts.py` with no arguments is a dry run: it re-verifies every
candidate against the live table, attaches this season's opponent evidence, checks the target
cohort for a same-named team, and writes a plan CSV. Nothing is written to the database.

Sample the plan by hand before applying. Read the surprising moves — three cohorts at once, a
club's whole roster — against the team's own name and its opponents.

### Bulk 3: Pilot 50 and verify

```bash
python scripts/fix_band_cohorts.py --apply <plan> --strong-only --skip-name-contradictions --limit 50 --execute
```

Then confirm in the database that the 50 hold the new cohort and nothing else on those rows
changed. Verify from the database, not from the run's own summary.

### Bulk 4: Apply the rest

Re-run the same command without `--limit`; the piloted rows come back as `already_applied`, so
no slicing is needed. Verify the whole batch the same way. Each write carries the planned old
value as a predicate, so a team that moved since the plan is skipped and reported rather than
overwritten.

Undo with `--revert <apply log> --execute`, which touches only rows still holding what the run
wrote.

**Selecting a subset of a reviewed plan:** `--strong-only` is the set this path's rule
describes and the default worth applying. `--gotsport-only` selects its complement — rows whose
only evidence is GotSport's own name — so treat it as a separate judgment rather than a filter.
`--boarded-only` / `--unboarded-only` split by whether the new cohort is ranked, and
`--exclude` takes comma-separated team ids. The two pairs are mutually exclusive; passing both
halves exits. `--include-collisions` **widens** the set into the held duplicates — leave it off.
`--dry-run` wins over `--execute`.

Ask before writing a batch. The boards regroup at Monday's ranking run; nothing else needs
repairing afterwards.

### Rows held because this season's opponents back the current label

The plan holds these as `held_fixtures_disagree`, for a look rather than for keeps. It is usually
a team playing a year up. Sample a few against their schedules, then file by its band each row
whose band is in our own name (`evidence_tier` `A_own_name_band`), following the owner's
2026-09-18 play-up decision (Step 3); rows whose band is only in GotSport's name stay held. Copy
the own-name rows into a plan with `action` set to `would_update` and apply it the usual way.

## Reviewing the weekly re-check

A Windows scheduled task, "PitchRank Weekly Age-Group Recheck", runs
`scripts/weekly_age_recheck.py` every Tuesday. It re-derives the pending population from
the reconcile logs, applies the bulk lane's rules, and writes `weekly_age_recheck_<date>.md`, a
plan CSV, and a row in `weekly_age_recheck_history.csv`. Like the bulk lane it cannot see a
band-named team GotSport files one group old, so newly imported teams of that kind accumulate
until an audit catches them.

Most pending teams are waiting for games, not failing a test: only about one game in six is
against a band-named opponent, so evidence accrues over the season. Read `qualifying` rather
than `pending` — pending grows whenever fresh reconcile rows land, and a growing total is
coverage widening, not a fault.

Treat its plan as any other plan: sample, pilot, verify, and apply only with the user's
approval. `weekly_age_recheck_last_run.log` says `ok` or carries the traceback. The log is written by
the script itself, so a week with no report *and* no log means the script never started:
the machine was off, or the task names a path that checkout does not hold.
