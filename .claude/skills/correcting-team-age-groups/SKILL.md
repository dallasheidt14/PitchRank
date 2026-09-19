---
name: correcting-team-age-groups
description: "Audits and corrects PitchRank teams' age groups from evidence rather than one source: reviews a state or the whole database against the CLAUDE.md label key, fixes the approved groups in reversible batches, and drives the weekly GotSport re-check. Use when asked to review or audit the age groups in a state or in all teams, fix a team's age group, correct cohorts in bulk, reconcile stored cohorts against GotSport, review this week's age-group re-check, judge whether a provider's cohort should be trusted, or investigate why a team appears on the wrong age board."
---

# Correcting Team Age Groups

A wrong cohort puts a team on a public board it does not belong on, and a wrong correction does
the same in reverse. Decide from evidence; never copy one source.

The birth-year chart is in CLAUDE.md, which is always loaded — read the cohort there rather than
re-deriving it. Two facts from it carry most of the weight: a band is named by its **younger**
year whichever way it is spelled (the CLAUDE.md label key shows the common spellings), and the
boards rank `u10`–`u17` and `u19` only.

To review the age groups of a state or of every team, follow **Auditing against the label key**.
For GotSport's reconcile population and the Tuesday re-check, follow **Correcting from GotSport's
reconcile logs**. Both apply through `data/exports/fix_band_cohorts.py`.

## What each source is worth

The band is the value; the provider is corroboration. CLAUDE.md puts it as a veto that is not a
value, and that holds: a provider cohort withholds a write it disagrees with, and something
season-proof supplies the cohort actually written.

| Signal | Weight |
|---|---|
| Two-year band in **our own** team name (`B2015/16`, `2013-2014`) | Decides, even when the team plays a year up. Season-proof and independent of the provider. |
| Division label on this season's games (`'14 (U12B)`) | Decides — the league's own statement for this season. Present mainly on league imports. |
| Opponents' own names carrying a band, this season | Decides. Independent of every column, including ones this tool wrote. |
| Opponents' own names carrying one birth year, this season | Separates two adjacent candidates: a year fits exactly two groups (2014 is U13 or U12), so it votes against a group it cannot be in. Season-proof but usually too thin to decide. |
| A U-label in **our own** name (`U13`, `13U`) | Only as current as the season that wrote it, and often that was last season. Moves a team only when a season-proof signal above confirms it. |
| GotSport's cohort saying **younger** than stored | Usually right where a band can check it (~99%). Not independent of a U-label: when GotSport's own name carries the same label, its cohort repeats it. |
| GotSport's cohort for a band-named team | GotSport files a band by its **older** year, so it agreeing with a stored value one group too old proves nothing. |
| GotSport's cohort saying **older** than stored | Usually wrong — about two in three. Leave these alone. |
| A single birth year in a name (`2014`) | Fits two groups. Moves a team only when the stored group is outside both. |
| A multi-year name (`B10-12`, `06-07-08`) | Decides nothing: the squad spans several groups. |
| Opponents' `age_group` **columns** | Worthless — the paths that mislabelled the team set its opponents too. |

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
- Every team the owner left as stored — the ones reviewed one by one and the 70 — is listed in
  [scripts/owner_decisions.json](scripts/owner_decisions.json), which the review skips.

When the owner declines a team or a held group, add it to that file with the date and the answer
before the next review. Put a declined group back in front of the owner only with the new evidence
named.

## Hold rather than write

Each rule below is enforced automatically, by a flag, or not at all. Know which.

- **Our own name states a different age** — *partly automatic*. The plan's `D_name_contradicts`
  tier reads four-digit years only; apostrophe-prefixed bands, written '11/'12, reach it only under
  `--skip-name-contradictions`, so pass that flag on every apply. In a reconcile plan these rows
  usually mean the GotSport link points at another squad. The check does not know U18 files into
  U19, so it also holds every `08/09` band moving to `u19` — see audit Step 4.
- **An identical team already sits in the target cohort** — *automatic*. A reconcile plan holds
  it as `would_update_collision` on name, gender and cohort alone, so the other row can belong to
  another club; the audit review holds it as `held_duplicate_landing` only when club and state
  match too. Either way it is usually a duplicate pair split by the mislabel, but
  `merging-duplicate-teams` needs byte-identical `club_name` and a matching `state_code` bucket,
  so a reconcile pair may not be proposable there.
- **This season's opponents back the current label** — *automatic*: held as
  `held_fixtures_disagree`, but held for a look, not kept. It is usually a team playing a year
  up. Sample a few against their schedules, then file by its band each row whose band is in our
  own name (`evidence_tier` `A_own_name_band`), following the play-up decision above; rows whose
  band is only in GotSport's name stay held, because a provider name is a veto and not a value.
  Copy the own-name rows into a plan with `action` set to `would_update` and apply it the usual
  way.
- **Opponents sit two or more groups from the name** — *automatic in the audit*:
  `held_opponents_far_from_name`. Mostly 09/10 teams in U19 leagues, two-year play-ups, and
  numbers that are not birth years (`Columbus United 09/10 Boys` plays U11). Owner's call.

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

```
python .claude/skills/correcting-team-age-groups/scripts/review_age_labels.py review [--state AZ,NC] --exports-dir C:/PitchRank/data/exports
```

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
held-far rows as their own question.

### Step 4: Write the plan, dry-run it, read the holds

```
python .claude/skills/correcting-team-age-groups/scripts/review_age_labels.py write-plan <review.csv> --groups 1,2,3
python data/exports/fix_band_cohorts.py --apply <plan> --skip-name-contradictions
```

Run the second command from `C:\PitchRank`, where `data/exports/fix_band_cohorts.py` lives. Leave off
`--strong-only`: it keeps only band rows and would drop the approved U-label and birth-year
groups. The dry run prints only counts; the held rows and their `hold_reason` are in the apply log
it names (`fix_band_cohorts_apply_<time>.csv`). Read every `held_name_contradicts` row there. Apply
as a separate plan, without the flag, the ones that are false alarms: an `08/09` band going to
`u19`, and a band whose name also carries a U-label two or three seasons old
(`Queen City FC U14/15 (2010/2011)`). Keep held a name whose U-label its own birth year
contradicts (`U14 Travel 2011`).

### Step 5: Pilot 50, verify, apply the rest, verify

Run the plan with `--limit 50 --execute`, confirm in the database that the 50 hold the new group
with name, gender and state unchanged, then re-run without `--limit` and verify the whole batch
the same way. Each write carries the planned old value as a predicate, so a team that moved since
the plan is skipped rather than overwritten. Undo with `--revert <apply log> --execute`.

### Step 6: Re-run the review and record

Re-run Step 1. Approved groups should come back near empty, leaving only what was deliberately
held. Record the owner's answers, plan and apply logs, undo commands, and every hold with its
reason in `data/exports/<scope>_age_key_review_<date>.md`. The boards regroup at the next ranking
run.

## Correcting from GotSport's reconcile logs

Correct a cohort when GotSport says younger **and** something season-proof agrees. Across 12,083
corrections, 99.3% of games against band-named opponents matched the new cohort.

This path only sees teams GotSport says are **younger** than stored. A band-named team GotSport
files one group old never reaches it; the audit above is how those get fixed.

### Step 1: Preflight

Run from `C:\PitchRank`. `data/exports/` is gitignored, so `data/exports/fix_band_cohorts.py`
and `data/exports/weekly_age_recheck.py` exist only in the main checkout and are absent from
every worktree and every fresh clone. They have no tests (IMP-242).

Credentials come from root `.env` (`.env.local` overrides it); a missing key surfaces as
`Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY` before any read.

Candidates come from `data/exports/reconcile_teams_with_gotsport_*.csv` — the most recent
execute-mode row per team. A team never reconciled cannot appear, and on a machine without
those logs the tool reports zero candidates rather than failing. Widen the population by
running `scripts/reconcile_teams_with_gotsport.py` first.

### Step 2: Plan, and read real rows

`python data/exports/fix_band_cohorts.py` with no arguments is a dry run: it re-verifies every
candidate against the live table, attaches this season's opponent evidence, checks the target
cohort for a same-named team, and writes a plan CSV. Nothing is written to the database.

Sample the plan by hand before applying. Read the surprising moves — three cohorts at once, a
club's whole roster — against the team's own name and its opponents.

### Step 3: Pilot 50 and verify

```
python data/exports/fix_band_cohorts.py --apply <plan> --strong-only --skip-name-contradictions --limit 50 --execute
```

Then confirm in the database that the 50 hold the new cohort and nothing else on those rows
changed. Verify from the database, not from the run's own summary.

### Step 4: Apply the rest

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

## Reviewing the weekly re-check

A Windows scheduled task, "PitchRank Weekly Age-Group Recheck", runs
`data/exports/weekly_age_recheck.py` every Tuesday. It re-derives the pending population from
the reconcile logs, applies the reconcile rules, and writes `weekly_age_recheck_<date>.md`, a plan
CSV, and a row in `weekly_age_recheck_history.csv`. Like the reconcile path it cannot see a
band-named team GotSport files one group old, so newly imported teams of that kind accumulate
until an audit catches them.

Most pending teams are waiting for games, not failing a test: only about one game in six is
against a band-named opponent, so evidence accrues over the season. Read `qualifying` rather
than `pending` — pending grows whenever fresh reconcile rows land, and a growing total is
coverage widening, not a fault.

Treat its plan as any other plan: sample, pilot, verify, and apply only with the user's
approval. `weekly_age_recheck_last_run.log` says `ok` or carries the traceback; a week with no
report and no log means the machine was off.

## Reporting a batch

Give the count with its population and what remains — "3,700 of 22,800, the rest waiting for
games" rather than "3,700 fixed". A bare number invites a challenge it cannot answer.
Reconcile a distinct-team count against the batch sums: another session writes these same
tables with these same tools.
