# Handoff: Weekly Data Hygiene — Step 3 (Fuzzy Duplicate Merge)

## The task

Walking the weekly data-hygiene GitHub Action (`.github/workflows/data-hygiene-weekly.yml`)
step by step, fixing each one. Steps 1 and 1b are done and merged. Step 2 is investigated
and the recommendation is to leave it off. **Step 3 is next and is the big one** — it is
disabled because it merged 1,772 pairs of distinct teams on 2026-08-19.

## Read this first: the working tree lies

`C:\PitchRank` is on branch `fix/emailed-auth-links-spent-before-click`, **34 commits
behind `origin/main`**, with uncommitted edits that are *already on main*. Its copies of
`scripts/find_fuzzy_duplicate_teams.py` and `.github/workflows/data-hygiene-weekly.yml`
are stale.

**Work from `origin/main`.** `git show origin/main:<path>` and
`git grep -n <pattern> origin/main -- <paths>`. Run `export MSYS_NO_PATHCONV=1` first or
git-bash mangles the colon form. Do not "fix" the local uncommitted changes — they are the
old branch's version of work that already landed.

Direct Postgres (psycopg2 on `DATABASE_URL`) is **firewalled from this host** — it times
out. Use PostgREST: `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)` from the
`supabase` package, paginating `.range(off, off+999)`. A full scan of `games` (~1M rows)
deep-offsets into a statement timeout; batch by team id, 100 per `.in_()`. Credentials in
`C:\PitchRank\.env.local` — load with the absolute path, a bare `load_dotenv()` returns
empty.

## The authoritative age-group chart — do not re-litigate

The maintainer stated this twice and it is the rule. A two-year team name maps to the
group by its **younger** year:

    U10 2017/2016   U13 2014/2013   U16 2011/2010   U19 2008/2007
    U11 2016/2015   U14 2013/2012   U17 2010/2009
    U12 2015/2014   U15 2012/2011   U18 2009/2008  (no U18 board; folds to U19)

So `13/14` is **U13**. `scripts/normalize_team_names._resolve_band` implements this and
matches 9 of 10 rows exactly (U18 folds to U19 because `AGE_GROUPS` has no U18 and the
teams table has zero u18 rows).

Opponent data appears to contradict this — combined two-year squads play the older year's
teams about 2:1, and adjacent birth years share a cohort only 10.6% of the time. That
argument was raised, evaluated, and **rejected by the maintainer**: brackets and
registration are not our concern, the chart is. Do not reopen it.

## What is already done

| | Status |
|---|---|
| Step 1 — normalize names | Merged (#996, #997). Rewrites ~37,900 names Monday. |
| Step 1b — backfill distinction | Merged (#1001). Was dead 12 weeks; fills 46,454 gaps Monday. |
| Step 2 — fix age groups | **Leave off.** Only ~326 teams have a correctable `age_group`; writing it moves a team between ranking boards with no undo. `AGE_DERIVATION_ENABLED: 'false'` in both callers. |
| Step 3 — fuzzy merge | **Next.** `FUZZY_AUTO_MERGE_ENABLED: 'false'` (workflow line 82). |
| Step 4 — queue auto-approve | Off. `QUEUE_AUTO_APPROVE_ENABLED: 'false'`. Its writes are noted as *less* recoverable than merges — aliases have no audit table and no revert RPC. |

Also merged this session: five PRs (#996–#1001) covering the band rule, the age-derivation
gate on the manual workflow, `CLAUDE.md` corrections, blog content (U18 rows removed), and
~22 stale code comments.

## Step 3 — what is known going in

**Why it is off** (workflow lines 74–82): `score_team_pair` compares names with
`SequenceMatcher`, and two shapes clear the 0.90 auto-merge bar without being duplicates —
`unknown_781631` vs `unknown_781653` scores 0.929 on the shared placeholder prefix alone,
and `EPIC SC 2008 Dash` vs `EPIC SC 2009 Dash` scores 0.941 plus 0.15 for the matching
club. U19 holds two birth years at once, which is why that one cohort produced 780
suggestions. The 2026-08-19 run merged 1,772 pairs.

**Guards already on main** in `scripts/find_fuzzy_duplicate_teams.py` — verify they are
sufficient rather than assuming:
- `is_placeholder_name()` (:60) rejects `unknown_\d+` names before scoring
- `birth_years_conflict()` (:101) rejects pairs stating different birth years
- `should_skip_pair()` (:270) re-derives distinctions via `scripts/_team_distinction.py`
- `--min-score` defaults to **0.95**, though the workflow may pass something else — check
  lines 246 and 250 for the actual invocation

**A revert tool exists and is tracked on main**: `scripts/revert_fuzzy_auto_merges.py`.
It has `--dry-run` and `--limit`. `execute_team_merge` records a full
`deprecated_team_snapshot` in `team_merge_audit` plus `reverted_at/reverted_by/
revert_reason`, and merges resolve at read time through `MergeResolver`, so a revert is
three writes: un-deprecate the team, repoint `team_alias_map`, drop the `team_merge_map`
row. It has already been run — see the next section.

## The merge backlog — already answered, do not re-ask

The 1,772 merges from 2026-08-19 **were reverted**. That figure in the workflow comment is
the revert count, not a backlog. Checked 2026-08-21 against `team_merge_audit`.

August totals: 3,839 merges by `pitchrank-bot`, 3,285 reverted, **554 still in place**.
Replaying those 554 through the guards now on main:

    319   audit row has no name snapshot — cannot judge
    154   birth years agree — merges look legitimate
     71   ambiguous — a name uses two-digit shorthand (see below)
      6   look genuinely wrong, but the revert tool skips them

Four more were reverted on 2026-08-21 via
`revert_fuzzy_auto_merges.py --execute --since 2026-08-01 --birth-year-conflicts`
(Alliance FC '09 Academy, PSA Monmouth '08 ECNL, Las Vegas Alliance FC '09,
LAS VEGAS DIVERSITY FC '08 Academy). Verified un-deprecated and no longer redirected.
No un-reverted placeholder merges remain in August.

**Do not trust a naive `birth_years_conflict` sweep.** It over-reports badly — it called 81
of these bad when only 4 were safely actionable. Names like `B08/07` lose a year during
normalization, so a pair looks disjoint purely from that loss. `keep_birth_year_conflicts`
in the revert script guards against this; a hand-rolled check does not.

Open, needing judgement rather than automation:
- Why does the tool skip the 6 that look clearly wrong (`Union 2010 FC 2009` merged into
  `Union 2010 FC 2008`, `Pacesetter SC 2009 Red` into `Pacesetter SC 2008 Red`)?
- Are the 319 nameless audit rows recoverable at all? This decides whether that cleanup is
  even possible.

**Decided: do not move the revert script into the Step 2 slot.** It mops a leak that is
already off (Step 3 is disabled), it only knows two patterns and both are now guarded at
the source, and an automatic un-merger running weekly could undo a correct merge. Keep it
as an operator tool. Leave Step 2 empty.

## Open questions for Step 3 itself

1. Do the guards now on main actually close both failure modes? Replay the 2026-08-19 pairs
   through the current `score_team_pair` and count how many still clear the bar.
2. What else clears 0.90 that should not? The two known shapes were found after the fact,
   which is the worrying part — nobody has swept for a third.
3. Is auto-merge worth having at all, versus a review queue? A merge is the least reversible
   write in the system, and `team_merge_audit` has a 319-row hole in its name snapshots.
4. If it is re-enabled, what proves it is safe before the flag flips? There is no backtest
   harness today.

## Context worth carrying

- Monday's run is the **first that can report a failure**. All four `tee`'d steps now set
  `pipefail`; previously `tee` returned 0 and a crash looked green. If a step goes red,
  that is the fix working, not a regression.
- `claude-review` fails on every PR repo-wide — the `ANTHROPIC_API_KEY` secret is empty.
  Not a code problem; ignore it when judging CI.
- Codex reviews each PR **once**, on first push, and does not re-review after fixes. Read
  its findings but verify them — it has been both right (the older-year band argument, the
  hyphenated `GU-12` gap) and wrong (a stale-doc citation, a PR-ordering artifact).
- Heredocs in this environment eat backslashes. Write patch scripts to a file with the
  Write tool instead of piping them through `bash <<'PY'`.
- `git add <dir>` sweeps tracked `.pyc` files into the commit. Stage files individually.

## Next concrete action

**Verify the guards actually close the failure modes.** Replay the 2026-08-19 merge pairs
through `score_team_pair` as it stands on `origin/main` and count how many still clear the
0.90 bar. That number decides everything else: if it is zero, the conversation is about
re-enabling Step 3 behind a backtest; if it is not, the guards are incomplete and need work
before the flag is touched.
