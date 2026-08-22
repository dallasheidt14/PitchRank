# Evidence rules

The rules `scripts/decide_team_merges.py` applies, why each exists, and what happens when
they are loosened.

## Contents

- The precondition
- The decisive refusals
- Reading an age label
- What a merge requires
- The measured trade-off
- What none of this establishes

## The precondition

Before any evidence is weighed, the two rows must agree on club, state and stored gender, and
neither name may contradict its own stored gender.

The duplicate scan already compares only within one club, state and gender, so these normally
hold. Re-check them anyway: a candidate list can arrive from anywhere, and the stored gender
is not self-validating. A batch import filed every California row named `GU8`/`GU08` created
on one day as Male, including one at a girls-only club. A merge across that error deprecates a
live boys squad into a girls team.

Where a name spells out "Boys" or "Girls" in words and the column disagrees, the name wins and
the pair is refused — fix the column first with
`scripts/fix_gender_from_registered_name.py`. A bare `B`/`G` letter is not enough to
contradict a column: it can be a colour, a squad code, or a coach initial.

## The decisive refusals

**They played each other.** Two rows that met on the pitch are two teams. No further argument
applies.

**They both played on the same calendar day.** A squad cannot be in two places. Verify the
opponents are genuinely different clubs before trusting a single instance — a duplicated
fixture against a duplicated opponent can imitate this. Of 23 same-day conflicts in one
batch, 21 involved different opponent clubs, and the two that did not each had many other
conflicting dates.

In one full batch the set of pairs sharing a game date was exactly the set provable as
different teams — no exception in either direction.

**Their birth years disagree.** After resolving labels, as below.

A pair is also refused outright when either row is missing or already deprecated, and routed
to review when either row carries three or more registrations from one provider — a row
already fusing several squads at the alias layer, which a further merge compounds.

## Reading an age label

`U11` names no cohort by itself: the label moves every Aug 1 while a birth year does not. So
`U11` and `2016` can be the same squad or two different ones, depending entirely on when the
games were played.

For a season starting in year `Y` (Aug `Y` – Jul `Y+1`), `U-N` means birth year `(Y+1) − N`.
`U19` also covers `(Y+1) − 18`, since U18 folds into the U19 board.

Resolve each side's label through the seasons that side's games actually fall in, then compare
birth-year sets. This is what separates `CFA OC SC U12 Miguel` / `CFA OC SC 2015 Miguel` —
two live squads — from `SW U12 - SOCAL` / `SW 2015 - SOCAL`, one squad re-registered.

Read labels with `team_name_utils._UAGE_TOKEN`. It matches the gender-affixed forms
(`GU11`, `U11G`, `BU12`, `U12B`) that make up most real labels. A hand-rolled pattern that
misses them reads no cohort at all and silently disables the check — that mistake hid 99
mergeable pairs and 14 genuine cohort conflicts in one run.

## What a merge requires

Absence of contradiction is not evidence of duplication. A merge needs a positive reason:

- both names resolve to the **same** birth-year set, **and**
- the two schedules never share a season — a club re-registering one squad — **or** they
  share at least two opponents, meaning one schedule split across two records

One shared opponent is too easily coincidence. Requiring two was the difference between
destroying a real team and not, in testing.

A band against a single year (`2015` vs `15/16`) always goes to review. Clubs use both
conventions for both situations, and the codebase's own subset rule was chosen for recall
rather than precision.

An empty row merges only when it also comes from a different provider — a cross-provider
duplicate. "No games" alone is weak: most empty rows are stale registrations rather than fresh
ones, and many have never been scraped, so nothing has confirmed they are empty.

## The measured trade-off

Scored against pairs judged independently from game data:

| Rule set | Real teams destroyed | True duplicates merged |
|---|---:|---:|
| merge on ≤1 game, or equal cohort | 3 | 84% |
| require positive evidence + exact cohort | 0 | 34% |
| **+ cross-provider empty shells (shipped)** | **0** | **36%** |
| + merge on a single shared opponent | 1 | 37% |
| + merge unknown cohorts with disjoint seasons | 2 | 42% |
| + merge any empty shell | 2 | 46% |

Safety and yield trade directly, and the safe edge is around a third. Past that the names
genuinely do not contain the answer, so more yield can only come from behavioural evidence or
a person — not from tuning.

Treat any change that raises the merge rate as a regression until it is re-scored against
adjudicated pairs.

## What none of this establishes

A shared game date is strong evidence of distinctness. Its absence is **not** evidence of
duplication — two squads in different divisions may simply never clash. The rules remove
demonstrable errors; they do not certify the remainder. That is why anything not refused and
not positively supported goes to review rather than through.
