# Step 3 replay — the guards on main do NOT close the failure modes

**Question asked:** replay the 1,772 merges of 2026-08-19 through `score_team_pair` as it
stands on `origin/main` (58fe03d68) and count how many still clear the 0.90 bar.

**Answer: 159.** Not zero. The guards block 91% of the incident, but what remains is not a
residue of the two known bugs — it is a set of *new* failure shapes, and at least 23 of the
159 are provably two different soccer teams.

Worse, the historical replay understates the live risk. A full dry run of the current code
across all 18 cohorts says Step 3 would auto-merge **916 pairs today**, and **11 of those
pairs are teams that have played each other**.

**Do not flip `FUZZY_AUTO_MERGE_ENABLED` on the strength of the existing guards.**

---

## 1. The replay

Method: `scripts/` and `src/` extracted from `origin/main` with `git archive` (content
verified identical to `git show origin/main:<path>`; the working tree was not used). Each
audit row's `deprecated_team_snapshot` supplies the deprecated side as it was at merge
time; the canonical side comes from `teams`. All 1,772 bot merges of 2026-08-19 carry a
snapshot, so none were dropped for missing data, and all 1,614 canonical ids resolved.

The replay runs the **whole production gauntlet in order**, not just the scorer:
stored-age-group equality → `score_team_pair` → `--min-score` → club equality →
`_should_skip_pair`. It uses **0.90**, which is what `data-hygiene-weekly.yml` actually
passes — not the script's 0.95 default.

| Gate | Blocked |
|---|---:|
| `is_placeholder_name` (the `unknown_NNNN` bug) | 918 |
| `birth_years_conflict` (the `2008` vs `2009` bug) | 662 |
| `has_protected_division` | 18 |
| stored `age_group` mismatch | 12 |
| `_should_skip_pair` | 3 |
| **still merges** | **159** |
| | **1,772** |

**Raising the threshold does not help.** Of the 159 survivors, 121 score exactly 1.000 and
only 11 score below 0.95. Moving `--min-score` from 0.90 to the script's 0.95 default
leaves 148 of them intact. The bar is not the problem.

### The 159 is robust to which names you use

The deprecated side comes from a snapshot, the canonical side from `teams` today, so the
obvious objection is name drift. It is real: **934 of the 1,772 deprecated teams have been
renamed since 2026-08-19**, almost all of them `unknown_NNNN` → a real name, by the
unknown-team-name backfill.

Re-running the entire replay with **today's** names on both sides returns **the same 159 —
and the identical set of pairs**, not merely the same count. Two things follow:

- The headline number does not depend on the snapshot choice, so the drift caveat is closed.
- **The backfill did not re-arm the placeholder failure mode.** All 918 pairs the
  `is_placeholder_name` guard blocked are still blocked today, now by
  `birth_years_conflict`, `_should_skip_pair`, or by scoring under 0.90 once they have real
  names. Zero of the 159 survivors come from that set. This was worth checking — giving 934
  previously-unnamed teams real names is exactly the kind of change that could have
  reopened the original incident, and it did not.

## 2. At least 23 of the 159 are provably different teams

Name similarity cannot separate a duplicate from two real squads, so the 159 pairs were
tested against game data instead (4,441 game rows across the 316 teams involved):

- **1 pair played each other.** `Corona U11 Urena` vs `Corona 2016 Urena`, 2026-05-03,
  2–3. Two rows cannot be one team if they met on the pitch.
- **22 pairs have same-day fixture conflicts** — each row played a *different* opponent on
  the same calendar date. A squad cannot be in two places.

That evidence was then checked for the obvious artefact, that the "different" opponents are
themselves one club under two rows. **21 of the 23 involve genuinely different opponent
clubs**; only 2 could be a duplicated-opponent artefact, and one of those has 10 separate
conflict dates.

Worst cases, all of which the current guards wave through:

| Score | Pair | Evidence |
|---:|---|---|
| 0.998 | `STA MOSC U19 DPL` → `STA MOSC 2009 DPL` | 15 conflicting dates, 20 vs 24 games |
| 0.950 | `West U19 NAL` → `West 2009 NAL` | 10 conflicting dates |
| 1.000 | `CFA OC SC U12 Miguel` → `CFA OC SC 2015 Miguel` | 7 conflicting dates, 21 vs 69 games |
| 1.000 | `ECNL RL G08/07` → `ECNL RL G08/07` (Slammers FC) | 6 conflicting dates, 47 vs 48 games |
| 0.998 | `Corona U11 Urena` → `Corona 2016 Urena` | played each other |

23 is a **floor, not a total** — it counts only pairs where the schedule proves distinctness.
114 of the 159 have games on both sides with no shared date at all, which is consistent with
a duplicate but does not establish one.

## 3. Why they get through: the guards read the wrong vocabulary

`birth_years()` returns an **empty set** for an age-label form. `birth_years_conflict` then
sees `{}` vs `{2009}`, finds no disagreement, and allows the pair. Meanwhile
`_should_skip_pair` canonicalizes `U19` and `2009` to the *same* cohort `u19` — correctly,
per the age chart — so it sees matching age tokens and no distinguishing squad word.
Both guards are individually right and jointly blind:

```
'STA MOSC U19 DPL' vs 'STA MOSC 2009 DPL'
    birth_years:  [] / [2009]      -> conflict=False   (empty set never disagrees)
    age_tokens:   ('u19',) / ('u19',)  -> skip=False    (canonicalization erases the difference)
    score: 0.998 -> MERGE
```

The same hole opens from the other side for two-digit forms: `birth_years` reads nothing
from `Select-09`, so `Select-09` vs `Select-07/08` also comes back "no conflict".

## 4. There is no single shape to patch

Classifying all 159 by the shape of the name difference, **proven-distinct pairs appear in
every shape**:

| Shape of the difference | Pairs | Proven distinct |
|---|---:|---:|
| age-label vs birth-year (`U12` vs `2015`) | 52 | 7 |
| byte/normalized-identical names | 44 | 8 |
| two-digit year form (`'09`, `-09`) | 27 | 3 |
| club-prefix restatement / other | 21 | 2 |
| band subset (`2016` vs `2016/17`) | 9 | 2 |
| age-label vs age-label (`U18` vs `U19`) | 3 | 1 |
| neither name states an age | 3 | 0 |

The 44 **byte-identical** pairs are the ones that settle the architecture question: two rows
both named `ECNL RL G08/07` in the same club, cohort and state, each with ~48 games and six
conflicting fixture dates. The names carry **zero** distinguishing information. No name-based
rule can ever separate them, because there is nothing there to read. Patching shapes one at a
time is how the first two bugs were found — after the fact, each time.

## 5. The discriminator that does work is behavioural, and it is exact

Splitting the 159 by what the *schedules* do:

| | Pairs | Proven distinct |
|---|---:|---:|
| one side has no games at all | 22 | 0 |
| game-date ranges are disjoint | 72 | 0 |
| ranges overlap, never the same date | 42 | 0 |
| **ranges overlap and share ≥1 game date** | **23** | **23** |

The set of pairs that share a game date is **exactly** the set of proven-distinct pairs —
23 = 23, with no exception in either direction. Every pair that shares a date turned out to
have a genuine conflict; no pair without a shared date shows any evidence of being two teams.

Note what this also explains: `SW U12 - SOCAL` vs `SW 2015 - SOCAL` has the same name shape
as the proven-bad `CFA OC SC U12 Miguel` pair, but its two date ranges do not touch
(2026-05→2026-11 vs 2024-11→2026-02). That is a club re-registering one squad under a new
naming convention — a genuine duplicate. **The name shape cannot tell those two situations
apart; the calendar can.**

### Proposed guard

> Before merging, refuse any pair where both teams have a game on the same calendar date.
> Send it to review instead.

On this dataset that blocks 23 of 23 proven-bad merges and costs 0 merges that show any
evidence of being duplicates — 136 of the 159 still merge automatically. It is one batched
query per candidate pair, and it is the only check tested here that works on the
byte-identical class.

A second, independent gate is available if a belt-and-braces setting is wanted: **only
auto-merge when the smaller side has ≤1 game.** That permits 47 of the 159 with zero proven
errors, and caps the damage of any mistake at one misattributed game. It is much more
conservative — it forgoes 112 probably-good merges — so it is the right setting only if
review capacity exists to absorb them.

### Implementation notes

- The insertion point is `run_fuzzy_duplicates()`, after `suggestions` is assembled and
  **before** the `auto_merge` branch — one batched fetch of `game_date` for every id in the
  suggestion list, then filter. It does not belong in `score_team_pair`, which is pure and
  is also imported by `revert_fuzzy_auto_merges.py`.
- Cost measured on the real 916: 1,832 team ids, ~37 batched `.in_()` queries of 50 ids each
  per side. Minutes, not hours, and it runs once per cohort loop rather than per pair.
- **`is_excluded` does not matter here** — recomputing all 155 live blocks while counting
  only non-excluded games returns the same 155. So the guard can ignore the flag, and no
  decision about excluded games is needed to ship it.
- What the guard does *not* claim: a shared game date is strong evidence of distinctness,
  but the absence of one is not evidence of duplication. It removes the demonstrable errors;
  it does not certify the remainder. That is why it should gate a review queue rather than
  license a broader auto-merge.

## 6. What Step 3 would do if the flag were flipped today

The replay is historical. The live number is the one that matters for the decision. Running
`run_fuzzy_duplicates()` from `origin/main` across the exact cohort loop the workflow uses
(`u10..u17, u19` × male/female) at `--min-score 0.90`:

| | |
|---|---:|
| team rows scanned across the 18 cohorts | 184,147 |
| **merges the current code would execute** | **916** |
| of those, the two teams **played each other** | **11** |
| of those, the two teams share a game date | **155** |
| would still auto-merge under the proposed guard | 761 |
| (memo) smaller side has ≤1 game — low-harm either way | 267 |

Per cohort the suggestions run 15–113, heaviest in `u19 female` (113), `u11 male` (110) and
`u12 male` (99).

**The eleven head-to-head pairs are the single most decision-relevant fact in this
document.** These are not judgement calls — two rows that met on the pitch cannot be one team:

| Score | Would merge | Into | Shared dates |
|---:|---|---|---:|
| 1.000 | `Academy ECNL 2013` | `Charlotte Soccer Academy - Charlotte SA ECNL 2013` | 10 |
| 0.928 | `NYSA B1607` | `NYSA B1611` (Oklahoma Celtic) | 7 |
| 1.000 | `U10 Premier` | `BU10 Premier` (Surf San Diego North) | 6 |
| 0.928 | `NYSA B1611` | `NYSA B1609` | 6 |
| 1.000 | `NYSA B1607` | `NYSA B1609` | 5 |
| 1.000 | `NYSA 1701` | `NYSA B1710` | 5 |
| 1.000 | `GLASA Tornadoes 2017` | `GLASA FC Tornadoes 17B` | 2 |
| 0.998 | `Corona U11 Urena` | `Corona 2016 Urena` | 1 |
| 1.000 | `Galaxy Boys 2017 Blue` | `Galaxy SC - 2017 Blue` | 1 |
| 1.000 | `BMT JR ACADEMY 2017G RED` | `Beaumont YSC - BMT JR Academy 2017 Red` | 1 |
| 1.000 | `Salzburg` | `Salzburg` | 1 |

Two of these deserve specific attention:

- `Academy ECNL 2013` → `Charlotte SA ECNL 2013` is the **bare-name vs club-prefixed-name**
  pattern — the exact case the tool's docstring cites as its reason to exist. Charlotte
  Soccer Academy fields two ECNL 2013 squads. The flagship pattern is not safe either.
- The **NYSA `B1607/B1609/B1611/B1710`** cluster is a seventh failure shape not present in
  the 2026-08-19 data: a club that distinguishes squads by a numeric suffix. `1607` is not
  in the `20\d\d` birth-year range, so `birth_years` reads nothing from either side and
  `birth_years_conflict` cannot fire. Four squads, mutually merging, three pairs of which
  have played each other.

Also newly visible in the live data and absent from the incident set: gender-letter
differences (`2017G` vs `2017`, `U10 Premier` vs `BU10 Premier`) and numeric squad suffixes
(`United FC 19` vs `United FC 18`). The list of shapes is still growing every time anyone
looks, which is §4's point restated with fresh data.

## 7. Answers to the handoff's open questions

**Q1 — do the guards close both failure modes?** They close the two they were written for
(1,580 of 1,772 blocked). They do not close the problem: 159 survive, ≥23 provably wrong.

**Q2 — what else clears 0.90?** Seven distinct shapes, listed in §4, with proven-distinct
pairs in all but the smallest. The two known shapes were about 89% of the 2026-08-19 damage
by volume but are not the mechanism that remains.

**Q3 — auto-merge or a review queue?** There is no merge review queue today — `team_merge_map`
and `team_merge_audit` are write-records, and `team_match_review_queue` is for provider→master
aliases, not team-to-team merges. Standing one up means a new table plus an operator surface;
`mission-control` has no merge UI. The §5 guard is the cheaper path to a safe re-enable and
does not need one.

**Q4 — what proves it is safe before the flag flips?** This replay is the harness. It is
reproducible: `scratchpad/replay_0819.py` + `evidence.py` reconstruct both sides from
`team_merge_audit` snapshots and score them against whatever the tree currently says. The
gate to propose is: **any change to the merge path must replay the 1,772 pairs and show zero
survivors that share a game date.** Today that number is 23.

## 8. Recommendation

1. **Leave `FUZZY_AUTO_MERGE_ENABLED: 'false'`.** Nothing found here argues for flipping it
   as the code stands.
2. **Add the shared-game-date guard** to `find_fuzzy_duplicate_teams.py`, behind
   `--dry-run` first.
3. **Re-run this replay** and require zero surviving shared-date pairs before the flag moves.
4. Do not chase the six name shapes individually. §4 is the evidence that that approach
   does not terminate.

---

## Reproduction

Scripts live in the session scratchpad
(`…/fc01ce18-…/scratchpad/`), all runnable standalone:

| File | What it does |
|---|---|
| `mainsrc/` | `scripts/` + `src/` extracted from `origin/main` @ 58fe03d68 |
| `replay_0819.py` | the replay; writes `replay_0819_results.json` |
| `replay_today.py` | the same replay on today's names — the drift control |
| `score_live.py` | applies the proposed guard to today's 916 suggestions |
| `evidence.py` | game-data evidence per surviving pair; writes `evidence_159.json` |
| `conflict_quality.py` | checks conflicts are not a duplicated-opponent artefact |
| `taxonomy.py` | the §4 shape classification |
| `mechanism.py` | the §3 guard-by-guard trace |
| `live_shard.py` | what Step 3 would suggest today, per cohort |

Caveats stated plainly: the canonical side of each pair is read from `teams` today rather
than from a snapshot, since only the deprecated side is snapshotted — but see §1, where
re-running the whole replay on today's names returns the identical 159 pairs, which closes
that objection. `same_day_conflicts` is evidence, not proof; §2 reports the
duplicated-opponent artefact check separately, and §5 states what the guard does not claim.

---

# Part 2 — Making Step 3 work

## 9. The rule set, and how it was tested

Rules that decide from **games** rather than names. Applied in order:

1. **Refuse** if the two records played each other, or both played on the same calendar day.
2. **Resolve age labels through the season they were played in**, then refuse on a birth-year
   conflict. `U12` alone names no cohort, but `U12 in the 2026-27 season` is the 2015 birth
   year — because the label moves every Aug 1 while a birth year does not. For a season
   starting in year `Y`, `U-N` means birth year `(Y+1) - N`, and U19 also covers `(Y+1)-18`.
3. **Review, never merge**, when one name gives a band and the other a single year
   (`MVP 2015 Grey` vs `MVP B15/16 Grey`). Clubs use both conventions for both situations.
4. **Merge** only on positive evidence: the two cohorts resolve to the *same* birth-year set
   AND either the seasons do not overlap (a re-registration) or the two records share ≥2
   opponents (one schedule split across two rows).
5. Everything else goes to **review**.

### Two assumptions in the first draft were wrong

- **"One side has no games, so merging is harmless" is false.** A merge deprecates the team
  row and repoints its provider alias, so a real team that simply has not been scraped yet
  stops existing and every *future* game lands on the other squad. The harm is not one
  misattributed game.
- **Equal birth years is not sufficient while both teams are live in the same season.** A
  club can field two 2015 squads in different flights — `Chicago MX FC U12` and
  `Chicago MX FC 2015` are both 2015 and both real.

### Measured against independent adjudication

136 of the surviving pairs were judged from game data by a separate pass that never saw
these rules, with every "different teams" verdict put through adversarial refutation
(10 of 11 survived). Scoring the rule variants against that ground truth:

| Rule set | Real teams destroyed | True duplicates merged |
|---|---:|---:|
| first draft (merge on ≤1 game, or equal cohort) | **3** | 84% |
| require positive evidence + exact cohort | 0 | 34% |
| **+ cross-provider zero-game shells (chosen)** | **0** | **36%** |
| + merge on a single shared opponent | 1 | 37% |
| + merge unknown cohorts with disjoint seasons | 2 | 42% |
| + merge any zero-game shell | 2 | 46% |

Safety and yield trade off directly, and the safe edge is ~36%. Caveat: 136 pairs is a
small sample and the ground truth is model-adjudicated, not human-confirmed — treat the
percentages as the shape of the curve, not precise rates.

## 10. What that does to today's 916

| | Count |
|---|---:|
| **Merge** — same cohort, seasons don't overlap (re-registration) | 210 |
| **Merge** — same cohort, ≥2 shared opponents | 8 |
| **Merge** — empty shell from a different provider | 2 |
| **Refuse** — played each other, or a game on the same day | 156 |
| **Refuse** — different birth years once labels are resolved | 27 |
| Review — cohort not determinable from either name | 246 |
| Review — same cohort and season, no shared opponents | 166 |
| Review — band vs single year | 101 |
| | **916** |

**220 merge, 183 refuse, 513 review.**

That is the honest shape of it: roughly a quarter of what Step 3 currently wants to do can
be done unattended and correctly. Not 916, and not the 507 an earlier draft of these rules
claimed — that draft destroyed teams.

The review pile is large enough that it, not the merging, is the real product decision.

---

# Part 3 — What was executed, and the follow-up fixes

## 11. Executed 2026-08-21

**295 team merges** applied via `scripts/apply_vetted_team_merges.py`, verified: 295 of 295
deprecated, canonical matches on 294 (the 295th is the Empire Surf chain, which correctly
cascaded past its intermediate row to the final survivor), **zero unintended deprecations**.
Log: `.turbo/step3/merge_results.json`. Audit: 295 `merge` + 4 `cascade_alias` rows under
`pitchrank-operator`.

**73 gender corrections** applied via `scripts/fix_gender_from_registered_name.py`
(50 Female→Male, 23 Male→Female), all verified. Log: `.turbo/step3/gender_fix_log.json`,
revertible with `--revert <log> --execute`.

**23 merges held back**, each for a stated reason: 3 upheld by adversarial review as genuinely
different teams, 7 band-vs-single-year pairs whose band was erased by name normalization,
5 rows already fusing 3+ registrations from one provider, and 8 found only by the
cross-cutting checks.

### Two mistakes worth recording

**The executor reported 295 failures for 295 successes.** PostgREST cannot serialise
`execute_team_merge`'s JSONB return and raises `JSON could not be generated` even when the
merge commits; the real payload sits inside the exception text.
`scripts/run_all_merges.py:270` already carries the workaround and the new script did not
reuse it. The danger was not the misreport but the log: it recorded every merge as failed, so
a revert driven by it would have been a silent no-op. Fixed, and the log is now rewritten from
verified database state rather than from the RPC's reply.

**Game counts were computed without merge resolution.** A row that is itself the canonical
target of an earlier merge reads as empty while holding inherited history. That is how
`idx297` nearly ran — its "empty" survivor already held 33 games from three prior B09 merges,
so merging Capital FC's 2008 ECNL team into it would have handed that identity to the club's
2009 squad. Recomputing all 319 through `team_merge_map` changed 13 pairs' counts; re-running
the same-day and head-to-head safety test on the corrected game sets still returned **zero**
failures, so the flaw was contained.

## 12. Two pipeline holes this exposed, both now fixed

### Merged teams stopped being scraped

`find_yesterday_null_score_teams` and `find_recently_active_teams` both match games by the raw
`team_id_master` on the game row and then require `teams.is_deprecated = false`. After a merge
neither side can satisfy both: the game still names the deprecated row, which is filtered out,
and the surviving team is named by no game. Since `execute_team_merge` never repoints games —
it only counts them — a merged team's unplayed fixtures silently stop being enqueued for a
score fill, and no other producer looks at NULL scores.

Measured after this batch: **348 NULL-score games stranded across 124 surviving teams, 291 of
them still upcoming.**

- Permanent fix: `supabase/migrations/20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql`
  resolves both RPCs through `team_merge_map`, using the idiom already in the rankings views.
  **Not yet applied** — direct Postgres is firewalled from this host and the MCP token is
  unauthorised, so it needs `supabase db push` or a manual apply plus a ledger repair.
- One-time repair: **done.** `scripts/enqueue_stranded_merge_fixtures.py --merged-by
  pitchrank-operator --since 2026-08-21 --execute` enqueued 94 teams covering 291 fixtures at
  priority 2. The script stays useful after any manual merge.

### Merged teams showed a blank rank chart

`ranking_history` is keyed by the raw `team_id` and a merge never rewrites those rows, so a
surviving team's own history stays filed under the ids it absorbed. **159 of the 295 survivors
had a blank chart**; the merge-aware read populates **144** of them and makes 19,092 more
history rows visible. The remaining 15 genuinely have no history.

Fixed in two readers, both now using the existing `resolveMergedTeamIds` helper rather than a
fourth hand-rolled resolution:
- `frontend/lib/api.ts` `getRankHistory`
- `frontend/app/api/insights/[teamId]/route.ts`

Both dedupe by snapshot date, preferring the canonical team's own row, because the weeks
before a merge hold one snapshot per team and a naive union double-plots them.
`tsc`, `eslint`, `prettier` and the full Vitest suite (56 files, 463 tests) all pass.

## 13. Still open

| Item | Notes |
|---|---|
| Apply the enqueue-RPC migration | Written, unapplied. Needs `supabase db push` + ledger repair |
| 23 held merges | Listed in §11; each needs a human call, not a rule |
| `SC Blues 2012 DPL` | 176 games = the club's DPL, ECNL and ECNL-RL squads fused at the **alias** layer, not by any merge. Violates the never-merge-across-tiers rule and its PowerScore is a blend of three squads |
| 729 rows with 3+ registrations from one provider | Database-wide. Sequential registrations are legitimate; concurrent ones are fusions. Not yet separated |
| 385 rows whose stored gender contradicts their registered name | 73 fixed; 286 rest on a bare B/G letter and 26 lack corroboration |
| Step 1 laundering | Normalization erases the band that distinguishes two squads. Any future band guard must read `team_name_original`, since Step 1 runs first in the same job |
| `pick_canonical_pair` | Ranks on name aesthetics. Do **not** change it to "more games wins" — measured, that doubles fixture stranding. Rank on live activity if it changes at all |
| Two copies of the canonical rule | `find_fuzzy_duplicate_teams.py:146` and `run_all_merges.py:127` must change together |
