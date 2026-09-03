# Handoff: state-code audit 2026-09-02 — the anchor pilot, and what it found

## Where to work

`C:/pitchrank-state-audit` — a worktree on branch `state-audit-2026-09-02`, cut from
`origin/main` at `968f81215` (#1080). **Nothing is committed yet.** It holds:

- `scripts/assign_team_states.py` — two new probing modes, `--anchor-clubs` and
  `--probe-unclubbed`, and the `confirm` action (plan: `.turbo/plans/anchor-clubs-state-audit.md`)
- `scripts/hold_unsafe_state_applies.py` — the operator-side split of a snapshot into safe and
  held applies, with `tests/unit/test_hold_unsafe_state_applies.py`
- `supabase/migrations/20260902210000_allow_confirm_in_team_state_audit.sql` — **applied to
  production by the operator 2026-09-02 ~21:05 UTC and recorded in `schema_migrations`**
- skill prose (`.claude/skills/assigning-team-states/`), `check_state_skill_assumptions.py`
  figures, backlog IMP-161..166 (IMP-154 and IMP-160 closed), this handoff, and 70-odd new
  unit tests

It has no `.env`. Source credentials per command:
`set -a && . /c/PitchRank/.env && set +a`. The ZenRows key is a process environment variable.

**Do not use `C:/PitchRank`** (another session's branch, PR #1071, with an uncommitted edit
that refuses a branch switch). **`C:/pitchrank-state-converge`** holds someone's staged,
uncommitted edits to the same script — an authority test in `decide` and a snapshot
rule-version refusal. This branch touches `build_snapshot` and `apply_snapshot` too; whichever
lands second resolves the conflict by keeping both, and should bump their `SNAPSHOT_RULES`
constant since a snapshot carrying confirms is a new shape.

## What the pilot was

The operator's question: audit every team that *already has* a state, not only the ones a
tier disputes. Only the GotSport registration record can answer that, one paid call per team,
and 2.9% of undisputed teams (~5,000) carry a state it would contradict. Probing all 178,482
checkable teams is ~171,000 calls. The plan chosen instead: buy one anchor per club the
provider has never confirmed, and let the existing contradiction audit — which selects a
club's dissenters for free — do the finding. Budget for the pilot: 5,000 calls.

## What it found

| Step | Paid calls | Result |
|---|---|---|
| Free rehearsal (`--probe-limit 0`) | 0 | 4,635 clubs anchorable; 216 already answered in the ledger; 16,700 unclubbed teams, 586 answered |
| **Anchor pass** `--anchor-clubs --probe-limit 2500` | 2,500 | 2,339 answered. **2,519 confirms** (the modal-state team was right), 16 Tier A corrections, 14 queued |
| Free count after anchoring | 0 | audit population **2,182 → 5,005**; anchored clubs 2,368 → 4,943 |
| **Contradiction audit** `--probe-limit 2500` | 2,500 | 2,301 answered. Provider disagreed on **1,567 of 2,670** answered — 80.8% where 2+ club-mates anchor, 48.9% under one anchor. **1,486 corrections applied**, 81 queued |
| Unclubbed rehearsal's cached answers | 0 | 146 confirms, 5 queued |

**About 300 corrections per thousand paid calls**, against 29 for random probing (a
disagreement rate the tool computes; the hand-checked rate is Step 2a's).
The corrections read like a gazetteer: Fort Wayne to Indiana, Reno to Nevada, Kittery to
Maine, Little Rock to Arkansas, Lake Oswego to Oregon. Two batches of 50 were read by hand
against `team_state_audit` and every one placed; the remaining rows were applied from the
same snapshots, actor `assign_team_states`, windows **20:53–21:12** (anchor) and **21:21–21:30**
(audit) UTC. `revert_team_states` undoes either by actor and window; a `confirm` row reverts
to its earlier provenance with the state untouched.

## What the review changed after the pilot

The finalize review found, and this branch fixes: a disputed
`AL` answer could authorise a club-derived correction in the new modes (now queued; only
Tier A decisions and confirms apply there); confirms ignored the revert ledger and could
overwrite an operator's `--set` (both gated now, at decision time and at apply time); the
new selectors probed stored Canadian provinces and counted `no gotsport alias` rows toward
the retry cap (excluded); a Tier B apply could overwrite a confirm that landed between the
hold script's read and the replay (apply_snapshot re-reads provenance for every non-A write
and skips one outranked since the snapshot); SKILL.md Step 5 told the operator to replay the
unsplit file (it now says the split one); and `hold_unsafe_state_applies.py` never loaded the
env its docstring promised (it imports the tool's readers now). The two population branches
of `build_snapshot` and the two reports were merged into one each. The review also found the
provenance re-read exempting Tier A entirely, so an operator's `--set` could be overwritten
by a registration answer (one `outranked` rule now, at every gate including `--team
--execute`, and operator-set teams are never bought); the two selectors counting a club's
size differently, so a border club's US team fell through both (one `stated_members`
grouping); a `no gotsport alias` team pickable but unprobeable (excluded from the pick); a
cached Alabama default treated as an anchor (it is not); and the confirm phase reading the
ledger too early (it reads again just before writing).

## What went wrong, and is fixed

**The ledger refused the first confirm.** The plan assumed the trigger fires only on a state
change; it fires on any provenance change, so a confirm is logged — correctly — and the
action check did not know the word. The first apply stopped at its first confirm, *after* the
16 corrections had landed and *before* the queue rows and the board mirror, so 13 ranked teams
sat on the wrong board for ten minutes. Three fixes: the migration above; confirms now run
**last** in `apply_snapshot` so nothing can strand above them (test pins the order); and a
replay skips a confirm whose team already carries `tier_a`, so Step 4's batch-then-rest no
longer stamps the first batch twice (the anchor apply did, before that fix: 50 teams carry two
confirm rows, harmless).

## The database at the end of the day (22:05 UTC)

| | This morning (19:34) | End of day |
|---|---|---|
| Live teams | 204,798 | 204,798 |
| With a state | 201,609 | 202,412 (98.8%) |
| Provider-confirmed (`tier_a`) | 6,423 | **14,333** |
| Corrections written by the tool today | — | **2,990** |
| Teams confirmed by the provider today | 0 | 4,184 (the first 50 carry two ledger rows) |
| Paid GotSport calls today | — | 11,242 |
| Review queue pending | 1,940 | 2,016 |
| Audit population (contradicts a confirmed club-mate) | 2,182 | 1,558 — **all answered**, 0 left to probe |

After the pilot the operator approved finishing the population: the uncapped audit (1,566
calls → 985 corrections), the remaining 2,093 anchorable clubs (2,073 calls → 1,519 confirms,
77 corrections), and the last 183 dissenters (146 corrections). Every batch was read by hand
at 50 before the rest was applied. Actor `assign_team_states`, windows 20:04–22:05 UTC.

Measure it again with:

```sql
SELECT count(*) FILTER (WHERE state_source = 'tier_a') AS provider_confirmed,
       count(*) FILTER (WHERE state_code IS NULL)     AS blank,
       count(*)                                        AS live
FROM teams WHERE coalesce(is_deprecated, false) = false;
SELECT count(*) FROM team_state_review_queue WHERE status = 'pending';
```

## What is left, in order

1. **The audit population is drained.** 1,558 teams contradict a confirmed club-mate; 1,243
   are answered and 315 answered without a state, so nothing is left to probe. What remains
   in that pool is the 111 queued holds (DC, reported values, reverted values) and dissent
   the provider says is legitimate — 1,131 teams whose cached answer the next
   `--audit-contradictions` run writes as a confirm at no cost, so they leave the pool. The
   population regrows only when a new anchor lands.
2. **947 anchorable clubs remain** (6,973 teams): the ones the two passes today could not
   ask — no GotSport id on any member, or answered without a state. `--anchor-clubs` will
   pick a different club-mate next run and retire the rest at three silent answers, or sooner
   once every aliased member has answered that way.
3. **The unclubbed tail**: `--probe-unclubbed`, 16,455 teams of which 15,628 carry a GotSport
   id and 586 are already answered. Base rate applies (~3%), so ~450 corrections for ~15,000
   calls — do it once, in chunks of `--probe-limit 5000`.
4. **The review queue**, now ~2,000 pending: `queue_pending.csv` in the scratchpad has the
   shapes; the R9 "confirm-current" false friends want rejecting, the placeholder-club fills
   approving by hand, and the seven DC rows want the DC policy decided once.
5. **The held teams**: 16 flip-flops (`sweep_tier_a_held.json`) and 8 by hand
   (`sweep_tier_a_held_by_hand.json`) — foreign clubs and a Québec team the map cannot read
   (IMP-163, IMP-164).

Everything after step 1 is cheaper per correction than it was this morning and will stay so:
each anchor exposes its dissenters, and each correction is a new anchor.

## Backlog entries from this session

IMP-161 Tier B two-and-two swap · IMP-162 stale full-name `state` column · IMP-163 non-US
clubs on state boards · IMP-164 the association map cannot read a Canadian province (83 + 71
such answers today, all discarded) · IMP-165 a queue-approved value is not protected by the
provenance gate · IMP-166 a cached answer is not bound to the alias it came through. Closed on
this branch: IMP-154 (ordered paged reads) and IMP-160 (the hand-set prints are escaped).

## Next concrete action

`/finalize` this worktree: the suite is green (3,152 + new tests), lint is clean on the CI
path list, `check_state_skill_assumptions.py` holds on every assertion. Open the PR, run
`scripts/pr_wait.py`, then remove the worktree. Then step 1 above.
