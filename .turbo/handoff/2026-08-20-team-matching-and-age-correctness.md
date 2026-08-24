# Handoff: team matching and age-group correctness

**Date:** 2026-08-20 · Continues `.turbo/handoff/2026-08-19-stabilize-unknown-teams.md`

## The one-paragraph version

Every defect found today is the same mistake wearing different clothes: **the system
decides which team is which by reading numbers out of team names, in about six
different places, each with its own slightly-wrong rules.** Ten PRs shipped fixing
that. One PR is open. One change is built but **not shipped and needs a decision** —
it would rewrite 77% of team names. Separately, a credential leak found during
cleanup still needs action.

---

## DO THIS FIRST — not code

**`.env.local` was committed to a PUBLIC repo on 2026-01-17 (`d747981c1`) and contains
`SUPABASE_SERVICE_ROLE_KEY` and `DATABASE_URL`.** Seven months exposed. The service-role
key bypasses row-level security.

- #994 (merged) stopped tracking the file. **That revokes nothing.**
- **Rotate both credentials**: Supabase → Settings → API (roll service-role key), then
  Settings → Database (change password). Update Vercel env vars and GitHub Actions secrets.
- History purge still pending and needs a force-push, which the agent permission layer
  blocks — the maintainer must run it:
  ```
  git filter-repo --path .env.local --invert-paths --force
  git remote add origin https://github.com/dallasheidt14/PitchRank.git
  git push --force --all && git push --force --tags
  ```
  Purging is NOT a substitute for rotating.

---

## Merged today

| PR | What |
|---|---|
| #979 | Restored 263 teams whose provider alias the merge-revert had dropped — the scrape queue was silently re-absorbing them, unrevertably |
| #980 | Gated Step 4 of data-hygiene (`QUEUE_AUTO_APPROVE_ENABLED`) and `auto-merge-queue.yml` |
| #981 | **The core fix.** `birth_years` / `birth_years_conflict` in `src/utils/team_name_utils.py`, wired into six matching call sites |
| #990 | Two word-boundary bugs in `find_queue_matches.py`; plus `repair_defective_aliases.py` |
| #991 | Retired 531 aged-out teams to `u20`; made birth year 2007 resolve to U19 |
| #992 | TGS dual-year band handling — **contained a bug, fixed in #996** |
| #993 | `_lookup_state` picks the club's majority state; candidate search merges home + complement |
| #994 | Stopped tracking `.env.local` |
| #995 | `backfill_state_from_team_name.py` — 176 teams, new Step 0 in `update-missing-club-and-state.yml` |
| #996 | **OPEN** — band read from younger year; frontend reads `age_group` before name |

### Applied directly to the database (rollback CSVs in `logs/`)

- 263 provider aliases restored
- 6 defective aliases re-pointed (11 skipped rather than guessed)
- 531 aged-out teams → `u20`
- 3 club-name corruptions repaired (`2006 United FC` → `06 United FC`)
- 176 state codes filled from team names

---

## The rule that governs everything

Age groups are **bands spanning two birth years**, because the season runs Aug 1 – Jul 31.
Maintainer's published table for 2026-27:

```
U9 (2018/17)  U10 (2017/16)  U11 (2016/15)  U12 (2015/14)  U13 (2014/13)
U14 (2013/12) U15 (2012/11)  U16 (2011/10)  U17 (2010/09)  U18 (2009/08)  U19 (2008/07)
```

Verified: every row satisfies **U_N = {SEASON+1−N, SEASON−N}**. So **N = SEASON+1 minus the
YOUNGER year.** Reading a band from its older year is one group too old, every time.

Three traps that have each caused a bug:

1. **A bare year is ambiguous, a band is not.** 2016 is U10 *or* U11; the band 2016/15 is U11.
2. **The age-20 fold applies to bare years only.** A lone 2007 is U19 (only U19 contains it),
   but the *band* 2007/06 has aged out. Folding it files an aged-out band as U19.
3. **`_tracked_age_group` folds 18→19 and the teams table holds ZERO rows at u18.** Anything
   emitting `u18` files teams under a cohort nothing can match.

---

## IN FLIGHT — needs a decision before it ships

**Worktree:** `C:/PitchRank-bands` · **Branch:** `fix/dual-year-bands-read-younger-year`
**Uncommitted:** `scripts/normalize_team_names.py`

### What the maintainer asked for

Stop putting birth years in team names. The name should show the **age group**, rendered
from `teams.age_group`, so the annual rollover is: update the column, re-run the job, names
follow. `age_group` is 100% populated, 97.6% in U10–U19, and every ranked team has one.

### What is built and working

```
normalize_team_name(team_name, club_name, age_group)   # new 3rd param

Aspire 12/13                   + u14  ->  Aspire U14
Sparta Tacoma - B14/15 Silver  + u13  ->  Sparta Tacoma - U13 Silver
Dallas Texans ECNL B08/07      + u19  ->  Dallas Texans ECNL U19
```

Both callers (`run_with_psycopg2`, `run_with_supabase`) select and pass `age_group`. Without
the column the old behaviour applies, so import-time matching is unaffected.

### Why it is NOT shipped — live dry run against production

```
Would update: 144,484 of 188,639 live names   (77%)
```

Two problems:

1. **BUG — 1,631 names end up with two age tokens.** The first converts, the second survives:
   `'Auburndale Scream 2013 U13'` → `'Auburndale Scream U14 U13'`. Fix: drop a second age
   token once one is found. Not yet done.

2. **THE DECISION — the column and the name disagree on 17,581 teams, and the column wins:**
   ```
   'LB GU12 Grey'           column u13  ->  'LB U13 Grey'
   'Dallas Surf U15G Blue'  column u16  ->  'Dallas Surf U16 Blue'
   'U8 White'               column u12  ->  'U12 White'
   ```
   If the column is right these are 17,581 corrections. If it is wrong anywhere, the error
   is written into names where nothing can check it afterwards — and at least one case is
   suspect: `B14/15` is stored `u13` where the published table says U12.

**Offered and awaiting the maintainer:** produce a CSV of all 17,581 showing the name's age,
the column's age, and the birth year in the original name, so the column can be audited
*before* anything is written. ~10 minutes.

---

## Still open

**Flags that must stay `false`** — the normalizer repair unmasked 86 new merges the
birth-year guard does **not** block (67 have matching years, 19 state no year). Do not lift
either on the strength of that guard:
- `FUZZY_AUTO_MERGE_ENABLED`
- `QUEUE_AUTO_APPROVE_ENABLED`

**Step 1 of data-hygiene has a bigger unfixed problem than the band bug.** 6,950 teams sit
un-normalized because `backfill_unknown_team_names.py:309` writes raw GotSport names
straight to the database — it does not import the normalizer — and Step 1 only runs weekly.
One-line fix in the backfill, not in Step 1.

**Issues filed with findings posted:**
- **#983** — 75 misfiled games via 8 `affinity_wa` aliases. Confirmed real (opponents are
  100% one birth year). Needs a quarantine-vs-reattribute decision; games are immutable.
- **#984** — rescope to **5** real defects, not 250. 234 of 250 are gap-1, i.e. the same band
  labelled from either end. The "7,834 games" headline was wrong.
- **#985** — recommend closing. 96 of 119 are band-edge labelling; the 2 real ones are the
  maintainer's own merges into demonstrably healthy canonicals.
- **#986** — half fixed by #993. The `club_name` half is squadi-only and squadi is dead (no
  code in repo, zero games ever) — closeable.

**Not repaired:** 1,453 names already flattened to the older year by the old normalizer.
`team_name_original` preserves the band, so recoverable as a separate job.

---

## Techniques worth reusing

**Opponents settle age questions that names cannot.** Teams play their own age group, so
opponent birth years reveal the true cohort. This is what separated real defects from noise
across #983/#984/#985 — unanimous opponents plus a differing provider name means a misfile;
opponents straddling both years means band labelling and is fine.

**A test that passes for the wrong reason is how both band bugs shipped.** `B2008/2007` is
correct under *both* the right and the wrong rule, because 2007 falls out of range and folds
back to U19. Walk the whole table, never one case.

**Peer review (`/peer-review` → codex) caught what review-by-reading missed.** It rejected
the first version of #996 outright and was right. Note: the harness kills foreground bash at
10 minutes; run codex with `run_in_background: true` and `-o <file>`.

**Environment traps:** force-push and `git reset` are blocked by the permission layer.
Heredocs mangle backslashes — write patch scripts to a file instead. Worktrees have no
`node_modules`, so run `tsc`/vitest in the main `C:/PitchRank` checkout.

---

## Next concrete action

**Ask the maintainer whether to audit the 17,581 name/column disagreements before writing
them.** If yes, produce the CSV. If they are confident `age_group` is authoritative, fix the
duplicate-age-token bug (1,631 names) and ship the in-flight `normalize_team_names.py`
change. Nothing else in this session is blocked.
