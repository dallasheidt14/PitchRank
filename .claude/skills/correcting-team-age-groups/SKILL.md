---
name: correcting-team-age-groups
description: "Decides and corrects a PitchRank team's age group from evidence rather than one source, and drives the weekly re-check of teams that cannot be decided yet. Use when asked to fix a team's age group, correct cohorts in bulk, reconcile stored cohorts against GotSport, review this week's age-group re-check, judge whether a provider's cohort should be trusted, or investigate why a team appears on the wrong age board."
---

# Correcting Team Age Groups

A wrong cohort puts a team on a public board it does not belong on, and a wrong correction does
the same in reverse. Decide from evidence; never copy one source.

The birth-year chart is in CLAUDE.md, which is always loaded — read the cohort there rather than
re-deriving it. Two facts from it carry most of the weight: a band is named by its **younger**
year whichever way it is spelled (the CLAUDE.md label key shows the common spellings), and the
boards rank `u10`–`u17` and `u19` only.

```
Task Progress:
- [ ] Step 1: Preflight
- [ ] Step 2: Plan (dry run) and read real rows
- [ ] Step 3: Pilot 50 and verify in the database
- [ ] Step 4: Apply the rest and verify
- [ ] Step 5: Report with the population, and record what was held
```

## What each source is worth

The band is the value; the provider is corroboration. CLAUDE.md puts it as a veto that is not a
value, and that holds: a provider cohort withholds a write it disagrees with, and something
season-proof supplies the cohort actually written.

| Signal | Weight |
|---|---|
| Two-year band in **our own** team name (`B2015/16`, `2013-2014`) | Decides. Season-proof and independent of the provider. |
| Opponents' own names carrying a band, current season | Decides. Independent of every column, including ones this tool wrote. |
| Two-year band in **GotSport's** name | Strong, not independent — it agrees with GotSport's cohort by construction. |
| GotSport's cohort saying the team is **younger** than stored | Usually right: ~99% where a band can check it. |
| GotSport's cohort saying the team is **older** than stored | Usually wrong — about two in three. Leave these alone. |
| A single birth year in a name (`2014`) | Decides nothing: it sits in two cohorts. |
| A U-age in a name (`U13`) | Lags a season after Aug 1. One cohort away is stale; two or more contradicts. |
| Opponents' `age_group` **columns** | Worthless — the paths that mislabelled the team set its opponents too. |

Correct a cohort when GotSport says younger **and** something season-proof agrees. Across 12,083
corrections, 99.3% of games against band-named opponents matched the new cohort.

For the opposite direction — a name disagreeing with the stored column — read
`scripts/audit_name_age_disagreements.py` first; it is the prior art.

## Hold rather than write

Each rule below is enforced automatically, by a flag, or not at all. Know which.

- **Our own name states a different age** — *partly automatic*. The plan's `D_name_contradicts`
  tier reads four-digit years only; apostrophe-prefixed bands, written '11/'12, reach it only under
  `--skip-name-contradictions`, so pass that flag on every apply. `_resolve_band` reads plain
  two-digit bands (`13/14`) but not the apostrophe form, and that gap put one wrong cohort into
  production. These rows usually mean the GotSport link points at another squad.
- **An identical team already sits in the target cohort** — *automatic*: held as
  `would_update_collision` and excluded unless `--include-collisions` is passed. These are
  duplicate pairs split by the mislabel. `merging-duplicate-teams` needs byte-identical
  `club_name` and a matching `state_code` bucket as well, so a pair flagged here may not be
  proposable there.
- **This season's opponents back the current label** — *automatic*: held as
  `held_fixtures_disagree`, but held for a look, not kept. It is usually a team playing a year
  up, and the owner decided on 2026-09-18: "it doesn't matter that they play up we need to get
  their actual age group correct." Sample a few against their schedules, then file the rows
  whose OWN name carries the band (`evidence_tier` `A_own_name_band`) by that band; a band found
  only in GotSport's name is provider evidence, a veto and not a value, so those stay held. The
  tool has no flag that applies these, so copy the rows into a plan with `action` set to
  `would_update` and apply that plan the usual way.

A correction landing on `u9` or younger is still a correction — the team leaves the boards
because those cohorts are not ranked, and the rollover migration walks it back up to `u10` in
time.

## Step 1: Preflight

Run from `C:\PitchRank`. `data/exports/` is gitignored, so `data/exports/fix_band_cohorts.py`
and `data/exports/weekly_age_recheck.py` exist only in the main checkout and are absent from
every worktree and every fresh clone. They have no tests (IMP-242).

Credentials come from root `.env` (`.env.local` overrides it); a missing key surfaces as
`Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY` before any read.

Candidates come from `data/exports/reconcile_teams_with_gotsport_*.csv` — the most recent
execute-mode row per team. A team never reconciled cannot appear, and on a machine without
those logs the tool reports zero candidates rather than failing. Widen the population by
running `scripts/reconcile_teams_with_gotsport.py` first.

## Step 2: Plan, and read real rows

`python data/exports/fix_band_cohorts.py` with no arguments is a dry run: it re-verifies every
candidate against the live table, attaches this season's opponent evidence, checks the target
cohort for a same-named team, and writes a plan CSV. Nothing is written to the database.

Sample the plan by hand before applying. Read the surprising moves — three cohorts at once, a
club's whole roster — against the team's own name and its opponents.

## Step 3: Pilot 50 and verify

```
python data/exports/fix_band_cohorts.py --apply <plan> --strong-only --skip-name-contradictions --limit 50 --execute
```

Then confirm in the database that the 50 hold the new cohort and nothing else on those rows
changed. Verify from the database, not from the run's own summary.

## Step 4: Apply the rest

Re-run the same command without `--limit`; the piloted rows come back as `already_applied`, so
no slicing is needed. Verify the whole batch the same way. Each write carries the planned old
value as a predicate, so a team that moved since the plan is skipped and reported rather than
overwritten.

Undo with `--revert <apply log> --execute`, which touches only rows still holding what the run
wrote.

**Selecting a subset of a reviewed plan:** `--strong-only` is the set this skill's rule
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
the reconcile logs, applies the rules above, and writes `weekly_age_recheck_<date>.md`, a plan
CSV, and a row in `weekly_age_recheck_history.csv`.

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
