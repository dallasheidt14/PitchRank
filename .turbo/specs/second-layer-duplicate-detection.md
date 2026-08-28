# Second-layer duplicate detection: two finders, one adjudicator

**Status**: design, awaiting approval · **Date**: 2026-08-27

## The problem in one sentence

Name similarity is currently the *only* doorway into duplicate detection, so the set of
pairs that can ever be considered is capped by the name scan's blocking key — and game
evidence, which is the part that actually decides correctly, never sees a pair the names
did not first nominate.

## What the current pipeline can reach

`find_fuzzy_duplicate_teams.py` (weekly Step 3, `FUZZY_AUTO_MERGE_ENABLED: 'false'`) can
only propose a pair when **all** of these hold:

| Constraint | Where | Effect |
|---|---|---|
| Same `(age_group, gender)` | fetch query, `:197-225` | cohort-scoped by design |
| Same `state_code` (NULL → `_no_state`) | `:244-247` | a CA row can never pair with a NULL-state row |
| Byte-identical `club_name` after lower/strip | `:264-268` | `Solar SC` != `Solar Soccer Club` |
| Same stored `age_group` | `:259-260` | no U18/U19 fold |
| `SequenceMatcher` ratio + boosts >= 0.90 | `:115-141` | stdlib, not rapidfuzz |

It reads `teams.team_name` and never `team_name_original`, never games, aliases, provider
ids, or dates.

`decide_team_merges.py` then judges from games, but inherits the same strictness as a hard
precondition: raw `club_name` compare (NULL fails against every real club), raw
`state_code` compare, and **any shared calendar date is an automatic REFUSE** — which is
exactly the signature of the double-import duplicate that all 639 merges on 2026-08-27
turned out to be.

## Measured gap

Fingerprinting every scored game since 2025-08-01 as
`(game_date, canon(opponent), own_score, opp_score)`, Modular11 excluded:

| | pairs |
|---|---:|
| Share >= 2 identical fixtures | 1,217 |
| — involve an `unknown_` placeholder | 1,049 |
| — named on both sides | 168 |
|   — of those, same `(age_group, gender)` | 117 |
|   — already reachable by today's scan | 51 |
|   — **new reach** (club or state differs) | **66** |

Separately, 399 pairs in the unfiltered set had played each other — the strongest available
distinctness signal, and free to compute.

## Design

Two independent finders, one adjudicator, and **agreement between the finders as its own
confidence signal**.

```
                 ┌─ Finder A: shared-fixture fingerprint (behavioural) ─┐
teams + games ──►│                                                      ├──► pair set
                 └─ Finder B: structured name match                    ─┘      │
                                                                               ▼
                                                 adjudicator (extended decide_team_merges)
                                                                               │
                                          Tier 1 both agree ─┬─ Tier 2 behavioural only
                                                             └─ Tier 3 name only
                                                                               │
                                                                               ▼
                                                        proposal file → apply_vetted_team_merges
```

### Finder A — behavioural (new)

`scripts/find_shared_fixture_duplicates.py`.

Generalise `build_regid_merges.py`, which currently exists **only** in a dead session's
scratchpad (`.../4294a591-.../scratchpad/build_regid_merges.py`, 232 lines, not in git).
Rescuing it into the repo is step zero.

Fingerprint each scored game as `(game_date, canon(opponent_id), own_score, opp_score)`,
both perspectives. Two teams that independently hold the same tuple under different game
rows are a candidate.

Changes from the placeholder-specific original:

- seed from all teams, not just `unknown_` rows — the index at its lines 135-145 is already
  an all-pairs generator
- drop the `provider_team_id < 3_000_000` target gate (rejects TGS/SincSports/PlayMetrics
  twins outright)
- replace `matched == total` with *count of shared fingerprints* plus share of the smaller
  schedule; `matched == total` is meaningless once both sides have full schedules, and it
  is why 280 pairs were held as "partial"
- `canon()` candidate keys before counting ambiguity (recovers some of the 27 held)
- exclude Modular11 on both sides and honour `games.is_excluded`
- **hard-exclude any pair that ever played each other**

### Finder B — structured name match

Widen reach; the scorer is not the bottleneck.

1. **Block on club first, in two passes.**

   **Pass 1 — `(club_name, age_group, gender, state_code)`.** Club replaces state as the
   primary pile key; state stays in the key. Club is compared byte-identically after
   lower/strip, exactly as today.

   **Pass 2 — the same key with `state_code` relaxed**, and *only* where the two club
   strings are byte-identical (case aside).

   Measured on 200,161 live teams. Piling by `(club, age_group, gender)` is 681,775
   comparisons, biggest pile 153; adding `state_code` back gives 602,696 and 144. State
   therefore costs ~12% of an already-small number and shrinks the worst pile by nine
   teams — it is doing no real work once club is the pile key. Both are far below today's
   76,020,942 comparisons over `(age_group, gender, state_code)` piles of up to 3,415,
   because today the club rule is applied *after* pairs are formed and so saves no work.

   Of the 117 same-cohort pairs that Finder A flags this season: 51 are reachable today
   (same club, same state), **17 are same-club-different-state** — Pass 2's target — and 49
   have genuinely different club strings.

   Pass 2 is deliberately narrow. Relaxing state *and* fuzzy-matching club names at the
   same time removes both guards against franchise clubs — Rush, Albion, Surf, Sting all
   run near-identically-named affiliates in many states, and state is what stops
   `ALBION SC Boulder County` merging into `ALBION SC San Diego`. Requiring byte-identical
   club strings keeps Pass 2 on the FC Delco shape (one club, rows stamped PA/NY/MD/NJ/OH
   by whichever event created them) and structurally excludes the franchise shape, whose
   club strings differ.

   The 49 differing-club pairs are **out of scope for this design**. They need real club
   canonicalisation (`club_normalizer.normalize_to_club` / `are_same_club`, 106 clubs /
   476 variations), which is where the franchise risk actually lives. Treat as a separate
   later pass with its own guards.
2. **Read `team_name_original` when present**, falling back to `team_name`. This restores
   gender and birth-year evidence and re-arms `birth_years_conflict`. Caveat: 90,032 live
   rows have that column NULL.
3. **Compare fields, not one string** — `(club, birth-year set, gender, distinction)` via
   `extract_distinctions` / `resolve_distinction` / `birth_years`, instead of one
   `SequenceMatcher` ratio over a laundered name.

### Adjudicator — extend `decide_team_merges.py`, do not rebuild

It already handles merge-map expansion, season dating, and the gender-column-vs-name
conflict. Fix the artifacts that refuse good pairs:

- club via `are_same_club`; NULL means *unknown*, not *mismatch*
- state demoted from precondition to weak signal
- same-day REFUSE **exempted when the shared date is itself a shared fingerprint** (same
  opponent, same score) — that is a double import, not two squads in two places
- filter to scored games before computing "played the same day" (today, two scheduled
  null-score fixtures trigger the refuse)
- fix the empty-shell branch, which tests only the deprecated side and so misses roughly
  half of true empty-shell duplicates on a coin-flip side assignment

### Combining rule — the actual second layer

Each pair records which finder(s) proposed it:

- **Tier 1 — both finders agree.** Names match *and* schedules overlap. Two independent
  signals; highest confidence.
- **Tier 2 — behavioural only.** Schedules overlap, names differ. Requires the name check
  to not *contradict* (different cohort, gender, or division tier = refuse).
- **Tier 3 — name only.** What runs today, unchanged in confidence.

This is the substantive change: names stop being the doorway and become a second
independent vote.

## Output

Proposal JSON in the shape `apply_vetted_team_merges.py` already consumes, plus a CSV for
eyeballing. Nothing merges automatically. The skill gains one step between its current
Steps 1 and 2.

## Risks and prerequisites

- `rapidfuzz` is in neither `requirements.txt` nor `requirements.lock`, and every import is
  try/except-guarded — CI and the GitHub Action silently run the `SequenceMatcher`
  fallback. Either add it or commit to stdlib.
- `normalize_team_names.py --all-teams` runs every Monday with no freeze flag and keeps
  laundering gender and bands out of `team_name`. Reading `team_name_original` is a
  workaround, not a fix.
- `backfill_team_distinction.py` (Step 1b) has failed silently on `import truststore` since
  2026-06-01, so `teams.distinction` is ~3 months stale — and no matcher reads it anyway.
- Blocking must move to club *before* state is relaxed. Deleting the state rule while
  leaving `(age_group, gender)` as the pile key takes the scan from 76 million comparisons
  to 1.2 billion, with a worst pile of 18,458 teams. Club-first blocking is what makes the
  relaxation affordable — and is 111x cheaper than what runs today.
- 15,046 live teams have no `club_name` at all and so cannot be piled by club under either
  pass. Finder A covers them instead, since it never reads a name.
- `revert_fuzzy_auto_merges.py` defaults `--merged-by` to `pitchrank-bot`, so it does not
  cover operator-applied merges unless the actor is passed explicitly.

## Out of scope

- Modular11 / MLS NEXT teams, per operator decision 2026-08-27.
- Pairs whose club strings genuinely differ (49 of the 117 evidenced pairs this season).
  These need club canonicalisation and carry the franchise-club risk; separate later pass.
- Re-enabling `FUZZY_AUTO_MERGE_ENABLED`.
- The Modular11 game mis-attribution found while measuring (U13 fixtures filed onto U14
  rows) — a separate import bug, worth its own backlog entry.
