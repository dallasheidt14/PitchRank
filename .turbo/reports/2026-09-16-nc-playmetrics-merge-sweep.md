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
| Merges applied | 166 |

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
club founding year (`Worthington United 94 U13 Boys`). The band is not required
either: GotSport's Carolinas rows open with the year and go straight to the club
(`13 WUSC Revolution Blue`), so a leading two-digit number in the birth-year range
is read as the cohort wherever it opens a name. A leading season (`25 BAC Shooting
Stars`) falls outside that range and is dropped by it.

**The scope above is one import; the duplication is state-wide.** Clustering every
live NC team on the squad identity in its name, with the stored age group and
gender held equal and cohorts judged from the names, finds 316 clusters covering
332 rows. 259 of them contain no row from this import at all, and the largest
group is GotSport against SincSports at 187: the two providers hold the same NC
clubs under different naming conventions. These are candidates, not verified
duplicates.

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


## Outcome, 2026-09-16

166 merges applied in two batches (25, verified against the database, then 141), 0
failures. Live NC teams fell from 6,128 to 5,962. Every deprecated row is marked
deprecated and carries a `team_merge_map` row; no survivor was deprecated. The
doubled-fixture repair found nothing to exclude, which follows from the clusters
being selected for date-disjoint schedules.

### What the adversarial review removed

189 pairs entered review across four slices; 23 were removed and 3 had their
direction reversed.

| Removed | Why |
|---|---|
| 14 | Academy and MLS NEXT rows. The repo refuses this class for fuzzy merging and clustering on squad identity walked past that. 17 clubs field a U18 and a U19 side that both play the same MLS NEXT Cup window, so those are separate squads; a `<club>_U14_HD` id is a season slot rather than a squad. |
| 4 | A row naming only the club, merged into one of several squads that club fields. |
| 1 | `13 MLS Next AD` carries no club token, so every club's entry scores 1.0 against it. The pair would have fused Carolina Velocity FC into Carolina Core FC. |
| 1 | A U14 squad into a U13 squad, each of which already had its own counterpart. |
| 3 | Unresolved data defects: a survivor whose whole schedule sits two cohorts above its stored age, a stale `MLS_NEXT_AD` tag, and two colourless rows where the club fields Rise Black and Rise Gray. |

The 3 direction reversals all came from asking whether a row had ranking history
rather than how much: when both sides had some, the tiebreak kept the newer row.
One would have discarded 68 published ranking snapshots in favour of 12. The
final list discards the deeper history in no pair.

### Still open

- 99 clusters where neither row has a game. They look like duplicates and cannot
  be evidenced, so they need a person rather than a rule.
- 18 clusters holding contradicting fixtures on a shared date, and 15 where the two
  rows played each other. Those are correct refusals.
- The 23 removed above, each needing the specific decision named in its row.
- **A SincSports import on 2026-09-13 and 2026-09-14 created NC rows duplicating
  GotSport rows from 2025-11-04, which is where most of this came from.** Fixing
  that matcher stops new duplicates arriving; nothing here addresses it.
