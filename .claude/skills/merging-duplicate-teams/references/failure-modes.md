# Failure modes

Shapes in which name similarity has already declared two different squads a duplicate. Use
these to recognise a known shape quickly and to spend review effort hunting for new ones.

## Contents

- Why the list keeps growing
- Shapes found in the names
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
the most. Guarded.

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
