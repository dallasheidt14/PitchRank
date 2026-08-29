# Failure modes

Shapes in which name similarity has already declared two different squads a duplicate. Use
these to recognise a known shape quickly and to spend review effort hunting for new ones.

## Contents

- Why the list keeps growing
- Shapes found in the names
- The birth-year guard is silent more often than it fires
- Silent exclusions — pairs the scan drops without saying so
- Shapes no name rule can reach
- Shapes found only across a batch
- What review should hunt for

## Why the list keeps growing

Assume this list is incomplete and that a fresh sweep will find another shape. The underlying
cause is not a parsing bug: clubs legitimately field several squads that differ only in ways
the names do not reliably encode, so no amount of name-rule work terminates.

## Shapes found in the names

**Placeholder names.** `unknown_781631` against `unknown_781653` scores 0.929 on the shared
prefix and the closeness of two provider ids. Guarded.

**Two different birth years.** `EPIC SC 2008 Dash` against `EPIC SC 2009 Dash` scores 0.941
plus a club-match bonus. U19 holds two birth years at once, which is why that cohort produced
the most. Guarded — **but only when both stored names carry a four-digit year.** Read the next
section before relying on that word.

**Age label against birth year.** `STA MOSC U19 DPL` against `STA MOSC 2009 DPL`. `birth_years`
reads nothing from a U-label, and an empty set never disagrees with anything, so the conflict
check cannot fire. Meanwhile the distinction check canonicalises both to the same cohort — 
correctly — and sees no difference. Both guards are individually right and jointly blind.
Resolved by dating the label through the season played.

**Two-digit years.** `Select-09` against `Select-07/08`. Same hole from the other side:
nothing is read from the two-digit form, so no conflict is detected.

**Band against single year.** `MVP 2015 Grey` against `MVP B15/16 Grey`. The subset rule lets
these through by design, having been chosen for recall.

**Numeric squad suffix.** `NYSA B1607`, `B1609`, `B1611`, `B1710` at one club — four squads
distinguished only by a trailing number, three pairs of which have played each other. `1607`
is not in the birth-year range, so nothing is read from either side.

**Gender letter.** `2017G` against `2017`, `U10 Premier` against `BU10 Premier`. Both pairs
have played each other.

**The flagship pattern is not safe either.** A bare name against a club-prefixed name —
`Academy ECNL 2013` into `Charlotte Soccer Academy - Charlotte SA ECNL 2013` — is the case the
duplicate scan exists to catch, and that club fields two ECNL 2013 squads that share ten game
dates.

## The birth-year guard is silent more often than it fires

`birth_years_conflict` is the **first** rule that stops a 2008 team absorbing a 2009 team, not
the only one — `cohort_of` in `decide_team_merges.py` is a second, independent layer that dates
U-labels from the seasons actually played and can refuse where the guard was silent. Neither is
a backstop for the other, and one branch bypasses both (see below).

The guard returns `False` — no conflict — whenever **either** side states no years. Measure the
blind rate on the cohort you are working rather than assuming; on live `u19`:

```
u19 live rows: 26,756
birth_years() returns empty: 5,848  (21.9%)
```

Measure it with `scripts/check_merge_skill_assumptions.py`, and **order the query**. PostgREST
leaves row order unspecified without an `.order()` clause, so paging a cohort silently drops
rows: the same u19 count came back as 22,508 rows and 4,855 blind unordered, against 26,756 and
5,848 ordered. A 16% undercount, reproducible, in the direction that makes the problem look
smaller than it is.

Three separate, verified causes make a side state no years, and none is visible in the output.

**1. A U-label carries no year, and the weekly normalizer creates U-labels.**
`scripts/normalize_team_names.py --all-teams` is Step 1 of the same Monday job, and it is the
only hygiene step with no freeze flag. It rewrites a birth-year band into a single U-age:

```
'EPIC SC B09/08 Dash' -> 'EPIC SC U19 Dash'
'EPIC SC B08/07 Dash' -> 'EPIC SC U19 Dash'      <- two cohorts, identical output
```

And the guard then reads nothing from either:

```
birth_years('Club U19 Red')                          -> set()
birth_years_conflict('Club U19 Red', 'Club 2008 Red') -> False
birth_years_conflict('Club U19 Red', 'Club 2009 Red') -> False
```

20,146 live rows carry a U-label and no four-digit year in `team_name`. The normalizer disarms
the merge scan's own safety check, every week, on the row it just rewrote — and `u19` is the one
cohort where that check has to earn its keep, because it is the only one holding two birth years.

**The documented fallback does not rescue `u19`.** Reading `team_name_original` is partial
corpus-wide (90,032 live rows have it NULL) but in `u19` it is effectively useless: of the 5,476
blind rows, one has a year recoverable that way. Do not plan around the fallback in that cohort.

**2. Gender is erased too.** `'Rush 14B Black'` and `'Rush 14G Black'` both normalize to
`'Rush 2014 Black'`. 21,214 live rows are byte-identical in (club, name, age group) to an
opposite-gender team. The stored `gender` column is the only thing separating them.

**3. A dead branch in the extractor.** `_GENDER_WORD` in `team_name_utils.py` was written with
literal backspace bytes where `\b` was intended, so the branch can never match:

```
birth_years('Club 12 Boys')  -> set()      # expected {2012}
birth_years('Club Boys 12')  -> set()
birth_years('Club 2012 Boys') -> {2012}    # different branch, works
```

2,953 live rows use that form.

The documented workaround — read `team_name_original` — is partial: **90,032 live rows have
that column NULL**, because it is stashed only on the first rewrite and rows normalized before
that behaviour shipped never got one. `birth_years`' own docstring says it reads the raw name
and that `normalize_team_name` is the wrong substrate; the shipped scanner passes it
`teams.team_name` anyway.

## Silent exclusions — pairs the scan drops without saying so

These remove pairs from consideration entirely. They produce no verdict, no log line, and no
entry in `decisions.json`, so nothing downstream can tell they existed.

**A division token — `AD`, `HD`, `EA` or `MLS NEXT`.** `has_protected_division` withholds these
from the scan, 4,553 live rows. That is intended: the tiers must not be merged across.

Until IMP-135 it tested bare substrings, so any name whose second-or-later word merely began
with those letters read as a division and was excluded with no log line:

```
'FC EAST 2012'                         -> was protected, now eligible
'SC EAGLES 2013'                       -> was protected, now eligible
'FSA Timberwolves 2016GR (L Adams NR)' -> was protected, now eligible
'EAST MEADOW 2012'                     -> was not protected   # first word, no leading space
```

That withheld 2,660 unrelated rows and made the exclusion position-dependent, which is why a
leading EAST behaved differently from a trailing one. The check now matches whole tokens, so
those names reach the scan; 88 rows leading with a real `AD`/`HD`/`EA` token became protected
in the same change, having previously slipped through for want of a preceding separator.

**Placeholder names.** `unknown_<digits>` on either side returns `None` before scoring. Correct
as a name rule — the names carry no information — but it means the whole placeholder class can
only be reached through Doorway B.

**Rows the fetch never returned.** `fetch_teams` in `find_fuzzy_duplicate_teams.py:197-225`
pages 1,000 rows at a time with no `.order()` clause. PostgREST does not guarantee a stable
order across pages without one, so every cohort scan silently drops a share of its own input —
16% when reproduced on `u19`. These rows are not skipped by a rule; they are never fetched, so
they appear in no count, no verdict and no report, and the loss is invisible from the output.
A one-line fix in the scan, but until it lands, treat every per-cohort figure this pipeline
produces as a floor.

## Shapes no name rule can reach

**Byte-identical names.** Two rows both called `ECNL RL G08/07` in the same club, cohort and
state, each with roughly fifty games and six conflicting fixture dates. The names carry no
distinguishing information, so only behaviour separates them.

**Truncated names.** An importer cutting names near fifty characters makes different teams
collide on an identical prefix, and the same truncated string can appear on several unrelated
rows in a large club.

**Laundered names.** Name normalization rewrites a two-year band to a single year and strips
gender letters, erasing the exact token that distinguished two squads — and it runs *before*
the duplicate scan in the same weekly job. Any band or gender check must therefore read
`team_name_original`, not `team_name`.

## Shapes found only across a batch

**A row that is already a fusion.** `SC Blues 2012 DPL` carries 176 games — the club's DPL,
ECNL and ECNL-RL squads sharing one row, fused at the **alias** layer with no merge in its
history. Concurrent registrations in different competitions are the signature; sequential ones
are ordinary season re-registration. Merging into such a row compounds an existing error.

**Inherited history read as empty.** A row that is itself the canonical target of earlier
merges holds games filed under absorbed ids. Counting raw ids makes it look empty and removes
the evidence that would have refused the merge.

**A cluster that is one import event.** A large single-state or single-club cluster is usually
a season registration wave, which is legitimate and raises confidence. Establish which it is
from provider ids and creation dates rather than assuming either way.

## What review should hunt for

The shapes above are handled or recognisable. Spend review effort on what a per-pair name
check structurally cannot see:

- two rows in different flights of the same league, with disjoint opponent sets
- a squad qualifier that is load-bearing at that specific club — a coach surname, a branch, a
  colour, a tier number — where the other row carries none
- a surviving row that has never played and has never been scraped, so nothing has confirmed
  what it is
- a stored cohort or gender that the games contradict
