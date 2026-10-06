# Modular11 EA v2 — Season-Keyed IDs, Clean Before Matching, a Better Matcher

**Date:** 2026-10-06
**Status:** Draft (pending user review)
**Slug:** `modular11-ea-v2`
**Builds on:** `.turbo/specs/modular11-ea-scraper.md` (step 1) and
`.turbo/specs/modular11-ea-import.md` (step 2), both on branch `feat/ea-scraper`.

## Why

The U17 run showed the step-1 match report is not good enough to import from:

- Of 90 "needs review" teams, 27 were really duplicate copies of one squad already in PitchRank
  (e.g. California Football Academy held 3 times).
- 4 were `EA1` names the matcher did not read as EA.
- A shortcut pick linked Albion SC **Santa Ana** to an Albion SC **Santa Monica** team. It was
  caught and undone.
- Club branches (TFA OC vs SGV, LA Surf LC vs LA Surf Futures, Atlanta vs Atlanta Metro) pass the
  club-name comparison.

The user decided (2026-10-06): "we need to improve the matcher and utilize the
/merging-duplicate-teams and /assigning-team-states skills to help with the state code first so
its easier to match before we even think about importing."

## Finding that changes the identity model (verified 2026-10-06)

**An EA team id is an age slot, not a squad.** Ids 7155 and 7343 were U13 in 2025-26 and are U13
in 2026-27, and id 3432 (California Football Academy) was U17 in both seasons, each with a full
season of games under the same id. Each Aug 1 the slot gets a new cohort. So a link from
`3432` to a PitchRank team is right for one season only. The next season's games would land on
the wrong cohort, which is the same trap the MLS NEXT `{club}_U{age}` ids hit at this year's
rollover.

## Design

### 1. Season-keyed EA ids

- Every EA id PitchRank stores becomes `<UID_team>:<season start year>`, e.g. `3432:2026` for the
  2026-27 season. This applies to `team_alias_map.provider_team_id` and
  `teams.provider_team_id` for `modular11_ea` rows, and to the importer CSV's `team_id`.
- The scraper keeps writing the raw id plus the season in `teams.csv`, and the key is built in
  one place (`ea_key(uid, season)`).
- **Migrating what exists:** a one-off, logged, reversible script rewrites the 98 current U17
  aliases and the 36 created teams' `provider_team_id` from `3432` to `3432:2026`. Game rows keep
  the raw provider ids they were imported with, because games are immutable and they already
  resolve to the right teams.
- **Next season:** `3432:2027` is a new key and is matched fresh. Lineage is a strong signal: the
  team linked to the club's U16 slot in 2026 (`<u16 uid>:2026`) is the expected match for the U17
  slot in 2027.

### 2. Clean before matching, per age group

For the age being processed, take the **candidate pool**: every live PitchRank team of the same
age and gender whose club could match any EA club in that age's roster (the matcher's club test,
section 3).

1. **Duplicates:** run the `merging-duplicate-teams` skill on the candidate pool, using its
   cross-provider (Doorway C) and squad-key (Doorway D) detectors scoped to these clubs. Then run
   its full review (adversarial reviewers), its owner review page for held pairs, and its apply,
   verify and doubled-game steps. Nothing merges without the skill's gates.
2. **States:** run the `assigning-team-states` skill (dry run → hold split → apply → verify) and
   apply only to candidate-pool teams. Teams it cannot decide are listed for the owner, who has
   already answered in this format.
3. Re-run the match report on the cleaned pool.

### 3. The improved matcher (`match_modular11_ea_teams.py`)

- **Tier markers:** `EA` and `EA1` are EA; `EA2` is EA2. A `|`-separated or `(EA)` form is still
  read. National is never a marker.
- **Branch-safe club test.** A candidate's club must be the EA club itself, not a sibling branch.
  Accept when the normalised `club_name` equals the EA club, or the team name starts with the EA
  club followed by an age token (already built). Do not accept a `are_same_club` match whose extra
  words name a different place or sub-site (Santa Ana ≠ Santa Monica, OC ≠ SGV, `EC`, Metro,
  Futures). Such pairs go to review with the reason "different branch".
- **State agreement.** Each EA region maps to its allowed states (e.g. LA North → CA, PACNW →
  WA/OR/ID, Texas → TX). The table covers all 19 regions on the EA page; the owner checks it once
  before it is used. A candidate whose state contradicts the region is not a candidate. A
  candidate with no state cannot be confident (which is why section 2 comes first).
- **One team, one EA team.** Within an age, a PitchRank team may be claimed by only one EA team.
  This is solved as an assignment over all claims, not team by team, and a contested team goes to
  review.
- **Qualifiers mean a different squad.** A candidate whose name carries a coach surname, a colour,
  a Roman numeral or a letter squad mark that the EA team's own name does not carry cannot be
  confident.
- **Schedule evidence** (tie-breaker and safety check, no single game decides):
  - a candidate that has played the EA team's sibling squad (same club, same age) is that sibling,
    not this team;
  - a candidate that played on the same date as one of the EA team's league games against a
    different opponent is a different squad.
- **Lineage** (from the second season on): the team linked to the club's age-below slot last
  season is the leading candidate.
- **Buckets** stay `confident`, `review` and `no_match`, each with a reason a person can read.

### 4. Import, unchanged in shape

The step-2 linker, builder and alias-only matcher stay as they are, keyed by season. The owner
reviews the U17-style spreadsheet and the impact numbers, and approves each age before
`--execute`.

## Order of work

1. Season keys, including migrating the U17 data already in.
2. The matcher improvements, with tests built from this week's real failures: Santa Ana/Santa
   Monica, TFA OC/SGV, LA Surf LC/Futures, Atlanta/Atlanta Metro, San Diego/San Diego EC, `EA1`,
   California Football Academy ×3, BVBIA Arizona Ramirez/Romero.
3. A cleanup runner that produces the candidate pool and hands it to the two skills, one age at
   a time.
4. Re-run U17 end to end (the 67 still undecided), then U16 as the first age done the new way.

## Out of scope

- MLS NEXT (`modular11`) and its rollover.
- Scheduling the EA Scraper workflow (it stays manual).
- Writing the skills' own rules. The runner calls them; it does not change them.

## Success measure

On U16, the first age run fresh under v2: no confident link that a person rejects on reading, no
two EA teams claiming one PitchRank team, and fewer than a third of teams left for review. U17
needed 90 of 167 reviewed.
