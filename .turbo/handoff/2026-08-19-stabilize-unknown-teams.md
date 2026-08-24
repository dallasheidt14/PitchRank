# Handoff: unknown_ placeholders + fuzzy auto-merge fallout

**Date:** 2026-08-19 · **Plan:** `.turbo/plans/stabilize-unknown-teams.md`

## What happened

Two linked problems, both now contained.

**Placeholders.** The weekly unknown-opponent job (`unknown-opponent-hygiene-weekly.yml`, Tue 18:00
UTC) creates teams named `unknown_<provider_team_id>` because its GotSport lookup is WAF-blocked
from CI and the block is silently recorded as "this team has no name." ~30,000 accumulated.

**Merges.** Those placeholder names then poisoned `find_fuzzy_duplicate_teams.py`, which scores
team names with `SequenceMatcher`. `unknown_781631` vs `unknown_781653` scores 0.929 on the shared
prefix alone — over the 0.90 auto-merge bar. A second shape did the same with birth years
(`EPIC SC 2008 Dash` vs `... 2009` = 0.941 + 0.15 club boost). **5,016 wrong merges since March,
all reverted.**

## Current state

| | |
|---|---|
| Live placeholders | **23,630** (19,216 resolvable, 4,414 permanently dead) |
| `team_merge_map` | 10,280 (was 13,508) |
| Merges reverted | 5,016 — 0 known-bad remaining |
| Backfill cron | running, ~7,200/day, resolvable set clears in ~2.5 days |

Merged today: #963 #964 #965 #966 #968 #969 #970 #971 #972 #975.

**Two jobs are gated OFF and must stay off:**
- `FUZZY_AUTO_MERGE_ENABLED: 'false'` — data-hygiene Step 3 (fuzzy merge)
- `AGE_DERIVATION_ENABLED: 'false'` — data-hygiene Step 2 (`fix_team_age_groups.py`)

## Outstanding — in priority order

### 1. Decide what the fuzzy merge step becomes (needs a decision, then ~1-2 days)

**The finding that matters:** correct and incorrect merges score *identically*.

```
LEGIT   Rangers FC - 2017 White / Rangers FC 2017 White    1.000
WRONG   Richmond United ... B2014/15 1  /  ... 2           1.000
WRONG   PDA South ECNL I  /  PDA South ECNL II             1.000
```

No threshold separates them — `--min-score` is not a lever. Every fix is another categorical
guard, and four shapes have been found so far (placeholders, birth years, year-shorthand, squad
numbers), each discovered only after it caused damage. Squad numbers still leak: **103 sibling
groups covering 213 teams** in the first 60,000 scanned (`Mustang SC 2014 Elite II` / `III`).

**Recommendation:** drop `--auto-merge` from the workflow, add `--output`, write
approved/needs-review CSVs (the shape `unknown-opponent-hygiene-weekly.yml` already uses), and
route them to the dashboard's existing Team Merge Manager. Volume is review-sized — three of the
last five Mondays produced zero non-placeholder suggestions, one produced 223.

Do not flip `FUZZY_AUTO_MERGE_ENABLED` back on without this, or at minimum without a clean
u19-female dry run first (that cohort produced 769 bad merges in one run).

### 2. Two bugs in the merge path, worth fixing whenever that file is touched

- `execute_merge` never passes `p_confidence_score` (`scripts/run_all_merges.py:253-261`), though
  `execute_team_merge` accepts it. All 5,016 merges recorded `0.0`, which is why the forensics had
  to be rebuilt from timestamp windows.
- `find_fuzzy_duplicate_teams.py:337` reads `dry_run = args.dry_run and not args.auto_merge`, so
  **`--auto-merge --dry-run` performs real merges.**

### 3. Mark the dead provider IDs (needs a migration; only after the drain finishes)

4,414 teams created before 2026-05-01 have 7-digit GotSport IDs that return `404 Can not find
team` permanently. Once the resolvable ones drain they become the entire work-list and the cron
grinds them forever. Add a `resolution_attempted_at` column, set it on 404 in
`backfill_unknown_team_names.py`, exclude those rows from the fetch.

**Separate question:** those 4,414 can never be named from GotSport. Leave / re-source / retire?
They carry games, so deletion is not obviously safe.

### 4. The age-group question (blocked on the maintainer, blocks nothing else)

`fix_team_age_groups.py` computes `CURRENT_YEAR - birth_year + 1`, which cannot be right under
Aug 1 – Jul 31 banding: one birth year spans two cohorts and PitchRank stores birth *years*, never
birth *dates*. What is known:

- The Aug 2026 rollover migration **did** run — backup tables present, no `u18` survivors,
  pre-Aug-1 teams match the 2026-27 mapping at 100.0%.
- GotSport's `display_age_group` is not usable as truth — two different `2014` teams returned
  `U14` and `U12`.
- Dual-year names (`B2016/17`) look like band labels and may be the best signal, but that reverses
  the "always take the older cohort" rule from 2026-05-01, and `Illinois FC 2016-2018` /
  `U13/12 Boys` show the format is unreliable.

**Nothing should write `teams.age_group` from any source until this is settled.**

### 5. Residue (small, independent)

- **263 merges moved more than one alias.** Only the alias games route through was repointed;
  extras remain on the canonical. Identifiable via `aliases_updated` in `team_merge_audit`.
- **93 dual-year merges deliberately not reverted** — `2013 Lobos Rush Gold` → `2013/14 Lobos Rush
  Gold` and similar are the same team labelled from either end of its band.
- **Six copies of the GotSport resolver.** Five read `full_name`, `state`, `age`, `gender` — keys
  the API does not return. That is the original cause of all 30,000 placeholders. Consolidating
  onto one resolver on the WAF-aware transport would retire the root cause.

## Invariants

1. `FUZZY_AUTO_MERGE_ENABLED` stays `false` until item 1 is decided.
2. `AGE_DERIVATION_ENABLED` stays `false` until item 4 is decided.
3. Nothing writes `teams.age_group` from a name or from GotSport meanwhile.
4. The backfill writes `team_name` and `club_name` only.
5. Any new team-matching code must reject placeholder names — `is_placeholder_name` in
   `scripts/find_fuzzy_duplicate_teams.py`, or `_is_placeholder_team` in
   `src/tournaments/triage.py`.

## Gotchas worth knowing

- **GotSport WAF is a burst limiter, not an IP ban.** Paced requests from GitHub runners work fine
  without ZenRows — `process-missing-games.yml` has done it for months. Bursting is what fails.
  The shared `WAFBreaker` lives in `src/scrapers/gotsport.py`; importing it pulls in
  `src.etl.pipeline`, so any workflow using it needs `pandas`, `rich`, `numpy` installed.
- **A guard tested with hand-built dicts can be inert in production.** The first placeholder guard
  read `provider_team_id`, which `fetch_teams` does not select — it never fired. Test against the
  shape the real query returns.
- **`git show origin/main:path` mangles on Git Bash for Windows.** Use `MSYS_NO_PATHCONV=1`.

## Next concrete action

**Decide item 1: does the weekly fuzzy merge keep auto-merging, or become a review queue?**
Everything else is either unattended (the drain), blocked on that decision, or small enough to
pick up any time. Nothing is currently at risk — both dangerous jobs are gated off and the
database is clean of every known bad merge.
