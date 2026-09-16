# NC PlayMetrics duplicate sweep, 2026-09-16

Scope: the 530 teams created by the first NC Youth Soccer Classic League import
(`provider_id` = playmetrics, `state_code` = NC, created 2026-09-16). Nothing was
merged. This records what the sweep found so the next run starts from a count.

## Result

| | |
|---|---|
| New teams in scope | 530 |
| With any similarly-named pre-existing NC row (score >= 0.80) | 153 |
| Candidate pairs at the 0.90 threshold, before the guard fix | 77 |
| Same, after the guard fix | 46 |
| Verified duplicates | 11 |
| Merges applied | 0 |

## Why so few

Most of these teams are new to the database rather than duplicated. Only 153 of 530
have a similarly-named pre-existing NC row at any threshold the scan would accept.
The 11 verified duplicates are all the same shape: one row holds an August
tournament from SincSports, the other the September league from PlayMetrics, with
byte-identical team names, the same club under two spellings, no shared date and no
head-to-head.

## What the sweep found wrong with the pipeline

**The birth-year guard could not read this cohort notation, and is now fixed.**
These leagues write a cohort as `<older birth year> (<band>)`, as in `15 (U11) TFA
Purple`. `_UAGE_TOKEN` erased the band and `_AFFIX_2`'s affix requirement erased the
bare number, so both sides of `13 (13U) X` and `12 (U14) X` stated no year, scored
1.0, and the guard stayed silent. 12 of 34 reviewed pairs were two cohorts a year
apart, and both pairs the decision script approved on its own were a 2011 team about
to absorb a 2010 team. `_YEAR_THEN_UAGE` closes it; the candidate count fell from 77
to 46 and the birth-year class from 12 to 0. It is anchored to the start of the
name, because only the opening position separates a cohort from the other things
written in front of a band: a squad number (`Elite S.C. 2008 Elite 11 U17`), a
season (`Spring 25 U12 Boys`), a registration window (`8/1/17-7/31/18 BU9`) and a
club founding year (`Worthington United 94 U13 Boys`).

**The club precondition refuses this whole class on a string comparison.** 75 of the
77 candidates were refused as `clubs differ` before a single fixture was read,
because the two providers spell one club differently (`Carolina Core FC` against
`Carolina Core FC Youth`). `src/utils/club_normalizer.are_same_club` resolves 33 of
them as one club. The skill's Step 4 names only the NULL case for this tell; the
dominant case here is two spellings.

**A squad qualifier does not separate two squads.** 11 pairs survived every other
gate while naming different squads: `MYSA Blue` against `MYSA Blue B`, `CSA UM Elite
1` against `CSA UM Elite 2`, `CSA North Liga` against `CSA North King`.
`extract_team_variant` treats them as one variant, so they score 1.0. This is
unfixed and is the reason the remaining 46 cannot be worked without per-pair review.

**Many pre-existing NC rows carry a team name in `club_name`.** Values such as
`15 (U11) CSA Charlotte Black` and `(12U) WHYFC Blue` appear as club names on
GotSport and SincSports rows, which is what puts 461 of the 530 out of the shipped
scan's reach entirely.

## Held

- 1 pair, `15 (U11) CSA Charlotte Black`: PlayMetrics records the club as
  `CHARLOTTE FC` while the other row's club field holds the team name. CSA reads as
  Charlotte Soccer Academy, a different organisation from Charlotte FC. Needs a
  person.
- 11 pairs refused on the squad qualifier above. These are correct refusals.
- The remaining 24 of 46 were refused as `clubs differ` where `are_same_club` also
  reads them as different clubs. Not re-examined pair by pair.

The 11 verified pairs need a human decision to apply, not a rule change. Merge
direction must be reversed on them: `pick_canonical_pair` scores name aesthetics and
chose to keep the row created this week and deprecate the established row holding
the ranking history, in 10 of the 11.
