# Stabilizing the `unknown_<provider_team_id>` problem

**Written:** 2026-08-19 · **Status:** phases 0–1 done, 2 open

## The one-paragraph version

The weekly unknown-opponent job creates teams named `unknown_<provider_team_id>` because
its GotSport name lookup gets blocked by CloudFront and the block is recorded as "this
team has no name." There are 30,091 of them. They are real teams and should exist — the
defect is that they arrive nameless, and that **every system that matches teams by name
treats them as meaningful**. That second half is what actually caused damage: 3,708 wrong
merges since March, all now reverted.

The strategy is not to prevent placeholders. Bulk-resolving ~10,000 names inside a weekly
job is precisely what the WAF exists to stop. The strategy is: **let them be created, name
them quickly on a paced cron, and make every name-matching system refuse to act on them.**

---

## Where things stand

| | Count |
|---|---|
| Live placeholders | **30,091** |
| Resolvable (May 2026 onward, 6-digit IDs) | **25,677** |
| Dead (pre-May, 7-digit IDs, permanent 404) | **4,414** |
| Wrong merges reverted | 3,708 |
| Drain rate | 7,200/day |

Merged today: #963 (age job off), #964 (backfill + cron), #965 (CI deps), #966 (stop
discarding fetched names), #968 (15 gender fixes), #969 (merge job off), #970 (revert).

Open: **#971** (cron window), **#972** (scoring guard).

Two jobs are gated off and must stay off until their phase completes:
`AGE_DERIVATION_ENABLED=false`, `FUZZY_AUTO_MERGE_ENABLED=false`.

---

## Phase 0 — Containment ✅

Both destructive jobs gated, all 3,708 bad merges reverted, backfill cron live and proven
to run from GitHub without ZenRows.

## Phase 1 — Stop the bleeding ✅ (pending merge)

**#971 — point the cron at every resolvable placeholder.** A scheduled run passes no
`created_after`, so the script default applied and the job only saw teams created on/after
2026-08-04 — 12,252 of 30,091. It would have drained that window, gone quiet, and left
13,445 resolvable teams looking done. Moves the default to 2026-05-01, the boundary where
the dead 7-digit ID space ends.

**#972 — refuse to score placeholders and mismatched birth years.** Two guards in
`score_team_pair`. Closes the class of failure that caused every wrong merge. Verified by
diffing old vs new scoring: only the two bad shapes change.

**Do:** merge both. No further action needed.

---

## Phase 2 — Drain the backlog

25,677 resolvable at 7,200/day ≈ **3½ days**, unattended, once #971 lands.

**Verify at the halfway mark** rather than waiting for it to finish:

```bash
python scripts/backfill_unknown_team_names.py --dry-run --limit 5
```

Watch for `Skipped (API/DB error)` climbing above zero — that is the WAF, and the breaker
will pause and retry, but a sustained non-zero means the 12s pacing needs raising.

**Exit condition:** live placeholders created on/after 2026-05-01 reaches ~0.

---

## Phase 3 — Let the cron go quiet

The 4,414 dead IDs return `404 Can not find team` permanently. Once the resolvable ones are
drained they become the entire work-list, and the job grinds them forever without the
summary ever changing.

**Do:**
1. Add a `resolution_attempted_at` (or `unresolvable_at`) column to `teams` — needs a
   migration, so it is the only phase here with a schema change.
2. Set it on 404 in `backfill_unknown_team_names.py`; exclude those rows from the fetch.
3. Confirm a run with nothing to do exits reporting zero rather than 75 × 404.

**Why not sooner:** it only matters once phase 2 is finished, and a migration during
active remediation adds risk for no benefit.

**Open question for you:** those 4,414 teams can never be named from GotSport. Options are
to leave them, name them from an alternate source, or retire them. Worth deciding
separately — they carry games, so deletion is not obviously safe.

---

## Phase 4 — Re-enable the merge job

**Do not flip `FUZZY_AUTO_MERGE_ENABLED` until #972 is merged and phase 2 is done.**

1. Dry-run a few cohorts, u19 female first since it was worst:
   ```bash
   python scripts/find_fuzzy_duplicate_teams.py --age-group u19 --gender female --dry-run --min-score 0.90
   ```
2. Expect the suggestion count to collapse from 780 to a small number. If it does not,
   there is a third failure shape and it needs finding before the job runs again.
3. Review the surviving suggestions by hand. They should be genuine formatting duplicates.
4. Flip the flag.

**Consider while here:** the job auto-merges at 0.90 with no human gate, and
`confidence_score` was written as `0.0` on all 1,772 rows — so the score that justified each
merge was not recorded, which made the forensics harder than it should have been. Both worth
revisiting.

---

## Phase 5 — Residue

Small, independent, no ordering constraint.

- **263 merges moved more than one alias.** Only the alias games route through was
  repointed; extras remain on the canonical. Identifiable via `aliases_updated` in
  `team_merge_audit`.
- **3 placeholder→real merges left unreverted.** `unknown_720829` → "AV Navy";
  `unknown_757360` and `unknown_757363` both → "OVF Alliance Azul" — both cannot be right.
  #972 blocks this shape going forward.
- **Six copies of the GotSport resolver.** Five read `full_name`, `state`, `age`, `gender` —
  keys the API does not return. That is the original cause of all 30,091 placeholders.
  Consolidating onto one resolver on the WAF-aware transport would retire the root cause.

---

## Phase 6 — The age-group question (unresolved, blocking)

`AGE_DERIVATION_ENABLED` is off because `fix_team_age_groups.py` computes
`CURRENT_YEAR - birth_year + 1`, which cannot be right under Aug 1 – Jul 31 banding: one
birth year spans two cohorts, and PitchRank stores birth *years*, never birth *dates*.

**This is not an implementation task — it needs a decision on what determines a team's age
group.** Nothing else in this plan depends on it, and the job is safely off.

What is known:
- The Aug 2026 rollover migration **did** run (backup tables present, no `u18` survivors).
  Pre-Aug-1 teams match the 2026-27 mapping at 100.0%.
- GotSport's `display_age_group` is not usable as truth — two different `2014` teams
  returned `U14` and `U12`.
- Dual-year names (`B2016/17`) look like band labels and may be the best available signal,
  but that reverses the "always take the older cohort" rule from 2026-05-01, and names like
  `Illinois FC 2016-2018` and `U13/12 Boys` show the format is not reliable.

Do not write `age_group` from any source until this is settled.

---

## Order of operations

```
merge #971, #972                    ← today
  └─ phase 2: drain ~3½ days        ← unattended, spot-check at halfway
       └─ phase 3: 404 marking      ← needs a migration
            └─ phase 4: re-enable merge job, u19F dry run first
phase 5 residue                     ← anytime, independent
phase 6 age decision                ← blocked on you, blocks nothing else
```

## Invariants

1. `FUZZY_AUTO_MERGE_ENABLED` stays `false` until #972 is merged **and** a u19-female dry
   run comes back sane.
2. `AGE_DERIVATION_ENABLED` stays `false` until phase 6 is decided.
3. Nothing writes `teams.age_group` from a name or from GotSport in the meantime.
4. The backfill writes `team_name` and `club_name` only.
5. Any new team-matching code rejects placeholder names — `_is_placeholder_team` in
   `src/tournaments/triage.py` is the canonical predicate.
