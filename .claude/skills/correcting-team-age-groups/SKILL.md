---
name: correcting-team-age-groups
description: "Audits and corrects PitchRank teams' age groups from evidence rather than one source: reviews a state or the whole database against the CLAUDE.md label key and fixes the approved groups in reversible batches. GotSport's reconcile population and the weekly age-group re-check belong to the reconcile-gotsport skill. Use when asked to review or audit the age groups in a state or in all teams against the label key, fix a team's age group, judge whether a provider's cohort should be trusted, or investigate why a team appears on the wrong age board."
---

# Correcting Team Age Groups

A wrong cohort puts a team on a public board it does not belong on, and a wrong correction does
the same in reverse. Decide from evidence; never copy one source.

The birth-year chart is in CLAUDE.md, which is always loaded — read the cohort there rather than
re-deriving it. Two facts from it carry most of the weight: a band is named by its **younger**
year whichever way it is spelled (the CLAUDE.md label key shows the common spellings), and the
boards rank `u10`–`u17` and `u19` only.

To review the age groups of a state or of every team, follow **Auditing against the label key**;
it applies through `scripts/fix_band_cohorts.py`. To produce a plan without applying it, follow
**Propose-only mode**. GotSport's reconcile population, both its per-team triage and its bulk lane,
and the Tuesday re-check belong to the `reconcile-gotsport` skill.

`scripts/check_age_skill_assumptions.py` turns this skill's claims about the code into assertions
(the label key against the band readers, the owner's decisions, the applier's guards, the name
hold) without reading the database. The weekly team-cleanup loop runs it before proposing age changes
(`SELF_CHECKS` in `scripts/team_cleanup/propose_week.py`) and parks the ages stage as
`skill_stale` when it fails.

## Propose-only mode

Take the audit path's Step 1 and Step 4 write-plan command, and stop there:

```bash
python .claude/skills/correcting-team-age-groups/scripts/review_age_labels.py review --state AZ,NC --exports-dir C:/PitchRank/data/exports
python .claude/skills/correcting-team-age-groups/scripts/review_age_labels.py write-plan <review.csv> --groups 1,2,3
```

Both are read-only and **write nothing to the database**. They leave a review CSV and a
plan CSV under the exports directory. The review reads `SUPABASE_SERVICE_ROLE_KEY` from the
environment directly and raises a bare `KeyError` without it.

Resume at **Step 4's second command**, the applier's dry run: its apply log is the only
place the held rows and their reasons appear, and Step 5 writes.

Nothing is written at this stage, so there is nothing to undo. A hand run of this cleanup keeps
no database ledger — an apply log CSV in a gitignored directory is the whole record, and it lives
where the run wrote it: the folder `--exports-dir` named, else the checkout that ran the batch.
Under the weekly team-cleanup loop the apply also writes a `team_cleanup_changes` row for every
change that log records and the database holds.

## What each source is worth

The band is the value; the provider is corroboration. In this audit a provider cohort never moves
a team on its own: it withholds a write it disagrees with, or picks between the two groups a birth
year in our own name allows. GotSport is the one provider whose age is written as a value, and only
through the `reconcile-gotsport` triage under the owner's rules that CLAUDE.md records.

| Signal | Weight |
|---|---|
| Two-year band in **our own** team name (`B2015/16`, `2013-2014`) | Decides, even when the team plays a year up. Season-proof and independent of the provider. |
| Division label on this season's games (`'14 (U12B)`) | Decides — the league's own statement for this season. Present mainly on league imports. |
| Opponents' own names carrying a band, this season | Decides. Independent of every column, including ones this tool wrote. |
| Opponents' own names carrying one birth year, this season | Separates two adjacent candidates: a year fits exactly two groups (2014 is U13 or U12), so it votes against a group it cannot be in. Season-proof but usually too thin to decide. |
| A U-label in **our own** name (`U13`, `13U`) | Only as current as the season that wrote it, and often that was last season. Moves a team when a season-proof signal above confirms it, or on the play-up path below. |
| GotSport's cohort saying **younger** than stored | Usually right where a band can check it (~99%). It cannot show a U-label is current: when GotSport's own name carries the same label, its cohort repeats it. On the play-up path it rules out the label being *ours alone*; the birth-year and division checks are what test the label's age. |
| GotSport's cohort for a band-named team | GotSport files a band by its **older** year, so it agreeing with a stored value one group too old proves nothing. |
| GotSport's cohort saying **older** than stored | Not this audit's to move. The `reconcile-gotsport` triage takes it for a team that has played since Aug 1 unless this season's opponents back ours (owner, 2026-10-12: "Older wins unless games say ours"), and never against a two-year band in our own name. |
| A single birth year in a name (`2014`) | Fits two groups. Moves a team only when the stored group is outside both. |
| A multi-year name (`B10-12`, `06-07-08`) | Decides nothing: the squad spans several groups. |
| Opponents' `age_group` **columns** | Worthless — the paths that mislabelled the team set its opponents too. |

GotSport team-history imports do not write `games.division_name`. The review counts every game's
division text as a league read, so a tournament flight, including one a team entered playing up,
votes as if it were the league's own statement; SincSports and PlayMetrics tournament imports
already store flights there. Before storing a provider's division text on games, check whether it
names a league division or a tournament flight.

Measured 2026-09-19. In North Carolina ~1,260 names such as `15 (11U) CSA Uptown King` were
last season's labels: that team plays this season in Classic League `'14 (U12B)`, and 20 of 20
division reads backed the stored group. `08 (17U) CISC NM Tan` is stored U19, correctly — 2008 is
U19 — while GotSport's cohort repeats its old "17U". In Arizona, U-label moves resting on GotSport
were 7 right and 3 wrong where opponents could check them.

For the opposite direction — a name disagreeing with the stored column — read
`scripts/audit_name_age_disagreements.py` first; it is the prior art.

## Owner decisions

Quote these; do not extend them.

- 2026-09-18, on teams that play up: "it doesn't matter that they play up we need to get their
  actual age group correct."
- 2026-09-19, the national review's answers, as recorded: Group 1 "Move all 4,395"; Group 2 "Move
  all 801"; Groups 3–4 "Only the 866 U-labels"; the 70 held teams "Leave them".
- 2026-09-19, on a U-label team whose opponents are a group older: "Yea just because it's a u12
  team and playing up that doesn't matter it's still a u12 team".
- Every team the owner left as stored — the ones reviewed one by one and the 70 — is listed in
  [scripts/owner_decisions.json](scripts/owner_decisions.json), which the review skips.

When the owner declines a team or a held group, add it to that file with the date and the answer
before the next review. The birth-year group (group 4) is the exception: asked whether future
audits should keep raising it, the owner chose "Ask again at every audit", so it stays out of the
file and goes back in front of the owner each time.

## Hold rather than write

Each rule below is enforced automatically, by a flag, or not at all. Know which.

- **Our own name states a different age** — *automatic under a flag*. `--skip-name-contradictions`
  holds a row at apply when our name states any birth year the new group cannot hold, including a
  span that overlaps the group (owner, 2026-10-11: "Hold every span"), or a U-age two or more
  groups away. It reads every year form: four-digit years, two-digit years after a straight or
  curly apostrophe ('11, ’11), apostrophe bands ('11/'12, ‘11/‘12), and both years of every consecutive pair in a run
  (2012/13/14); a season label (2025-26) is not a birth year. U18 files into u19 on both counts:
  u19 holds three birth years (2009 among them in 2026-27), and a `U17` name is one group from
  `u19`. A U-age one group away passes, since names keep last season's label after Aug 1 and
  squads play a year up. Without the flag the applier reads no name, and plans from the review or
  the triage reach it unchecked, so pass it on every apply. In a reconcile plan these rows usually
  mean the GotSport link points at another squad.
- **An identical team already sits in the target cohort** — *automatic*. A reconcile plan holds
  it as `would_update_collision` on name, gender and cohort alone, so the other row can belong to
  another club; the audit review holds it as `held_duplicate_landing` only when club and state
  match too. Either way it is usually a duplicate pair split by the mislabel, but
  `merging-duplicate-teams` needs byte-identical `club_name`, a matching `state_code` bucket
  and the same stored age group — this column included — so a reconcile pair may not be
  proposable there.
- **Opponents sit two or more groups from the name** — *automatic in the audit*:
  `held_opponents_far_from_name`. Mostly 09/10 teams in U19 leagues, two-year play-ups, and
  numbers that are not birth years (`Columbus United 09/10 Boys` plays U11). Owner's call. This
  distance counts by group number, so a `U17` name stored `u19` lands here rather than on the
  play-up path, U19 leagues being a group of their own.

A correction landing on `u9` or younger is still a correction — the team leaves the boards
because those cohorts are not ranked, and the rollover migration walks it back up to `u10` in
time.

## Auditing against the label key

```
Task Progress:
- [ ] Step 1: Run the review (read-only)
- [ ] Step 2: Read real rows before asking
- [ ] Step 3: Ask the owner per group
- [ ] Step 4: Write the plan, dry-run it, read the holds
- [ ] Step 5: Pilot 50, verify, apply the rest, verify
- [ ] Step 6: Re-run the review and record
```

### Step 1: Run the review

```bash
python .claude/skills/correcting-team-age-groups/scripts/review_age_labels.py review --state AZ,NC --exports-dir C:/PitchRank/data/exports
```

`--state` takes comma-separated codes and defaults to every US state.

It needs origin/main's band reader, so run it from a checkout synced to origin/main — a worktree
works, with `--exports-dir` pointed at the main checkout, where the reconcile and apply logs live.
It reads only; the whole database takes about two minutes.

It skips teams with no or a non-US state, Modular11, `team_ranking_exclusions`, and the owner's list,
then writes one row per team whose own name disagrees with its stored group: `group` (1–4, blank
when not proposed), `cat` (why), `stored`, `proposed`, the evidence columns (`gotsport_age`,
`div_says`, `band_opps_say`, `year_witness`), `ranked`, `collision`, and `prior_fix` (an earlier
logged fix that still stands, which the review never overrides). It prints one table with a row
per group.

| Group | Rule |
|---|---|
| 1 | Band in our own name, stored one group older — GotSport's older-year filing |
| 2 | Band in our own name, stored younger, two or more groups off, or aged out |
| 3 | U-label in our own name confirmed by a season-proof signal |
| 4 | Single birth year that rules the stored group out; value from a season-proof signal, else GotSport's cohort when it is one of the year's two |
| 5 | U-label in our own name, team playing one group up (`ulabel_plays_up`): opponents exactly one group older, GotSport registering the label's own group, no division read for the stored group, and no birth year in the name that the label's group cannot hold |

The chart in the script is a literal table for one season, and the script refuses to run once
the season has rolled; replace `CHART` and `CHART_SEASON` from CLAUDE.md's table.

### Step 2: Read real rows before asking

Sample every group and every hold category against names, opponents and divisions. Look hard at
any state whose mix stands out — one pattern dominating, or a group far larger than its
neighbours'. North Carolina's out-of-date U-labels and Washington's multi-year squads would both
have misled a blind run.

### Step 3: Ask the owner per group

One `AskUserQuestion` question per group, each naming real teams as examples with stored and
proposed groups, the count, how many are ranked, and how many land on U9 or younger. Include the
held-far rows as their own question. Keep group 5 its own question: its opponents point away from
the move, so an answer covering it has to be given knowing that.

### Step 4: Write the plan, dry-run it, read the holds

```bash
python .claude/skills/correcting-team-age-groups/scripts/review_age_labels.py write-plan <review.csv> --groups 1,2,3
python scripts/fix_band_cohorts.py --apply <plan> --skip-name-contradictions
```

`write-plan` writes its plan beside the review CSV. Run `fix_band_cohorts.py` from the checkout
that holds `data/exports`, or pass it `--exports-dir` pointing there: otherwise a worktree run
leaves its apply log, the only way back, where removing the worktree destroys it. Leave off
`--strong-only`: it keeps only band rows and would drop the approved U-label and birth-year
groups. The dry run prints only counts; the held rows and their `hold_reason` are in the apply log
it names (`fix_band_cohorts_apply_<time>.csv`). Read every `held_name_contradicts` row there. Apply
as a separate plan, without the flag, the ones that are false alarms: a band whose name also
carries a U-label two or three seasons old (`Queen City FC U14/15 (2010/2011)`). Keep held a name
whose U-label its own birth year contradicts (`U14 Travel 2011`).

### Step 5: Pilot 50, verify, apply the rest, verify

Run the plan with `--limit 50 --execute`, confirm in the database that the 50 hold the new group
with name, gender and state unchanged, then re-run without `--limit` and verify the whole batch
the same way. Each write carries the planned old value as a predicate, so a team that moved since
the plan is skipped rather than overwritten. Undo with `--revert <apply log> --execute`.

Under the weekly team-cleanup loop the apply (`scripts/team_cleanup/apply_stage.py`) writes the
rows of the lane (the owner's choices, or the changes the automatic lane settled) into two cut files, a pilot of the first 50 by team id and a rest, and runs
the fixer with `--apply <cut> --execute --skip-name-contradictions` over each in turn, reading
each batch back from the database and stopping before the rest when a write it expected is
missing. The `--limit 50` pilot above is for a hand run.

### Step 6: Re-run the review and record

Re-run Step 1. Approved groups should come back near empty, leaving only what was deliberately
held. Record the owner's answers, plan and apply logs, undo commands, and every hold with its
reason in `data/exports/<scope>_age_key_review_<date>.md`. The boards regroup at the next ranking
run.

## GotSport's reconcile logs and the weekly re-check

The bulk lane that corrects cohorts GotSport says are younger, straight from the reconcile logs
through `scripts/fix_band_cohorts.py`, its `held_fixtures_disagree` rows, and the Tuesday re-check
(`scripts/weekly_age_recheck.py`) are documented in the `reconcile-gotsport` skill, beside its
per-team triage. Both lanes write through the same applier as this audit, so the apply-time holds
above guard them too. Neither lane fixes a band-named team that GotSport files one group old;
this audit is how those get fixed.

## Sweeping many teams at once

Used 2026-10-26 on every state: about 5,500 teams moved, 1,185 left for the owner. The two scripts
are the sweep as run, with their paths hardcoded to that session's files: read them and adjust
before reuse. Both read a review CSV, so run Step 1 first.

- **Evidence.** Only games from Aug 1 of the season count. Teams with no games since then are set
  aside, not listed.
- **Tier 1, move.** Opponent witnesses agree (`scripts/sweep_stage1.py`): at least 4 supporting
  games across 3 opponents, none backing the stored group, at least one witness a band or birth year.
- **Tier 2, move.** The team's own name and GotSport's cohort agree, no opponents back the stored
  group, and the name carries no last-season marker (`Spring 2026`, `25/26`). A U-label alone can be
  last season's, so it never moves a team on its own.
- **Everything else goes to the owner's list**, sorted by reason: GotSport says a third age, no
  GotSport id, GotSport agrees but opponents back stored, move would duplicate a team.
- **GotSport lookups** (`scripts/sweep_gotsport_lookup.py`): `team_details` is free but gets a
  403 block. Space requests 3 seconds apart, abort after 10 failures in a row, and resume from the
  output CSV. A block cleared on its own after a pause.
- **Applying.** Pilot 50, read back from the database, then the rest, as in Step 5. Each batch keeps
  its own apply log for `--revert`.

## Reporting a batch

Give the count with its population and what remains — "3,700 of 22,800, the rest waiting for
games" rather than "3,700 fixed". A bare number invites a challenge it cannot answer.
Reconcile a distinct-team count against the batch sums: another session writes these same
tables with these same tools.
