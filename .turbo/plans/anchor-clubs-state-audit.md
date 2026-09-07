---
status: done
---

# Plan: Anchor every club against the registration record, then let the audit find the rest

Two new candidate selectors for `scripts/assign_team_states.py`, sharing the audit mode's
machinery, plus one new decision action. **Built, piloted and applied on 2026-09-02**; the
handoff `.turbo/handoff/2026-09-02-state-anchor-pilot.md` carries the results. The design
below is corrected where the pilot changed it, and marked where it was.

## Context

The sweep probes only teams a tier disputes, and 2.9% of the *undisputed* stated teams
(~5,000) carry a state their own GotSport record contradicts (measured 2026-08-31, report
`.turbo/reports/2026-08-31-targeting-the-gotsport-probe.md`). The contradiction audit
(`--audit-contradictions`) finds those for free — but only in clubs that already hold a
provider-confirmed anchor (`state_source = 'tier_a'`). Measured 2026-09-02 over live stated
teams with a GotSport id (178,482):

| | Clubs | Teams |
|---|---|---|
| Already anchored — the audit has checked every dissenter | 2,151 | 86,505 |
| **No confirmed team yet** | **4,775** | **75,536** |
| No club name, or the club's only team | — | 16,441 |

One probe per unanchored club anchors it. Every club-mate stored differently then becomes an
audit candidate, and the audit already probes only the dissenters. Cost ≈ 4,800 calls for the
anchors, then the dissenters, then ~16,400 for the unclubbed teams: about 25,000 calls in all
against ~171,000 for probing every team, at today's measured ~470 calls/min.

**The gap that makes this a code change and not a script:** a probe that *agrees* with the
stored state leaves no provenance. `apply_team_state` is only called for a changed state, and
`build_anchor_index` reads `state_source = 'tier_a'`. So a correctly-stored team the provider
confirms is, to the audit, indistinguishable from one never asked — an anchor probe that agrees
would anchor nothing. The ledger (`team_state_probe_log.agreed`) records it, but nothing reads
the ledger to build anchors. The fix is a `confirm` action that writes provenance without
changing the state.

The operator chose this plan over probing everything (2026-09-02), with a 5,000-call pilot
first.

## Design

### Selector 1 — `--anchor-clubs`

Population: every club key (`club_key`, so placeholders and empty names key to `""` and are
excluded) with **at least two** live stated teams, **no** team carrying `tier_a` provenance
(a club whose confirmed teams *disagree* is also skipped: that is a name collision, and
`build_anchor_index` already omits it — reuse the same reading), and at least one team with a
GotSport alias.

One team per club, chosen deterministically:

1. a team whose stored state is the club's modal stored state (`build_club_index`), then
2. not durably answered within the reprobe window (`fetch_recent_probes`) — so a club whose
   first pick returned `no association` gets a *different* team next run, then
3. lowest `team_id_master`.

A club with **three or more** durable non-answers in the window — or every aliased member
answering that way — is skipped and counted ("unanswerable"): the provider does not know this
club. Ordering for the budget:
clubs by team count descending, then club key — one call on a 40-team club covers forty.

Alias lookup happens *before* selection, over every stated team of every anchorable club
(`anchor_pool`) — the whole club rather than the first pick, so a team without a GotSport id
is passed over for a club-mate that has one instead of retiring the club. **As built:** the
map from that lookup is kept and the probe stage reuses it, so the lookup is bought once.
`probe_list` then applies recency and the budget exactly as the audit does. Both selectors
exclude a stored Canadian province, as the audit does. **As built:** one `stated_members`
grouping backs both selectors and keeps only askable teams, so an operator's own answer is
excluded alongside a stored province, and neither counts toward the two.

### Selector 2 — `--probe-unclubbed`

Population: live stated teams with a GotSport alias whose club key is `""` or whose club has
exactly one live team. Ordered by `team_id_master`. Recency and budget via `probe_list`.
Runs after the anchor pass and the audit; it is the tail that clubs cannot reach.

The two flags are mutually exclusive with each other and with `--audit-contradictions` and
`--no-tier-a` (same parser guard shape as today). `--probe-limit` and `--reprobe-after-days`
are accepted with either (today the parser refuses them outside the audit).

### The `confirm` action

In either new mode, after `decide` runs with the bought answers in hand: for each probed
candidate whose mapped answer equals its stored state, whose `state_source` is neither
`tier_a` nor `operator`, and whose `(team, state)` pair no operator has reverted, emit

```
{"action": "confirm", "tier": "A", "pre_image": <stored>, "proposed": <stored>,
 "confidence": 0.95, "reason": "provider confirms <stored>"}
```

`decide` itself is untouched — it returns `None` when nothing changes, which is right for a
sweep. The confirm is built beside the decisions in `build_snapshot`, only in the new modes.
**As built:** the confirm is built in every answered-only mode, the audit included — an
agreeing dissenter would otherwise stay a candidate and be re-bought when its window expired.

`apply_snapshot` applies a confirm through the existing `apply_decision` → `apply_team_state`
with `p_expected_state_code == p_state_code`. The RPC updates `state_source`,
`state_confidence`, `state_assigned_at` and returns true. **Corrected during the pilot:** the
ledger trigger's `WHEN` also covers `state_source`, `state_confidence` and
`state_assigned_at`, so a confirm *is* logged — and the ledger's action check refused it
(`team_state_audit_action_check`), stopping the first apply at its first confirm after the 16
corrections had landed. Migration `20260902210000_allow_confirm_in_team_state_audit.sql` adds
`confirm` to the list; a confirm row carries equal old and new states and the earlier
`old_source`, so `revert_team_states` undoes it cleanly. Confirms are **not** mirrored to the
rankings (state unchanged), not counted as applies in the report, and `--fills-only` withholds
them like any non-fill. `--limit` bounds them as a third outcome.

An answer of `AL` is R8b's unset default: it confirms nothing and corrects nothing on its own
unless the club agrees, exactly as `decide` already treats it — the confirm path must apply
the same test (`association_state == UNSET_DEFAULT_ASSOCIATION` and any local reading
disagrees → no confirm). A disagreeing answer flows through `decide` as a normal Tier A
correction with every existing hold (DC, reverted, province).

### Report

Mode line names the population and the spend the way the audit's does:
`N clubs can be anchored, K to probe, C already answered`, then a "passed over" line naming
why the rest were not asked (anchored, single team, no alias, unanswerable). **As built:** a
club asked through a club-mate is reported on its own line, confirms are reported on their
own line rather than a table column, and the snapshot carries `passed_over` and, for the
anchor mode, `club_sizes`. After
a run the operator measures "did it work" for free:

```
python scripts/assign_team_states.py --audit-contradictions --probe-limit 0 --out after.json
```

— the count of new contradiction candidates is the yield the anchors exposed.

## Files

- `scripts/assign_team_states.py` — as built: `anchorable_clubs(teams)`, `anchor_pool(clubs)`,
  `anchor_candidates(clubs, club_index, recent, aliased)`, `unclubbed_candidates(teams)`,
  `bought_answers`, `confirm_decisions(..., revert_blocks)`, one `elif answered_only:` branch
  in `build_snapshot` shared with the audit, `apply_snapshot` handling (confirms last, held
  to the revert ledger, provenance re-read before every write), parser flags and
  guards, `_summarize_answered` shared by the audit and verify reports.
  `CONFIRM_ACTION = "confirm"`, `ANCHOR_RETRY_CAP = 3`, `OPERATOR_SOURCE = "operator"`.
- `tests/unit/test_assign_team_states.py` — new sections driving the real functions through
  the existing `audit(...)` harness, which took a `mode` argument rather than being copied.
- `.claude/skills/assigning-team-states/SKILL.md` — a Step 2b: when to run each of the three
  probing modes, in order (anchor → audit → unclubbed), and that a confirm writes provenance
  and is ledgered under its own action (the "no ledger row" belief was wrong; see Design).
- `.claude/skills/assigning-team-states/references/evidence-tiers.md` — the "three things get
  a team probed" list becomes five.

## Implementation steps (TDD: each test first, red, then the code)

1. `anchor_candidates`: one team per club; anchored clubs excluded; mixed-confirmed clubs
   excluded; placeholder and empty clubs excluded; singletons excluded; modal-state team
   preferred; recently-answered team skipped in favour of the next; club skipped at three
   durable non-answers or once every aliased member has answered without a state; ordered by club size then key, deterministic on id.
2. `unclubbed_candidates`: empty-club and single-team-club teams only; stated only; ordered.
3. Confirm builder: agreeing mapped answer on a non-`tier_a` team → confirm; already `tier_a`
   → nothing; disagreeing → nothing here (decide handles it); `AL` with a dissenting local
   reading → nothing.
4. `build_snapshot` branch: `anchor_clubs`/`probe_unclubbed` params; `auditing`-style write
   scope (only probed-and-answered teams produce decisions); snapshot `mode` = `"anchor"` /
   `"unclubbed"`; `candidates_selected`, `probed`, `aliases_found`, `probes_answered`,
   `cached_answers`, `skipped_durable`, `budget_applied`, plus `passed_over` and (anchor
   mode) `club_sizes`; `probe_blocked` handling identical to audit (decide from cache,
   write, exit 1).
5. `apply_snapshot`: confirms applied via `apply_decision`, excluded from `to_mirror`,
   withheld by `--fills-only`, bounded by `--limit`; the console line reports them separately.
6. Parser: the two flags, exclusivity guards, `--probe-limit` / `--reprobe-after-days`
   accepted with them; each guard testable before the credential check (the existing argv
   harness).
7. Summary: mode line, the "passed over" line, and a confirms line.
8. Skill prose (Step 2b, evidence-tiers list).

## Verification

- `python -m pytest tests/unit/test_assign_team_states.py -q` — new cases pass; each
  selector guard fails when its clause is deleted against a scratch copy.
- `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` — clean.
- `python scripts/check_state_skill_assumptions.py` — every assertion holds.
- Free end-to-end: `--anchor-clubs --probe-limit 0 --out x.json` prints the population and
  selects nothing; `--probe-unclubbed --probe-limit 0` likewise.
- **Pilot** (operator-run, paid): `--anchor-clubs --probe-limit 5000 --out anchors.json`, then
  `hold_unsafe_state_applies.py`, `--execute --limit 50`, read the batch in
  `team_state_audit`, apply the rest. Then `--audit-contradictions --probe-limit 0` to count
  what the anchors exposed, and report that number: it is the pilot's result.

## Coordination

`C:/pitchrank-state-converge` holds staged edits to `decide`, `build_snapshot` (an
`approved_states` argument and a `rules` field) and `apply_snapshot` (a rules-version
refusal). This plan adds a sibling branch in `build_snapshot` and a new action in
`apply_snapshot`, so the merge will conflict in those two functions and nowhere else. Whichever
lands second resolves by keeping both: the `rules` constant should then be bumped, since a
snapshot carrying confirms is a new shape.
