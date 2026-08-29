---
name: assigning-team-states
description: "Fills missing team states and corrects wrong ones in PitchRank, deciding each team from ranked evidence rather than one heuristic, with every write logged and reversible. Use when asked to fix a team's state, fill missing state codes, correct wrong states, run the state assignment sweep, work the state review queue, undo a state batch, decide which state a club belongs to, or investigate why a team appears on the wrong state board."
---

# Assigning team states

A team's state is **where its club is based**, not where it plays. Every wrong state in this
database was written by something that confused the two: an opponent's state copied onto a
team it travelled to play, a tournament host's state stamped on its visitors. The tiers below
all answer the club question, and the signals that answer the travel question are excluded on
purpose — they are why the problem exists.

The column is read by the public state boards, and it was write-once until this tool existed:
every earlier script filtered on `state_code IS NULL` in its SELECT, so nothing could correct
a wrong value and nothing recorded where a value came from. Two consequences shape everything
here. A correction is a heavier act than a fill, so it needs stronger evidence. And a run's
own report is not evidence that it did the right thing — verify against the database.

Copy this checklist and check off items as you complete them:

```
Task Progress:
- [ ] Step 1: Preflight — credentials, then prove the rules still fire
- [ ] Step 2: Take a snapshot with a dry run
- [ ] Step 3: Read the evidence before writing anything
- [ ] Step 4: Apply a small batch and verify it against the database
- [ ] Step 5: Apply the rest from the same snapshot
- [ ] Step 6: Work the review queue
- [ ] Step 7: Record what ran, and what you could not decide
```

## Step 1: Preflight

**Credentials.** The Supabase keys are in root `.env`, and `assign_team_states.py` prefers
`.env.local` when it exists. Both work on this checkout; a missing key surfaces as
`Missing SUPABASE_URL or SUPABASE_KEY` before any read.

**Prove the rules.** Run `python scripts/check_state_skill_assumptions.py`. It drives the real
decision code and asserts the behaviours this document promises: that a stored Canadian
province is never corrected, that a curated club queues rather than applies, that a correction
from a name never auto-applies, that a reverted value is not re-applied. **A failure means
this skill is now wrong, not that the codebase is broken** — fix the prose, then continue. The
measurements below the assertions never fail; they warn when a count this document quotes has
drifted more than 20%.

## Step 2: Take a snapshot with a dry run

```bash
python scripts/assign_team_states.py --out run.json
```

Writes nothing. It reads every live team, decides each one, and persists the decisions to the
`--out` file along with the state each team had at that moment.

**The dry run is the only thing that decides.** `--execute` replays the file and never
recomputes, for two reasons that both bite silently. A fill written early changes the clubmate
distribution a later team's Tier B reads, so a run that decided as it went would interfere
with itself. And the other weekly writers can move a team between the two commands, turning a
decision recorded as a fill into an unrecorded correction. Each write carries the snapshotted
state as a predicate, so a team that moved is skipped and reported rather than overwritten.

The GotSport probe costs one paid request per candidate — roughly 6,200 on a full run, routed
through ZenRows because a direct burst gets blocked. `--no-tier-a` skips it deliberately and
says so in the report. Do not confuse that with the tier being quiet: a blocked probe aborts
the run rather than deciding without evidence it was supposed to have.

## Step 3: Read the evidence before writing anything

The run prints a table of fills and corrections per tier. Before applying, know these three
things about what you are looking at.

**Corrections outnumber fills, and that is the point.** The blanks are nearly gone; the
remaining work is fixing values earlier heuristics guessed. On the 2026-08-29 run, 96% of
proposed corrections replaced a state no provider had ever reported.

**Tier B is the workhorse and it has one blind spot.** It reads the club, so a club whose
teams are *uniformly* mislabelled agrees with itself and gets its error propagated to the last
team rather than corrected. Tier E exists to catch that — see
[references/evidence-tiers.md](references/evidence-tiers.md).

**What the run says it cannot decide is as important as what it decides.** Teams no tier
reaches cannot be queued either, because a review row carries a proposal. The run counts them
and names any that are ranked Active, which means they are on a state board right now with no
state. Those need `--set`.

## Step 4: Apply a small batch and verify it against the database

```bash
python scripts/assign_team_states.py --execute --snapshot run.json --limit 50
```

Then verify — not from the run's output:

```sql
SELECT a.old_state_code, a.new_state_code, t.team_name, t.club_name, t.state_source
FROM team_state_audit a JOIN teams t ON t.team_id_master = a.team_id_master
WHERE a.applied_by = 'assign_team_states' ORDER BY a.id DESC LIMIT 20;
```

Read them as a person would: does the club name or the team name place it where the tool put
it? Gettysburg to PA and Mankato to MN are right for reasons no tier states. If one looks
wrong, it probably is — see [references/failure-modes.md](references/failure-modes.md) before
applying the rest.

## Step 5: Apply the rest from the same snapshot

```bash
python scripts/assign_team_states.py --execute --snapshot run.json
```

Same file, deliberately. Re-running the dry run first would produce a different snapshot
computed against a database the first batch already changed.

**To undo a batch**, scope by actor *and* date — both, or you will undo more than you meant:

```sql
SELECT * FROM revert_team_states(
  'assign_team_states', '2026-08-29 19:00+00', '2026-08-29 21:00+00',
  'your-name', NULL, 500, false, 'why'
);
```

It returns `(rows_changed, last_team_id)` for one page; loop, feeding `last_team_id` back as
the fifth argument, until it returns no id. Three traps: a revert scoped to an actor that
wrote nothing in the window silently reverts nothing and reports success; answers a person
gave by hand are stamped `operator` rather than `assign_team_states`, so a sweep revert leaves
them alone by design; and a team another writer has moved since the batch is skipped rather
than dragged back.

## Step 6: Work the review queue

Everything the tool would not do on its own authority is in `team_state_review_queue`, with
the tier, the confidence and the reason. The Streamlit dashboard's **State Review Queue**
section approves or rejects them.

Approving applies the change and mirrors it to the state board in the same transaction.
Rejecting changes nothing — and is the only thing that stops the same proposal being raised
again next week, so reject deliberately rather than leaving a row pending.

An approval fails if the team has moved since the row was filed. That is correct: the decision
you are looking at was computed against a state that no longer exists. Re-run the sweep.

## Step 7: Record what ran, and what you could not decide

Note the actor and the time window you used, so the batch can be found later. Then look at
what the run reported as undecidable. A team that is ranked and Active with no state is
visible on a board today; use `--set` with the reason:

```bash
python scripts/assign_team_states.py --team <uuid> --set OH --reason "why you know this" --execute
```

That writes your answer at confidence 1.0, stamped `operator`. Use it when the evidence a
person would use is not evidence the tool may act on — who a team plays is the clearest
example, and it is excluded from the tiers precisely because acting on it is what filled this
database with wrong states.

## References

- [references/evidence-tiers.md](references/evidence-tiers.md) — what each tier reads, why the
  order is what it is, and the exceptions that outrank the cascade.
- [references/failure-modes.md](references/failure-modes.md) — shapes in which the evidence has
  already been wrong, and how to recognise them.
