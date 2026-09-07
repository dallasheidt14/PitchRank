# Handoff: Fill-only state automation, and what corrections need first

## What this is

Making team-state maintenance run itself, or as much of it as is safe. The cleanup is done
(see `.turbo/handoff/2026-08-29-team-state-assignment.md`): four PRs merged, three
migrations applied, ~7,950 logged writes, 98.8% of live teams carrying a state and the
state boards in sync. What is not done is keeping it that way without a person.

**Read the prior handoff first.** This one assumes it.

## The finding that shapes everything here

**Fills are safe to automate. Corrections are not, and there is evidence, not a hunch.**

Run the sweep's dry run twice in a row and the second pass proposes 664 applies, **90 of
which overwrite what the first pass just wrote**. Two of them are a straight oscillation:

    Femac 2006      pass 1 wrote NV, pass 2 wants WA
    FEMAC 2009 JA   pass 1 wrote WA, pass 2 wants NV

Same club, each write flipping the club majority and dragging the other team back. Eight of
the ten sampled were **Tier B trying to overwrite Tier A** — the club count overruling a
per-team provider record, because the sweep changed the club distributions Tier B reads.

A weekly unattended corrector would run that forever. A fill cannot do it: nothing is
overwritten, and the worst case is a wrong state on a team that had none — visible, logged,
reversible.

Reproduce with:

    python scripts/assign_team_states.py --no-tier-a --out pass1.json
    python scripts/assign_team_states.py --no-tier-a --out pass2.json
    # then compare: decisions in pass2 whose team_id appears in pass1's applies

## Job one: the fill-only job

`scripts/assign_team_states.py` already has the tiers, the snapshot gate, the ledger and the
queue. It needs:

1. **`--fills-only`** — apply decisions whose `pre_image is None`, and queue everything else
   exactly as today. One filter in `apply_snapshot`, plus the flag.
2. **A workflow** modelled on `refresh-team-scrape-activity.yml`: dry run to a snapshot,
   then `--execute --snapshot <file> --fills-only`. It must NOT pass `--no-tier-a` blindly —
   read the Tier A note below.
3. **A test** that a correction is never applied under the flag, driving the real
   `apply_snapshot` the way `tests/unit/test_assign_team_states.py` already drives `decide`.

Volume: roughly 40 new blanks a day, ~500 fills on a first run.

**Tier A costs money.** The GotSport probe is ~6,200 paid ZenRows requests per full run and
is spent at snapshot time. For a fills-only job it is close to worthless — Tier A almost
never fills (0 of 617 fills in the 2026-08-30 sweep; it decides corrections). Run the
scheduled job with `--no-tier-a` and keep the paid probe for operator-run sweeps.

## Job two: make corrections converge

Two rules, both small, both testable by the pass-2 comparison above:

1. **Never let a lower tier overwrite a higher one's recorded source.** `teams.state_source`
   already records which tier wrote a value, so Tier B proposing over a `tier_a` row is
   detectable at decision time. This alone kills eight of the ten sampled rewrites.
2. **Never re-decide a team this tool wrote in the same pass.** The snapshot already knows
   what it wrote.

**Done means:** pass 2 proposes zero rewrites of pass 1's applies. Until it does, corrections
stay operator-run through the `assigning-team-states` skill.

## In flight

**PR #1063 — `tgs-autocreate-state`, open, one review round applied, branch checked out.**
Makes the TGS matcher set a state at creation from the club, when every stated team of that
club agrees. Lifts `_resolve_state_from_club` from `PlayMetricsGameMatcher` to
`GameHistoryMatcher` so there is one implementation. 2,941 tests pass, lint clean, seven
tests in `tests/unit/test_autocreate_state_from_club.py`.

Codex found two, both applied in `8c6320d41`:

1. **The unanimity check paged the club.** It fetched up to 500 rows and deduped; the
   largest club here has 532 stated teams, so a multi-state club read as unanimous whenever
   its minority fell outside an unordered page. It now reads one stated team and asks
   whether any team of that club names a different state — exact at any size.
2. **Creation must not write the full-name `state` column.** `assign_team_states` reads a
   filled one as "a provider reported this" and then refuses to correct it without a
   per-team record. A club-inferred state is precisely what the sweep should stay free to
   correct. **`PlayMetricsGameMatcher` still writes both on its own create path and has the
   same collision** — untouched here, worth its own look.

Not yet re-reviewed after those fixes.

Measured effect, against the 1,040 stateless TGS teams created in the ten days to 08-31:

| | Teams | |
|---|---|---|
| Resolved by the fix | 604 | 58% |
| Club spans states → still NULL | 352 | 34% |
| Brand-new club → still NULL | 84 | 8% |

Relaxing the rule from "every row agrees" to the tool's own "one meaningful state (≥2 teams
and ≥5%)" would reach 743 (71%). **This was considered and rejected**: at creation the only
evidence is the club, while the assignment tool later has four signals. Being more
conservative than the pass that will look again with better evidence is the right asymmetry,
and the blank is a handoff rather than a hole. Revisit only with a reason.

## Things established here that will otherwise be re-litigated

- **Affinity WA's hardcoded `WA` is correct and stays.** It scrapes a Washington state
  league. It has created no teams in 60 days. An earlier claim in this project that it
  produced the Hawaii Rush mislabel was **wrong** — those 17 teams came in under TGS and
  were stamped WA afterwards by an opponent-copying path, and both such paths are closed
  (Step 6 disabled in #1054, the discovery chain fixed in #1055 and again by
  `src/utils/gotsport_team_details.py`).
- **Modular11 was explicitly left alone** by the operator, though it has TGS's shape at
  lower volume.
- **TGS cannot be asked directly.** Every per-team endpoint tried returns 401
  (`/Team/get-team-details-by-teamID/{id}` and four other shapes). Only the event endpoints
  are public. The club is the only signal available at creation.
- **`scrape_tgs_event.py:587` still says state "will be matched later via club name
  script"** — that script is Step 4 of `update-missing-club-and-state.yml`, which is now
  `if: false`. The comment is a stale pointer to a disabled step.

## Also open, from the prior handoff

- **~600 rows pending in the state review queue.** The operator works these in the
  dashboard's **State Review Queue** section and their calls have been right, including the
  rejections.
- **~1,900 teams no tier can decide** and that cannot be queued, because a review row needs a
  proposal. None is visible on a state board. `--set` is the only path.
- **The dashboard panel has never been exercised beyond the queue work** — it was shipped
  with a NameError that a review caught by reading, not by running.

## Next concrete action

Get PR #1063 reviewed and merged — it is the one thing already written and it stops ~600
blanks a week at the source. Then build `--fills-only` and its workflow, which is the whole
of job one. Leave corrections manual until the pass-2 comparison comes back clean.
